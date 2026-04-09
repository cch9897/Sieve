import os

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import joblib
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import state
from config import (
    CRAWLER_DIR,
    DB_PATH,
    HOST,
    PORT,
    PREFERENCE_MODEL_PATH,
    PROJECT_ROOT,
)
from database import _init_auto_tags_table, _init_danbooru_labels_db, _init_labels_db, get_sync_db
from models import _check_cuda_available, _cuda_info
from routers import (
    autotags,
    danbooru_candidates,
    danbooru_labeler,
    danbooru_proxy,
    danbooru_recommend,
    images,
    labeler,
    ml_ops,
    multi_model,
    novels,
    stats,
    thumbnails,
    vision_scores,
)
from utils import _range_file_response

FRONTEND_DIST = state.FRONTEND_DIST
THUMBS_DIR = state.THUMBS_DIR
_safe_under_crawler = state._safe_under_crawler


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DB_PATH.exists():
        raise RuntimeError(f"Database not found: {DB_PATH}")
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    _init_labels_db()
    _init_auto_tags_table()
    _init_danbooru_labels_db()

    # Pre-check CUDA availability at startup
    _check_cuda_available()
    if state._cuda_available_cached:
        print(f"[inference] CUDA available: {_cuda_info()}")
    else:
        print("[inference] CUDA not available, CPU only")

    # Load preference models
    if PREFERENCE_MODEL_PATH.exists():
        try:
            state._preference_model = joblib.load(PREFERENCE_MODEL_PATH)
            print(f"[preference] XGBoost loaded: AUC={state._preference_model['auc']:.4f}, "
                  f"vocab={len(state._preference_model['tag_vocab'])} tags")
        except Exception as e:
            print(f"[preference] Failed to load XGBoost: {e}")
            state._preference_model = None
    else:
        print(f"[preference] XGBoost not found at {PREFERENCE_MODEL_PATH}")

    # Models use lazy loading: only metadata is read at startup, weights loaded on first inference.
    state._inference_device = "cpu"

    # --- Auto-scan .pt model files from classifier/ (metadata only, no weight loading) ---
    import glob as _glob
    classifier_dir = PROJECT_ROOT / "classifier"
    pt_files = sorted(_glob.glob(str(classifier_dir / "*.pt")))
    pt_files = [f for f in pt_files if not f.endswith('.bak.pt')]
    print(f"[models] Scanning {classifier_dir}: found {len(pt_files)} .pt files")

    for pt_path in pt_files:
        pt_name = Path(pt_path).stem
        try:
            import torch
            # Load only metadata (keys), not full tensors — use weights_only=False but
            # we only read scalar metadata then discard the checkpoint immediately.
            checkpoint = torch.load(pt_path, map_location="cpu", weights_only=False)
            model_class = checkpoint.get('model_class', 'timm')
            model_name = checkpoint.get('model_name', pt_name)

            if model_class == 'NaFlexClassifier':
                num_features = checkpoint.get('num_features', 1152)
                state._models[pt_name] = {
                    'model': None, 'transform': None, 'processor': None,
                    'type': 'siglip2',
                    'cv_auc': checkpoint.get('cv_auc', 0),
                    'n_samples': checkpoint.get('n_samples', 0),
                    'model_name': model_name,
                    'model_class': 'NaFlexClassifier',
                    'input_size': 'variable',
                    'num_features': num_features,
                    'fold_aucs': checkpoint.get('fold_aucs', []),
                    'max_num_patches': checkpoint.get('max_num_patches', 256),
                    'source_file': Path(pt_path).name,
                    '_pt_path': pt_path,
                }
                if state._active_model is None:
                    state._active_model = pt_name
                print(f"[models] Registered {pt_name}: {model_name} (NaFlexClassifier), AUC={checkpoint.get('cv_auc', 0):.4f} [lazy]")

            elif model_class in ('PreferenceModel', 'timm'):
                input_size = checkpoint.get('input_size', 224)
                state._models[pt_name] = {
                    'model': None, 'transform': None, 'processor': None,
                    'type': 'timm',
                    'cv_auc': checkpoint.get('cv_auc', 0),
                    'n_samples': checkpoint.get('n_samples', 0),
                    'model_name': model_name,
                    'model_class': model_class,
                    'input_size': input_size,
                    'fold_aucs': checkpoint.get('fold_aucs', []),
                    'source_file': Path(pt_path).name,
                    '_pt_path': pt_path,
                }
                if state._active_model is None:
                    state._active_model = pt_name
                print(f"[models] Registered {pt_name}: {model_name} ({model_class}), AUC={checkpoint.get('cv_auc', 0):.4f} [lazy]")
            else:
                print(f"[models] Skipping {pt_name}: unknown model_class '{model_class}'")

            del checkpoint  # free memory immediately
        except Exception as e:
            print(f"[models] Failed to scan {pt_name}: {e}")

    import gc
    gc.collect()
    print(f"[models] Registered models: {list(state._models.keys())}, active: {state._active_model} (lazy loading enabled)")

    with get_sync_db(readonly=False) as conn:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_images_file_created_at ON images(file_path, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_images_source_file_created_at ON images(source, file_path, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_novels_file_created_at ON novels(file_path, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_novels_title_author ON novels(title, author)")

    yield
    if state._db_pool is not None:
        await state._db_pool.close()
        state._db_pool = None
    if state._labels_pool is not None:
        await state._labels_pool.close()
        state._labels_pool = None
    if state._danbooru_labels_pool is not None:
        await state._danbooru_labels_pool.close()
        state._danbooru_labels_pool = None
    if state._danbooru_client is not None:
        await state._danbooru_client.aclose()
        state._danbooru_client = None


app = FastAPI(title="Sieve", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Include routers
# ---------------------------------------------------------------------------
app.include_router(thumbnails.router)
app.include_router(images.router)
app.include_router(novels.router)
app.include_router(stats.router)
app.include_router(labeler.router)
app.include_router(ml_ops.router)
app.include_router(vision_scores.router)
app.include_router(multi_model.router)
app.include_router(autotags.router)
app.include_router(danbooru_proxy.router)
app.include_router(danbooru_recommend.router)
app.include_router(danbooru_candidates.router)
app.include_router(danbooru_labeler.router)


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------

@app.get("/images/{file_path:path}")
async def serve_image(file_path: str, request: Request):
    for candidate in [file_path, quote(file_path, safe="/")]:
        full_path = CRAWLER_DIR / candidate
        if not _safe_under_crawler(full_path):
            raise HTTPException(status_code=403, detail="Forbidden")
        if full_path.exists():
            return _range_file_response(full_path, request)
    raise HTTPException(status_code=404, detail="File not found")


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file = FRONTEND_DIST / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
