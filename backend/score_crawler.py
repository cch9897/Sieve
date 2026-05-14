#!/usr/bin/env python3
"""
Score crawler images using vision models (EVA02/timm + SigLIP2 NaFlex).
Stores scores in the vision_scores table of labels.db (multi-model, composite PK).
Uses batch GPU inference + threaded preprocessing for speed.
"""

import argparse
import logging
import os
import signal
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Graceful shutdown
_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True
    logger.info("Received signal %d, finishing current batch...", signum)


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

_BACKEND_DIR = Path(__file__).parent
_PROJECT_ROOT = _BACKEND_DIR.parent

try:
    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

CRAWLER_DIR = Path(os.environ.get("CRAWLER_DIR", ""))
if not CRAWLER_DIR.is_absolute():
    CRAWLER_DIR = _PROJECT_ROOT / CRAWLER_DIR
DB_PATH = CRAWLER_DIR / "dedup.db"
LABELS_DB_PATH = _BACKEND_DIR / "labels.db"

CLASSIFIER_DIR = _PROJECT_ROOT / "classifier"

# Legacy env vars (single model paths) — still respected if set
_cnn_path = os.environ.get("CNN_MODEL_PATH", "")
CNN_MODEL_PATH = (
    (Path(_cnn_path) if Path(_cnn_path).is_absolute() else _PROJECT_ROOT / _cnn_path) if _cnn_path else None
)

_siglip2_path = os.environ.get("SIGLIP2_MODEL_PATH", "")
SIGLIP2_MODEL_PATH = (
    (Path(_siglip2_path) if Path(_siglip2_path).is_absolute() else _PROJECT_ROOT / _siglip2_path)
    if _siglip2_path
    else None
)

VIDEO_EXTS = {".mp4", ".webm", ".avi", ".mov", ".mkv"}
SKIP_EXTS = {".zip", ".rar", ".7z", ".gz"}
BATCH_SIZE = int(os.environ.get("SCORE_BATCH_SIZE", "48"))
PREPROCESS_WORKERS = int(os.environ.get("SCORE_WORKERS", "4"))


def init_vision_scores_table(conn: sqlite3.Connection):
    """Create or migrate vision_scores table to multi-model format."""
    cur = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='vision_scores'")
    row = cur.fetchone()
    if row:
        ddl = row[0] or ""
        if "PRIMARY KEY (image_id, model_name)" not in ddl:
            logger.info("[db] Migrating vision_scores to multi-model format...")
            conn.execute("ALTER TABLE vision_scores RENAME TO vision_scores_old")
            conn.execute("""
                CREATE TABLE vision_scores (
                    image_id INTEGER NOT NULL,
                    model_name TEXT NOT NULL,
                    score REAL NOT NULL,
                    scored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (image_id, model_name)
                )
            """)
            conn.execute("""
                INSERT INTO vision_scores (image_id, model_name, score, scored_at)
                SELECT image_id, 'default', score, scored_at FROM vision_scores_old
            """)
            conn.execute("DROP TABLE vision_scores_old")
            logger.info("[db] Migration complete.")
    else:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vision_scores (
                image_id INTEGER NOT NULL,
                model_name TEXT NOT NULL,
                score REAL NOT NULL,
                scored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (image_id, model_name)
            )
        """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vision_scores_score ON vision_scores(score DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vision_scores_model ON vision_scores(model_name)")
    conn.commit()


def _discover_model_paths() -> dict:
    """Scan classifier/ for .pt files and classify by model_class in checkpoint metadata."""
    import torch

    result = {"eva02": [], "siglip2": []}
    if not CLASSIFIER_DIR.exists():
        return result
    for pt in sorted(CLASSIFIER_DIR.glob("*.pt")):
        try:
            meta = torch.load(str(pt), map_location="cpu", weights_only=False)
            mc = meta.get("model_class", "timm")
            if mc == "NaFlexClassifier":
                result["siglip2"].append(pt)
            elif mc in ("PreferenceModel", "timm"):
                result["eva02"].append(pt)
        except Exception:
            pass
    return result


def load_eva02_model(path: Path | None = None):
    """Load EVA02/timm model. Returns (model, transform, device, model_name) or None."""
    model_path = path or CNN_MODEL_PATH
    if model_path is None or not model_path.exists():
        # Try auto-discover
        discovered = _discover_model_paths()
        if discovered["eva02"]:
            model_path = discovered["eva02"][-1]  # latest by name
        else:
            logger.warning("EVA02 model not found")
            return None

    import timm
    import torch

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    checkpoint = torch.load(str(model_path), map_location=device, weights_only=False)

    model_name = checkpoint["model_name"]
    model_class = checkpoint.get("model_class", "timm")
    input_size = checkpoint.get("input_size", 224)
    dropout = checkpoint.get("dropout", 0.3)

    if model_class == "PreferenceModel":
        import sys

        sys.path.insert(0, str(CLASSIFIER_DIR))
        from model_defs import PreferenceModel

        backbone = timm.create_model(model_name, pretrained=False, num_classes=0)
        num_features = backbone.num_features
        model = PreferenceModel(backbone, num_features, dropout)
        model.load_state_dict(checkpoint["model_state_dict"])
    else:
        model = timm.create_model(model_name, pretrained=False, num_classes=checkpoint.get("num_classes", 1))
        model.load_state_dict(checkpoint["model_state_dict"])

    model.to(device)
    model.eval()

    mean = checkpoint.get("normalize_mean", [0.485, 0.456, 0.406])
    std = checkpoint.get("normalize_std", [0.229, 0.224, 0.225])
    from model_defs import build_timm_transform

    transform = build_timm_transform(input_size, mean, std)

    logger.info("Loaded EVA02: %s (%s), input=%d, device=%s", model_name, model_class, input_size, device)
    return model, transform, device, model_name


def load_siglip2_model(path: Path | None = None):
    """Load SigLIP2 NaFlex model. Returns (model, processor, device, model_name) or None."""
    model_path = path or SIGLIP2_MODEL_PATH
    if model_path is None or not model_path.exists():
        # Try auto-discover
        discovered = _discover_model_paths()
        if discovered["siglip2"]:
            model_path = discovered["siglip2"][-1]
        else:
            logger.warning("SigLIP2 model not found")
            return None

    try:
        import torch
        from transformers import AutoModel, AutoProcessor
    except ImportError:
        logger.warning("transformers not installed, skipping SigLIP2")
        return None

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    checkpoint = torch.load(str(model_path), map_location=device, weights_only=False)

    model_name = checkpoint["model_name"]
    num_features = checkpoint.get("num_features", 1152)
    dropout = checkpoint.get("dropout", 0.2)

    import sys

    sys.path.insert(0, str(CLASSIFIER_DIR))
    from model_defs import NaFlexClassifier

    hf_model = AutoModel.from_pretrained(model_name, local_files_only=True)
    processor = AutoProcessor.from_pretrained(model_name, local_files_only=True)
    clf = NaFlexClassifier(hf_model, num_features, dropout)
    clf.load_state_dict(checkpoint["model_state_dict"])
    clf.to(device)
    clf.eval()

    logger.info("Loaded SigLIP2: %s, AUC=%.4f, device=%s", model_name, checkpoint.get("cv_auc", 0), device)
    return clf, processor, device, model_name


def preprocess_one_timm(args):
    """Preprocess a single image for timm model. Returns (image_id, tensor) or (image_id, None)."""
    image_id, path, transform = args
    from PIL import Image as PILImage

    try:
        img = PILImage.open(path).convert("RGB")
        tensor = transform(img)
        return (image_id, tensor)
    except Exception:
        return (image_id, None)


def preprocess_one_siglip(args):
    """Preprocess a single image for SigLIP2. Returns (image_id, pil_img) or (image_id, None)."""
    image_id, path = args
    from PIL import Image as PILImage

    try:
        img = PILImage.open(path).convert("RGB")
        return (image_id, img)
    except Exception:
        return (image_id, None)


def score_with_eva02(model, transform, device, to_score, labels_conn, model_name):
    """Score images with EVA02/timm model."""
    import torch

    scored = 0
    errors = 0
    start = time.time()

    for batch_start in range(0, len(to_score), BATCH_SIZE):
        if _shutdown:
            break

        batch = to_score[batch_start : batch_start + BATCH_SIZE]
        prep_args = [(img_id, path, transform) for img_id, path in batch]
        with ThreadPoolExecutor(max_workers=PREPROCESS_WORKERS) as pool:
            prep_results = list(pool.map(preprocess_one_timm, prep_args))

        valid = [(img_id, tensor) for img_id, tensor in prep_results if tensor is not None]
        errors += len(prep_results) - len(valid)

        if not valid:
            continue

        ids = [img_id for img_id, _ in valid]
        batch_tensor = torch.stack([t for _, t in valid]).to(device)

        with torch.no_grad():
            logits = model(batch_tensor).squeeze(-1)
            probs = torch.sigmoid(logits)
            if probs.ndim == 0:
                probs = probs.unsqueeze(0)
            scores = probs.cpu().tolist()

        results = [(img_id, score, model_name) for img_id, score in zip(ids, scores)]
        labels_conn.executemany(
            "INSERT OR REPLACE INTO vision_scores (image_id, score, model_name) VALUES (?, ?, ?)", results
        )
        labels_conn.commit()
        scored += len(results)

        elapsed = time.time() - start
        rate = scored / elapsed if elapsed > 0 else 0
        logger.info("[eva02] Progress: %d/%d (%.1f/s), errors: %d", scored, len(to_score), rate, errors)

    elapsed = time.time() - start
    logger.info("[eva02] Done: scored %d, errors %d, time %.1fs", scored, errors, elapsed)
    return scored, errors


def score_with_siglip2(model, processor, device, to_score, labels_conn, model_name):
    """Score images with SigLIP2 NaFlex model."""
    import torch

    scored = 0
    errors = 0
    start = time.time()
    # SigLIP2 NaFlex has variable input, use smaller batches
    siglip_batch = min(BATCH_SIZE, 16)

    for batch_start in range(0, len(to_score), siglip_batch):
        if _shutdown:
            break

        batch = to_score[batch_start : batch_start + siglip_batch]
        prep_args = [(img_id, path) for img_id, path in batch]
        with ThreadPoolExecutor(max_workers=PREPROCESS_WORKERS) as pool:
            prep_results = list(pool.map(preprocess_one_siglip, prep_args))

        valid = [(img_id, img) for img_id, img in prep_results if img is not None]
        errors += len(prep_results) - len(valid)

        if not valid:
            continue

        ids = [img_id for img_id, _ in valid]
        pil_images = [img for _, img in valid]

        try:
            inputs = processor(images=pil_images, return_tensors="pt", padding=True)
            inputs = {k: v.to(device) for k, v in inputs.items()}

            with torch.no_grad():
                logits = model(**inputs).squeeze(-1)
                probs = torch.sigmoid(logits)
                if probs.ndim == 0:
                    probs = probs.unsqueeze(0)
                scores = probs.cpu().tolist()

            results = [(img_id, score, model_name) for img_id, score in zip(ids, scores)]
            labels_conn.executemany(
                "INSERT OR REPLACE INTO vision_scores (image_id, score, model_name) VALUES (?, ?, ?)", results
            )
            labels_conn.commit()
            scored += len(results)
        except Exception:
            # Fallback: score one by one
            for img_id, pil_img in zip(ids, pil_images):
                try:
                    inp = processor(images=pil_img, return_tensors="pt")
                    inp = {k: v.to(device) for k, v in inp.items()}
                    with torch.no_grad():
                        logit = model(**inp).squeeze()
                        prob = torch.sigmoid(logit).item()
                    labels_conn.execute(
                        "INSERT OR REPLACE INTO vision_scores (image_id, score, model_name) VALUES (?, ?, ?)",
                        (img_id, prob, model_name),
                    )
                    scored += 1
                except Exception:
                    errors += 1
            labels_conn.commit()

        elapsed = time.time() - start
        rate = scored / elapsed if elapsed > 0 else 0
        logger.info("[siglip2] Progress: %d/%d (%.1f/s), errors: %d", scored, len(to_score), rate, errors)

    elapsed = time.time() - start
    logger.info("[siglip2] Done: scored %d, errors %d, time %.1fs", scored, errors, elapsed)
    return scored, errors


def main():
    parser = argparse.ArgumentParser(description="Score crawler images with vision models")
    parser.add_argument(
        "--model",
        choices=["eva02", "siglip2", "all"],
        default="all",
        help="Which model type to use for scoring (default: all)",
    )
    parser.add_argument(
        "--model-path", type=str, default=None, help="Explicit .pt file path to use (overrides --model auto-discovery)"
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        logger.error("Crawler DB not found: %s", DB_PATH)
        sys.exit(1)

    # Open DBs
    labels_conn = sqlite3.connect(str(LABELS_DB_PATH), timeout=30)
    labels_conn.execute("PRAGMA journal_mode=WAL")
    labels_conn.execute("PRAGMA busy_timeout=30000")
    init_vision_scores_table(labels_conn)

    crawler_conn = sqlite3.connect(str(DB_PATH), timeout=10)
    crawler_conn.row_factory = sqlite3.Row

    # Load requested models
    eva02_result = None
    siglip2_result = None
    explicit_path = Path(args.model_path) if args.model_path else None

    if args.model in ("eva02", "all"):
        eva02_result = load_eva02_model(explicit_path if args.model == "eva02" else None)
    if args.model in ("siglip2", "all"):
        siglip2_result = load_siglip2_model(explicit_path if args.model == "siglip2" else None)

    if not eva02_result and not siglip2_result:
        logger.error("No models could be loaded, exiting.")
        sys.exit(1)

    # Get all images from crawler (skip videos/archives)
    rows = crawler_conn.execute("SELECT id, file_path FROM images WHERE file_path IS NOT NULL").fetchall()

    all_images = []
    for r in rows:
        ext = Path(r["file_path"]).suffix.lower()
        if ext in VIDEO_EXTS or ext in SKIP_EXTS:
            continue
        full_path = CRAWLER_DIR / r["file_path"]
        if full_path.exists():
            all_images.append((r["id"], full_path))

    logger.info("Total scorable images: %d", len(all_images))

    # Score with each model
    if eva02_result and not _shutdown:
        model, transform, device, model_name = eva02_result
        scored_ids = set(
            r[0]
            for r in labels_conn.execute(
                "SELECT image_id FROM vision_scores WHERE model_name = ?", (model_name,)
            ).fetchall()
        )
        to_score = [(img_id, path) for img_id, path in all_images if img_id not in scored_ids]
        logger.info("[eva02] Already scored: %d, to score: %d", len(scored_ids), len(to_score))
        if to_score:
            score_with_eva02(model, transform, device, to_score, labels_conn, model_name)
        # Free memory
        del model, transform
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    if siglip2_result and not _shutdown:
        model, processor, device, model_name = siglip2_result
        scored_ids = set(
            r[0]
            for r in labels_conn.execute(
                "SELECT image_id FROM vision_scores WHERE model_name = ?", (model_name,)
            ).fetchall()
        )
        to_score = [(img_id, path) for img_id, path in all_images if img_id not in scored_ids]
        logger.info("[siglip2] Already scored: %d, to score: %d", len(scored_ids), len(to_score))
        if to_score:
            score_with_siglip2(model, processor, device, to_score, labels_conn, model_name)
        # Free memory
        del model, processor
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    # Final GPU cleanup
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            logger.info("[cleanup] GPU memory released")
    except Exception:
        pass

    crawler_conn.close()
    labels_conn.close()
    logger.info("All done.")


if __name__ == "__main__":
    main()
