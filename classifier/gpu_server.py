#!/usr/bin/env python3
"""
GPU Inference Server for Sieve Preference Classifier.

Deploy on any machine with a GPU. Loads the vision model once,
serves scoring requests via HTTP.

Usage:
    python gpu_server.py --model model_aesthetic.pt --port 5099
    python gpu_server.py --model model_aesthetic.pt --port 5099 --device cuda:0

Endpoints:
    POST /score        - Score a single image (multipart upload)
    POST /score_batch  - Score multiple images (multipart upload)
    GET  /health       - Health check + model info
"""

import argparse
import io
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import torch
import timm
from PIL import Image as PILImage
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

from model_defs import PreferenceModel, NaFlexClassifier, build_timm_transform

app = FastAPI(title="Sieve GPU Inference")

_model = None
_transform = None
_device = None
_model_info = {}


def load_model(model_path: str, device: str):
    global _model, _transform, _device, _model_info
    _device = torch.device(device)

    checkpoint = torch.load(model_path, map_location=_device, weights_only=False)
    model_class = checkpoint.get("model_class", "timm")
    model_name = checkpoint["model_name"]
    input_size = checkpoint.get("input_size", 224)

    if model_class == "PreferenceModel":
        num_features = checkpoint.get("num_features", 1024)
        dropout = checkpoint.get("dropout", 0.2)
        backbone = timm.create_model(model_name, pretrained=False, num_classes=0)
        model = PreferenceModel(backbone, num_features, dropout)
        model.load_state_dict(checkpoint["model_state_dict"])
    elif model_class == "NaFlexClassifier":
        from transformers import AutoModel, AutoProcessor
        num_features = checkpoint.get("num_features", 1152)
        dropout = checkpoint.get("dropout", 0.2)
        hf_model = AutoModel.from_pretrained(model_name, local_files_only=True)
        model = NaFlexClassifier(hf_model, num_features, dropout)
        model.load_state_dict(checkpoint["model_state_dict"])
    else:
        model = timm.create_model(model_name, pretrained=False, num_classes=1)
        model.load_state_dict(checkpoint["model_state_dict"])

    model = model.to(_device).eval()

    if _device.type == "cuda":
        model = model.half()

    _model = model
    if model_class == "NaFlexClassifier":
        _transform = None
    else:
        _transform = build_timm_transform(
            input_size,
            checkpoint.get("normalize_mean", [0.485, 0.456, 0.406]),
            checkpoint.get("normalize_std", [0.229, 0.224, 0.225]),
        )

    _model_info = {
        "model_name": model_name,
        "model_class": model_class,
        "input_size": input_size,
        "cv_auc": checkpoint.get("cv_auc", 0),
        "device": str(_device),
        "fp16": _device.type == "cuda",
    }
    print(f"Loaded {model_name} ({model_class}) on {_device}, input={input_size}")


def _score_image(img_bytes: bytes) -> float:
    """Score a single image, return sigmoid probability."""
    pil_img = PILImage.open(io.BytesIO(img_bytes)).convert("RGB")
    tensor = _transform(pil_img).unsqueeze(0).to(_device)
    if _device.type == "cuda":
        tensor = tensor.half()
    with torch.no_grad():
        logit = _model(tensor).squeeze()
        return torch.sigmoid(logit).item()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        **_model_info,
        "gpu_memory_mb": (
            torch.cuda.memory_allocated(_device) / 1024 / 1024
            if _device.type == "cuda" else None
        ),
    }


@app.post("/score")
async def score(file: UploadFile = File(...)):
    """Score a single image. Returns {"score": float, "ms": float}."""
    try:
        data = await file.read()
        t0 = time.monotonic()
        prob = _score_image(data)
        ms = (time.monotonic() - t0) * 1000
        return {"score": prob, "ms": round(ms, 1)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/score_batch")
async def score_batch(files: list[UploadFile] = File(...)):
    """Score multiple images in one request. Returns list of scores."""
    if len(files) > 128:
        raise HTTPException(400, "Max 128 images per batch")

    t0 = time.monotonic()

    # Read all file data first (async I/O)
    raw_data = []
    for f in files:
        raw_data.append(await f.read())

    # Parallel CPU preprocessing using thread pool
    def _preprocess(data: bytes):
        try:
            pil_img = PILImage.open(io.BytesIO(data)).convert("RGB")
            return _transform(pil_img), None
        except Exception as e:
            return None, str(e)

    with ThreadPoolExecutor(max_workers=min(8, len(raw_data))) as pool:
        prep_results = list(pool.map(_preprocess, raw_data))

    tensors = [r[0] for r in prep_results]
    errors = [r[1] for r in prep_results]

    # Score valid images as a batch
    valid_indices = [i for i, t in enumerate(tensors) if t is not None]
    scores = [None] * len(tensors)

    if valid_indices:
        batch = torch.stack([tensors[i] for i in valid_indices]).to(_device)
        if _device.type == "cuda":
            batch = batch.half()
        with torch.no_grad():
            # Process in sub-batches to avoid GPU OOM on very large requests
            MAX_GPU_BATCH = 64
            all_probs = []
            for start in range(0, batch.shape[0], MAX_GPU_BATCH):
                sub = batch[start:start + MAX_GPU_BATCH]
                logits = _model(sub).squeeze(-1)
                probs = torch.sigmoid(logits)
                if probs.ndim == 0:
                    probs = probs.unsqueeze(0)
                all_probs.append(probs)
            all_probs = torch.cat(all_probs).cpu().tolist()
            for idx, prob in zip(valid_indices, all_probs):
                scores[idx] = prob

    ms = (time.monotonic() - t0) * 1000
    results = []
    for i in range(len(files)):
        results.append({
            "index": i,
            "score": scores[i],
            "error": errors[i],
        })

    return {"results": results, "ms": round(ms, 1), "batch_size": len(files)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sieve GPU Inference Server")
    parser.add_argument("--model", required=True, help="Path to .pt checkpoint")
    parser.add_argument("--port", type=int, default=5099)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--device", default="cuda:0", help="torch device (cuda:0, cpu, ...)")
    args = parser.parse_args()

    load_model(args.model, args.device)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
