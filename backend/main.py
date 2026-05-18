import asyncio
import logging
import os
import sqlite3

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
    CANDIDATES_DB_PATH,
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
    animation,
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

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _scan_pt_models() -> None:
    import gc
    import glob as _glob

    classifier_dir = PROJECT_ROOT / "classifier"
    pt_files = sorted(_glob.glob(str(classifier_dir / "*.pt")))
    pt_files = [f for f in pt_files if not f.endswith(".bak.pt")]
    logger.info("[models] Scanning %s: found %d .pt files", classifier_dir, len(pt_files))

    for pt_path in pt_files:
        pt_name = Path(pt_path).stem
        try:
            import torch

            try:
                checkpoint = torch.load(pt_path, map_location="cpu", weights_only=True)
            except Exception:
                checkpoint = torch.load(pt_path, map_location="cpu", weights_only=False)
            model_class = checkpoint.get("model_class", "timm")
            model_name = checkpoint.get("model_name", pt_name)

            if model_class == "NaFlexClassifier":
                num_features = checkpoint.get("num_features", 1152)
                state._models[pt_name] = {
                    "model": None,
                    "transform": None,
                    "processor": None,
                    "type": "siglip2",
                    "cv_auc": checkpoint.get("cv_auc", 0),
                    "n_samples": checkpoint.get("n_samples", 0),
                    "model_name": model_name,
                    "model_class": "NaFlexClassifier",
                    "input_size": "variable",
                    "num_features": num_features,
                    "fold_aucs": checkpoint.get("fold_aucs", []),
                    "max_num_patches": checkpoint.get("max_num_patches", 256),
                    "source_file": Path(pt_path).name,
                    "_pt_path": pt_path,
                }
                if state._active_model is None:
                    state._active_model = pt_name
                logger.info(
                    "[models] Registered %s: %s (NaFlexClassifier), AUC=%.4f [lazy]",
                    pt_name,
                    model_name,
                    checkpoint.get("cv_auc", 0),
                )

            elif model_class in ("PreferenceModel", "timm"):
                input_size = checkpoint.get("input_size", 224)
                state._models[pt_name] = {
                    "model": None,
                    "transform": None,
                    "processor": None,
                    "type": "timm",
                    "cv_auc": checkpoint.get("cv_auc", 0),
                    "n_samples": checkpoint.get("n_samples", 0),
                    "model_name": model_name,
                    "model_class": model_class,
                    "input_size": input_size,
                    "fold_aucs": checkpoint.get("fold_aucs", []),
                    "source_file": Path(pt_path).name,
                    "_pt_path": pt_path,
                }
                if state._active_model is None:
                    state._active_model = pt_name
                logger.info(
                    "[models] Registered %s: %s (%s), AUC=%.4f [lazy]",
                    pt_name,
                    model_name,
                    model_class,
                    checkpoint.get("cv_auc", 0),
                )
            else:
                logger.warning("[models] Skipping %s: unknown model_class '%s'", pt_name, model_class)

            del checkpoint
        except Exception as e:
            logger.warning("[models] Failed to scan %s: %s", pt_name, e)

    gc.collect()
    logger.info(
        "[models] Registered models: %s, active: %s (lazy loading enabled)",
        list(state._models.keys()),
        state._active_model,
    )


async def _init_subprocess_dirs() -> None:
    if not DB_PATH.exists():
        raise RuntimeError(f"Database not found: {DB_PATH}")
    if not CRAWLER_DIR.exists():
        raise RuntimeError(f"CRAWLER_DIR does not exist: {CRAWLER_DIR}")
    state.THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    _init_labels_db()
    _init_auto_tags_table()
    _init_danbooru_labels_db()

    _check_cuda_available()
    if state._cuda_available_cached:
        logger.info("[inference] CUDA available: %s", _cuda_info())
    else:
        logger.info("[inference] CUDA not available, CPU only")

    if PREFERENCE_MODEL_PATH.exists():
        try:
            state._preference_model = await asyncio.to_thread(joblib.load, PREFERENCE_MODEL_PATH)
            logger.info(
                "[preference] XGBoost loaded: AUC=%.4f, vocab=%d tags",
                state._preference_model["auc"],
                len(state._preference_model["tag_vocab"]),
            )
        except Exception as e:
            logger.warning("[preference] Failed to load XGBoost: %s", e)
            state._preference_model = None
    else:
        logger.info("[preference] XGBoost not found at %s", PREFERENCE_MODEL_PATH)

    state._inference_device = "cpu"


async def _scan_model_registry() -> None:
    await asyncio.to_thread(_scan_pt_models)


async def _init_db_indexes() -> None:
    with get_sync_db(readonly=False) as conn:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_images_file_created_at ON images(file_path, created_at DESC)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_images_source_file_created_at ON images(source, file_path, created_at DESC)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_novels_file_created_at ON novels(file_path, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_novels_title_author ON novels(title, author)")

    if CANDIDATES_DB_PATH.exists():
        with sqlite3.connect(str(CANDIDATES_DB_PATH), timeout=30) as cconn:
            cconn.execute("PRAGMA journal_mode=WAL")
            cconn.execute(
                "CREATE INDEX IF NOT EXISTS idx_candidates_status_score ON candidates(status, preference_score DESC)"
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _init_subprocess_dirs()
    await _scan_model_registry()
    await _init_db_indexes()
    yield
    # Terminate any running subprocesses tracked by ManagedSubprocess instances.
    for proc_mgr in state._subprocesses.values():
        await proc_mgr.cleanup()

    if state._db_pool is not None:
        await state._db_pool.close()
        state._db_pool = None
    if state._labels_pool is not None:
        await state._labels_pool.close()
        state._labels_pool = None
    if state._danbooru_labels_pool is not None:
        await state._danbooru_labels_pool.close()
        state._danbooru_labels_pool = None
    if state._candidates_pool is not None:
        await state._candidates_pool.close()
        state._candidates_pool = None
    if state._danbooru_client is not None:
        await state._danbooru_client.aclose()
        state._danbooru_client = None

    for executor in [state._image_executor, state._io_executor, state._db_executor]:
        executor.shutdown(wait=False)


app = FastAPI(title="Sieve", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class MaxBodySizeMiddleware:
    def __init__(self, app, max_size: int = 1_000_000):
        self.app = app
        self.max_size = max_size

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        content_length = 0
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"content-length":
                try:
                    content_length = int(header_value)
                except (ValueError, TypeError):
                    pass
                break
        if content_length > self.max_size:
            await send(
                {
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"detail":"Request body too large"}',
                }
            )
            return
        await self.app(scope, receive, send)


app.add_middleware(MaxBodySizeMiddleware, max_size=1_000_000)

# ---------------------------------------------------------------------------
# Include routers
# ---------------------------------------------------------------------------
app.include_router(thumbnails.router)
app.include_router(animation.router)
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
        if not state._safe_under_crawler(full_path):
            raise HTTPException(status_code=403, detail="Forbidden")
        if full_path.exists():
            return _range_file_response(full_path, request)
    raise HTTPException(status_code=404, detail="File not found")


if state.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=state.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file = state.FRONTEND_DIST / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(state.FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
