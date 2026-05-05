#!/usr/bin/env python3
"""
Continuous pre-screening: fetch random Danbooru images, score with XGBoost + CNN fusion,
and save high-scoring candidates to a local SQLite DB for later labeling.
"""

import io
import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
import signal
import sqlite3
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Thread
from queue import Queue

import joblib

# Graceful shutdown flag
_shutdown = False

def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True
    print(f"\nReceived signal {signum}, finishing current batch and saving progress...", flush=True)

signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)
import numpy as np
import requests

# Bypass proxy for local network requests
for k in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(k, None)
os.environ["no_proxy"] = "*"

# Force no-proxy session for all local API calls
_adapter = requests.adapters.HTTPAdapter(pool_connections=256, pool_maxsize=512)
_session = requests.Session()
_session.mount("http://", _adapter)
_session.mount("https://", _adapter)
_session.trust_env = False
_session.proxies = {"http": "", "https": ""}

# Resolve paths relative to project root
_PROJECT_ROOT = Path(__file__).parent.parent

# Load .env if available
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

def _resolve(env_key, default):
    val = os.environ.get(env_key, default)
    p = Path(val)
    return p if p.is_absolute() else _PROJECT_ROOT / p

MODEL_PATH = str(_resolve("PREFERENCE_MODEL_PATH", "classifier/model.joblib"))
CNN_MODEL_PATH = str(_resolve("CNN_MODEL_PATH", "classifier/model_aesthetic.pt"))
DANBOORU_API = os.environ.get("DANBOORU_API", "http://localhost:5001")
CANDIDATES_DB = str(_resolve("CANDIDATES_DB", "backend/candidates.db"))
GPU_INFERENCE_URL = os.environ.get("GPU_INFERENCE_URL", "")  # e.g. http://your-gpu-server:5099
GPU_BATCH_SIZE = int(os.environ.get("GPU_BATCH_SIZE", "64"))  # batch size for remote GPU
PREFETCH_PAGES = int(os.environ.get("PREFETCH_PAGES", "16"))  # accumulate N pages before sending to GPU
MIN_SCORE = 0.55
BATCH_SIZE = 64
SLEEP_BETWEEN = 2
DANBOORU_LABELS_DB = str(_PROJECT_ROOT / "backend" / "danbooru_labels.db")
TAG_WEIGHT = 0.5  # fusion: tag_weight * xgb + (1-tag_weight) * cnn


def init_db():
    conn = sqlite3.connect(CANDIDATES_DB, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            image_id INTEGER PRIMARY KEY,
            ext TEXT,
            score INTEGER,
            rating TEXT,
            tags TEXT,
            preference_score REAL NOT NULL,
            tag_score REAL,
            cnn_score REAL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_score ON candidates(preference_score DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status)")
    # Score log: records ALL scored images (including rejected low-score ones)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS score_log (
            image_id INTEGER PRIMARY KEY,
            tag_score REAL,
            cnn_score REAL,
            fused_score REAL,
            accepted INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_score_log_fused ON score_log(fused_score)")
    conn.commit()
    return conn


def get_labeled_ids():
    if not os.path.exists(DANBOORU_LABELS_DB):
        return set()
    conn = sqlite3.connect(DANBOORU_LABELS_DB)
    cur = conn.cursor()
    cur.execute("SELECT image_id FROM labels")
    ids = {r[0] for r in cur.fetchall()}
    conn.close()
    return ids


def get_existing_candidate_ids(conn):
    cur = conn.cursor()
    cur.execute("SELECT image_id FROM candidates")
    return {r[0] for r in cur.fetchall()}


def get_last_page(conn):
    """Get the last scanned page number so we can resume.
    If scan_state is empty, estimate from existing candidates count."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scan_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    row = conn.execute("SELECT value FROM scan_state WHERE key='last_page'").fetchone()
    if row:
        return int(row[0])
    # Estimate: candidates / hit_rate / per_page
    total = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    if total > 0:
        estimated_page = max(1, int(total / 0.4 / BATCH_SIZE))
        print(f"  scan_state empty, estimating page from {total} candidates → page {estimated_page}", flush=True)
        return estimated_page
    return 1


def save_last_page(conn, page):
    conn.execute("INSERT OR REPLACE INTO scan_state (key, value) VALUES ('last_page', ?)", (str(page),))
    conn.commit()


def build_tag_features(tags_str, rating, model_data):
    tag_vocab = model_data['tag_vocab']
    feature_names = model_data['feature_names']
    n_features = len(feature_names)
    x = np.zeros(n_features, dtype=np.float32)
    raw_tags = [t.strip().strip(',') for t in tags_str.split()] if tags_str else []
    image_tags = set()
    for t in raw_tags:
        image_tags.add(t)
        image_tags.add(t.replace('_', ' '))
    tag_to_idx = {t: i for i, t in enumerate(tag_vocab)}
    for tag in image_tags:
        if tag in tag_to_idx:
            x[tag_to_idx[tag]] = 1.0
    n_tags = len(tag_vocab)
    rating_map = {'general': 0, 'sensitive': 1, 'questionable': 2, 'explicit': 3}
    rating_full = {'g': 'general', 's': 'sensitive', 'q': 'questionable', 'e': 'explicit'}
    rating_name = rating_full.get(rating, '')
    if rating_name in rating_map:
        x[n_tags + rating_map[rating_name]] = 1.0
    x[n_tags + 4] = len(raw_tags)
    x[n_tags + 5] = 1.0
    return x


def fetch_batch(page=1, per_page=40):
    try:
        resp = _session.get(f"{DANBOORU_API}/search", params={
            "page": page, "per_page": per_page, "order_by": "score"
        }, timeout=15)
        resp.raise_for_status()
        return resp.json().get("results", [])
    except Exception as e:
        print(f"  API error: {e}", flush=True)
        return []


def _gpu_remote_available():
    """Check if remote GPU inference server is reachable."""
    if not GPU_INFERENCE_URL:
        return False
    try:
        resp = _session.get(f"{GPU_INFERENCE_URL}/health", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def _gpu_score_single(thumb_data: bytes) -> float | None:
    """Score a single image via remote GPU server."""
    try:
        resp = _session.post(
            f"{GPU_INFERENCE_URL}/score",
            files={"file": ("img.jpg", thumb_data, "image/jpeg")},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()["score"]
    except Exception:
        pass
    return None


def _gpu_score_batch(thumb_list: list[tuple[int, bytes]]) -> dict[int, float]:
    """Score multiple images via remote GPU server. Returns {image_id: score}."""
    if not thumb_list:
        return {}
    results = {}
    # Split into sub-batches
    for i in range(0, len(thumb_list), GPU_BATCH_SIZE):
        chunk = thumb_list[i:i + GPU_BATCH_SIZE]
        files = [
            ("files", (f"{img_id}.jpg", data, "image/jpeg"))
            for img_id, data in chunk
        ]
        try:
            resp = _session.post(
                f"{GPU_INFERENCE_URL}/score_batch",
                files=files,
                timeout=60,
            )
            if resp.status_code == 200:
                for j, entry in enumerate(resp.json()["results"]):
                    if entry["score"] is not None:
                        results[chunk[j][0]] = entry["score"]
        except Exception as e:
            print(f"  GPU batch error: {e}", flush=True)
    return results


# Number of parallel threads for thumbnail fetching
THUMB_WORKERS = int(os.environ.get("THUMB_WORKERS", "128"))


def fetch_thumbnail(image_id, ext):
    """Download thumbnail from DanbooruFinder. Returns (bytes, True) or (None, accessible)."""
    try:
        resp = _session.get(
            f"{DANBOORU_API}/thumbnail/{image_id}.{ext}",
            timeout=10
        )
        if resp.status_code == 200:
            return resp.content, True
        # 404 = file not in tar archive, skip this image entirely
        return None, resp.status_code != 404
    except Exception:
        return None, True  # network error, don't permanently skip


def check_preview_exists(image_id, ext):
    """Check if preview is accessible on DanbooruFinder."""
    try:
        resp = _session.head(
            f"{DANBOORU_API}/preview/{image_id}.{ext}",
            timeout=5
        )
        return resp.status_code == 200
    except Exception:
        return True  # network error, assume available


def run(total_batches=0, mode="tag+vision"):
    vision_only = (mode == "vision-only")

    if vision_only:
        print("Mode: vision-only (XGBoost disabled)", flush=True)
        model_data = None
        xgb_model = None
    else:
        print("Mode: tag+vision", flush=True)
        print("Loading XGBoost model...", flush=True)
        model_data = joblib.load(MODEL_PATH)
        xgb_model = model_data['model']
        print(f"  XGBoost: AUC={model_data['auc']:.4f}, vocab={len(model_data['tag_vocab'])}", flush=True)

    # Determine vision scoring mode: remote GPU > local CNN > tag-only
    use_remote_gpu = False
    cnn_model = None
    cnn_transform = None

    if GPU_INFERENCE_URL:
        if _gpu_remote_available():
            use_remote_gpu = True
            try:
                info = _session.get(f"{GPU_INFERENCE_URL}/health", timeout=5).json()
                print(f"  Vision: REMOTE GPU @ {GPU_INFERENCE_URL}", flush=True)
                print(f"    model={info.get('model_name')}, device={info.get('device')}, "
                      f"fp16={info.get('fp16')}, AUC={info.get('cv_auc', 0):.4f}", flush=True)
                print(f"    batch_size={GPU_BATCH_SIZE}", flush=True)
            except Exception:
                print(f"  Vision: REMOTE GPU @ {GPU_INFERENCE_URL} (health info unavailable)", flush=True)
        else:
            print(f"  Remote GPU at {GPU_INFERENCE_URL} unreachable, falling back to local", flush=True)

    _vision_type = None  # 'timm' or 'siglip2'
    _siglip2_processor = None
    if not use_remote_gpu and os.path.exists(CNN_MODEL_PATH):
        try:
            import torch
            import torch.nn as tnn
            from PIL import Image as PILImage

            _inf_mode = os.environ.get('INFERENCE_MODE', 'cpu')
            _use_cuda = (_inf_mode == 'local_gpu' and torch.cuda.is_available())
            _device = torch.device('cuda' if _use_cuda else 'cpu')
            checkpoint = torch.load(CNN_MODEL_PATH, map_location=_device, weights_only=False)
            model_class = checkpoint.get('model_class', 'timm')
            input_size = checkpoint.get('input_size', 224)

            if model_class == 'NaFlexClassifier':
                # --- SigLIP2 NaFlex model ---
                from transformers import AutoModel, AutoProcessor

                class NaFlexClassifier(tnn.Module):
                    def __init__(self, hf_model, num_features, dropout=0.2):
                        super().__init__()
                        self.vision_model = hf_model.vision_model
                        self.num_features = num_features
                        hidden = 512
                        self.head = tnn.Sequential(
                            tnn.LayerNorm(num_features),
                            tnn.Dropout(dropout),
                            tnn.Linear(num_features, hidden),
                            tnn.GELU(),
                            tnn.LayerNorm(hidden),
                            tnn.Dropout(dropout * 0.5),
                            tnn.Linear(hidden, 1),
                        )
                    def forward(self, pixel_values, pixel_attention_mask=None, spatial_shapes=None):
                        kwargs = {"pixel_values": pixel_values}
                        if pixel_attention_mask is not None:
                            kwargs["attention_mask"] = pixel_attention_mask
                        if spatial_shapes is not None:
                            kwargs["spatial_shapes"] = spatial_shapes
                        outputs = self.vision_model(**kwargs)
                        feats = outputs.pooler_output
                        if feats is None:
                            feats = outputs.last_hidden_state.mean(dim=1)
                        return self.head(feats)

                model_name = checkpoint['model_name']
                num_features = checkpoint.get('num_features', 1152)
                dropout = checkpoint.get('dropout', 0.2)
                hf_model = AutoModel.from_pretrained(model_name, dtype=torch.float32, local_files_only=True)
                processor = AutoProcessor.from_pretrained(model_name, local_files_only=True)
                # Apply max_num_patches from checkpoint to processor
                _max_num_patches = checkpoint.get('max_num_patches', None)
                if _max_num_patches and hasattr(processor, 'image_processor') and hasattr(processor.image_processor, 'max_num_patches'):
                    processor.image_processor.max_num_patches = _max_num_patches
                siglip_clf = NaFlexClassifier(hf_model, num_features, dropout)
                siglip_clf.load_state_dict(checkpoint['model_state_dict'])
                siglip_clf.to(_device).eval()
                cnn_model = siglip_clf
                _siglip2_processor = processor
                _vision_type = 'siglip2'
                cnn_transform = None  # SigLIP2 uses processor, not transform
                print(f"  Vision: LOCAL {'GPU' if _use_cuda else 'CPU'} {model_name} (NaFlexClassifier), "
                      f"AUC={checkpoint.get('cv_auc', 0):.4f}, device={_device}", flush=True)

            elif model_class == 'PreferenceModel':
                import timm
                from torchvision import transforms as T

                class PreferenceModel(tnn.Module):
                    def __init__(self, backbone, num_features, dropout=0.2):
                        super().__init__()
                        self.backbone = backbone
                        self.head = tnn.Sequential(
                            tnn.LayerNorm(num_features),
                            tnn.Dropout(p=dropout),
                            tnn.Linear(num_features, 256),
                            tnn.GELU(),
                            tnn.Dropout(p=dropout * 0.5),
                            tnn.Linear(256, 1),
                        )
                    def forward(self, x):
                        feats = self.backbone(x)
                        if feats.ndim == 4:
                            feats = feats.mean(dim=(2, 3))
                        elif feats.ndim == 3:
                            feats = feats.mean(dim=1)
                        return self.head(feats)

                num_features = checkpoint.get('num_features', 1024)
                dropout = checkpoint.get('dropout', 0.2)
                backbone = timm.create_model(checkpoint['model_name'], pretrained=False, num_classes=0)
                cnn = PreferenceModel(backbone, num_features, dropout)
                cnn.load_state_dict(checkpoint['model_state_dict'])
                cnn.to(_device).eval()
                _vision_type = 'timm'
                from torchvision import transforms as T
                cnn_transform = T.Compose([
                    T.Resize(int(input_size * 1.14), interpolation=T.InterpolationMode.BICUBIC),
                    T.CenterCrop(input_size),
                    T.ToTensor(),
                    T.Normalize(
                        mean=checkpoint.get('normalize_mean', [0.485, 0.456, 0.406]),
                        std=checkpoint.get('normalize_std', [0.229, 0.224, 0.225]),
                    ),
                ])
                cnn_model = cnn
                print(f"  Vision: LOCAL {'GPU' if _use_cuda else 'CPU'} {checkpoint['model_name']} ({model_class}), "
                      f"input={input_size}, AUC={checkpoint.get('cv_auc', 0):.4f}, device={_device}", flush=True)
            else:
                import timm
                from torchvision import transforms as T
                cnn = timm.create_model(checkpoint['model_name'], pretrained=False, num_classes=1)
                cnn.load_state_dict(checkpoint['model_state_dict'])
                cnn.to(_device).eval()
                _vision_type = 'timm'
                cnn_transform = T.Compose([
                    T.Resize(int(input_size * 1.14), interpolation=T.InterpolationMode.BICUBIC),
                    T.CenterCrop(input_size),
                    T.ToTensor(),
                    T.Normalize(
                        mean=checkpoint.get('normalize_mean', [0.485, 0.456, 0.406]),
                        std=checkpoint.get('normalize_std', [0.229, 0.224, 0.225]),
                    ),
                ])
                cnn_model = cnn
                print(f"  Vision: LOCAL {'GPU' if _use_cuda else 'CPU'} {checkpoint['model_name']} ({model_class}), "
                      f"input={input_size}, AUC={checkpoint.get('cv_auc', 0):.4f}, device={_device}", flush=True)
        except Exception as e:
            import traceback
            print(f"  Vision model load failed: {e}", flush=True)
            traceback.print_exc()
    elif not use_remote_gpu:
        print(f"  Vision model not found at {CNN_MODEL_PATH}, tag-only mode", flush=True)

    has_vision = use_remote_gpu or cnn_model is not None
    if vision_only and not has_vision:
        print("ERROR: vision-only mode requires a vision model (remote GPU or local CNN)!", flush=True)
        return
    if vision_only:
        print(f"  Scoring: vision-only (no tag pre-filter)", flush=True)
    else:
        print(f"  Fusion: tag_weight={TAG_WEIGHT}, cnn_weight={1-TAG_WEIGHT}"
              f"{' (vision disabled, tag-only)' if not has_vision else ''}", flush=True)

    conn = init_db()
    labeled_ids = get_labeled_ids()
    existing_ids = get_existing_candidate_ids(conn)
    skip_ids = labeled_ids | existing_ids
    print(f"Skipping {len(labeled_ids)} labeled + {len(existing_ids)} existing = {len(skip_ids)} total", flush=True)

    batch_num = 0
    total_screened = 0
    total_added = 0
    cnn_scored = 0
    gpu_errors = 0
    thumb_miss = 0   # accessible but empty thumbnail
    thumb_404 = 0    # not accessible (not in tar cache)
    video_skip = 0   # skipped video/zip files
    # Score accumulators — lifetime totals for final summary
    sum_fused = 0.0
    sum_tag = 0.0
    sum_cnn = 0.0
    cnn_added = 0  # candidates added that had a vision score
    # Per-window accumulators (reset after each periodic log)
    win_sum_fused = 0.0
    win_sum_tag = 0.0
    win_sum_cnn = 0.0
    win_added = 0
    win_cnn_added = 0
    win_max = 0.0
    win_min = 1.0
    all_max = 0.0
    all_min = 1.0
    start_time = time.time()

    page = get_last_page(conn)
    has_gpu = use_remote_gpu or cnn_model is not None

    # ========== GPU PIPELINE MODE (3-stage: pages → download+preprocess → GPU) ==========
    if has_gpu:
        import torch
        from PIL import Image as PILImage
        from queue import Empty

        _cnn_device = next(cnn_model.parameters()).device if cnn_model else None
        LOCAL_BATCH = GPU_BATCH_SIZE or 64

        # Stage 1 output: filtered candidates ready for thumbnail download
        # Each item: (img_dict, tag_prob_or_none, ext) or None sentinel
        download_q = Queue(maxsize=LOCAL_BATCH * 16)

        # Stage 2 output: preprocessed items ready for GPU batching
        # Each item: (img_dict, tag_prob, ext, tensor_or_thumbdata, status) or None sentinel
        gpu_q = Queue(maxsize=LOCAL_BATCH * 64)

        # Shared stats (updated by multiple threads, approximate is fine)
        import threading
        _stats_lock = threading.Lock()
        _p_stats = {"screened": 0, "video_skip": 0, "thumb_404": 0, "thumb_miss": 0,
                     "log_entries": [], "pages_done": 0}

        def _preprocess_tensor(thumb_data):
            """CPU-side: decode + transform → tensor (or pre-processed dict for SigLIP2)."""
            try:
                pil_img = PILImage.open(io.BytesIO(thumb_data)).convert('RGB')
                if _vision_type == 'siglip2' and _siglip2_processor is not None:
                    # Pre-process in worker thread so GPU consumer gets ready tensors
                    processed = _siglip2_processor(
                        images=[pil_img], return_tensors="pt", padding="max_length"
                    )
                    return processed  # dict of tensors
                return cnn_transform(pil_img) if cnn_transform else None
            except Exception:
                return None

        # --- Stage 1: Page fetcher (single thread) ---
        def _page_fetcher():
            """Fetch pages → XGBoost filter → push candidates to download_q."""
            nonlocal page
            p_batch_num = 0
            while not _shutdown:
                if total_batches > 0 and p_batch_num >= total_batches:
                    break
                p_batch_num += 1

                images = fetch_batch(page=page)
                page += 1
                if not images:
                    time.sleep(1)
                    continue
                new_images = [img for img in images if img["id"] not in skip_ids]
                if not new_images:
                    continue

                with _stats_lock:
                    _p_stats["screened"] += len(new_images)
                    _p_stats["pages_done"] += 1

                if vision_only:
                    for img in new_images:
                        skip_ids.add(img["id"])
                        ext = img.get("ext", "jpg")
                        if ext in ("mp4", "webm", "zip"):
                            with _stats_lock:
                                _p_stats["video_skip"] += 1
                            continue
                        download_q.put((img, None, ext))
                else:
                    X = np.array([
                        build_tag_features(img.get("tags", ""), img.get("rating", ""), model_data)
                        for img in new_images
                    ])
                    tag_probas = xgb_model.predict_proba(X)[:, 1]
                    for img, tag_prob in zip(new_images, tag_probas):
                        skip_ids.add(img["id"])
                        ext = img.get("ext", "jpg")
                        if ext in ("mp4", "webm", "zip"):
                            with _stats_lock:
                                _p_stats["video_skip"] += 1
                            continue
                        tag_prob_f = float(tag_prob)
                        if tag_prob_f < MIN_SCORE * 0.5:
                            with _stats_lock:
                                _p_stats["log_entries"].append((img["id"], tag_prob_f, None, tag_prob_f, 0))
                            continue
                        download_q.put((img, tag_prob_f, ext))

            # Sentinel for download workers
            for _ in range(THUMB_WORKERS):
                download_q.put(None)

        # --- Stage 2: Download + preprocess workers (thread pool) ---
        _download_done_count = [0]  # mutable counter for sentinel tracking

        def _download_worker():
            """Pull from download_q → fetch thumbnail → preprocess → push to gpu_q."""
            while not _shutdown:
                item = download_q.get()
                if item is None:
                    # Track how many workers got sentinel
                    with _stats_lock:
                        _download_done_count[0] += 1
                        if _download_done_count[0] >= THUMB_WORKERS:
                            gpu_q.put(None)  # signal consumer
                    return

                img, tag_prob, ext = item
                thumb_data, accessible = fetch_thumbnail(img["id"], ext)
                if not accessible:
                    with _stats_lock:
                        _p_stats["thumb_404"] += 1
                    continue
                if not thumb_data:
                    with _stats_lock:
                        _p_stats["thumb_miss"] += 1
                    if vision_only:
                        continue
                    gpu_q.put((img, tag_prob, ext, None))
                    continue

                if use_remote_gpu:
                    gpu_q.put((img, tag_prob, ext, thumb_data))
                else:
                    tensor = _preprocess_tensor(thumb_data)
                    if tensor is not None:
                        gpu_q.put((img, tag_prob, ext, tensor))
                    elif not vision_only:
                        gpu_q.put((img, tag_prob, ext, None))

        # Start pipeline threads
        fetcher = Thread(target=_page_fetcher, daemon=True)
        fetcher.start()

        download_threads = []
        for _ in range(THUMB_WORKERS):
            t = Thread(target=_download_worker, daemon=True)
            t.start()
            download_threads.append(t)

        print(f"Pipeline started: 3-stage (fetcher → {THUMB_WORKERS} download/prep → GPU consumer), "
              f"batch={LOCAL_BATCH}", flush=True)
        print(f"Resuming from page {page}", flush=True)

        # --- Stage 3: Consumer (main thread) — collect GPU batches + score ---
        def _collect_gpu_batch(max_size, timeout_s=2.0):
            """Collect up to max_size items from gpu_q, returns (items, done)."""
            items = []
            done = False
            # Block on first item
            try:
                first = gpu_q.get(timeout=2)
            except Empty:
                return items, False
            if first is None:
                return items, True
            items.append(first)
            # Drain remaining without blocking too long
            deadline = time.monotonic() + timeout_s
            while len(items) < max_size and time.monotonic() < deadline:
                try:
                    item = gpu_q.get(timeout=0.05)
                except Empty:
                    break
                if item is None:
                    done = True
                    break
                items.append(item)
            return items, done

        while not _shutdown:
            batch_num += 1
            ready, pipeline_done = _collect_gpu_batch(LOCAL_BATCH)

            # Grab accumulated stats
            with _stats_lock:
                extra_log = list(_p_stats["log_entries"])
                _p_stats["log_entries"].clear()
                batch_screened = _p_stats["screened"] - total_screened  # delta
                thumb_404 = _p_stats["thumb_404"]
                thumb_miss = _p_stats["thumb_miss"]
                video_skip = _p_stats["video_skip"]

            score_log_batch = list(extra_log)
            added_this_batch = 0

            if ready:
                if use_remote_gpu:
                    batch_items = [(img["id"], payload) for img, _, _, payload in ready if payload is not None]
                    gpu_scores = _gpu_score_batch(batch_items) if batch_items else {}

                    for img, tag_prob, ext, payload in ready:
                        cnn_prob = gpu_scores.get(img["id"]) if payload is not None else None
                        if cnn_prob is not None:
                            cnn_scored += 1
                            fused = TAG_WEIGHT * tag_prob + (1 - TAG_WEIGHT) * cnn_prob if tag_prob is not None else cnn_prob
                        else:
                            if payload is not None:
                                gpu_errors += 1
                            if tag_prob is not None:
                                fused = tag_prob
                            elif vision_only:
                                continue
                            else:
                                continue

                        accepted = 1 if fused >= MIN_SCORE else 0
                        score_log_batch.append((img["id"], tag_prob, cnn_prob, fused, accepted))
                        if accepted:
                            conn.execute(
                                """INSERT OR IGNORE INTO candidates
                                   (image_id, ext, score, rating, tags, preference_score, tag_score, cnn_score)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                                (img["id"], ext, img.get("score", 0),
                                 img.get("rating", ""), img.get("tags", ""),
                                 fused, tag_prob, cnn_prob)
                            )
                            added_this_batch += 1
                            sum_fused += fused; win_sum_fused += fused
                            if tag_prob is not None:
                                sum_tag += tag_prob; win_sum_tag += tag_prob
                            win_added += 1
                            if cnn_prob is not None:
                                sum_cnn += cnn_prob; win_sum_cnn += cnn_prob
                                cnn_added += 1; win_cnn_added += 1
                            win_max = max(win_max, fused); all_max = max(all_max, fused)
                            win_min = min(win_min, fused); all_min = min(all_min, fused)
                else:
                    # Local GPU batch inference
                    has_tensor = [(i, r) for i, r in enumerate(ready) if r[3] is not None]
                    cnn_scores_map = {}

                    if has_tensor:
                        with torch.no_grad():
                            if _vision_type == 'siglip2' and _siglip2_processor is not None:
                                # SigLIP2: tensors already pre-processed by workers, concat batch
                                batch_inputs = {}
                                for _, r in has_tensor:
                                    processed = r[3]  # dict of tensors from _preprocess_tensor
                                    for k, v in processed.items():
                                        if k not in batch_inputs:
                                            batch_inputs[k] = []
                                        batch_inputs[k].append(v)
                                inputs = {k: torch.cat(vs, dim=0).to(_cnn_device) for k, vs in batch_inputs.items()}
                                logits = cnn_model(**inputs).squeeze(-1)
                            else:
                                batch_tensor = torch.stack([r[3] for _, r in has_tensor]).to(_cnn_device)
                                logits = cnn_model(batch_tensor).squeeze(-1)
                            probs = torch.sigmoid(logits)
                            if probs.ndim == 0:
                                probs = probs.unsqueeze(0)
                            for (idx, _), prob in zip(has_tensor, probs.cpu().tolist()):
                                cnn_scores_map[idx] = prob

                    for idx, (img, tag_prob, ext, tensor) in enumerate(ready):
                        cnn_prob = cnn_scores_map.get(idx)
                        if cnn_prob is not None:
                            cnn_scored += 1
                            fused = TAG_WEIGHT * tag_prob + (1 - TAG_WEIGHT) * cnn_prob if tag_prob is not None else cnn_prob
                        else:
                            if vision_only:
                                continue
                            fused = tag_prob if tag_prob is not None else 0.0

                        accepted = 1 if fused >= MIN_SCORE else 0
                        score_log_batch.append((img["id"], tag_prob, cnn_prob, fused, accepted))
                        if accepted:
                            conn.execute(
                                """INSERT OR IGNORE INTO candidates
                                   (image_id, ext, score, rating, tags, preference_score, tag_score, cnn_score)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                                (img["id"], ext, img.get("score", 0),
                                 img.get("rating", ""), img.get("tags", ""),
                                 fused, tag_prob, cnn_prob)
                            )
                            added_this_batch += 1
                            sum_fused += fused; win_sum_fused += fused
                            if tag_prob is not None:
                                sum_tag += tag_prob; win_sum_tag += tag_prob
                            win_added += 1
                            if cnn_prob is not None:
                                sum_cnn += cnn_prob; win_sum_cnn += cnn_prob
                                cnn_added += 1; win_cnn_added += 1
                            win_max = max(win_max, fused); all_max = max(all_max, fused)
                            win_min = min(win_min, fused); all_min = min(all_min, fused)

            # DB commit
            if score_log_batch:
                conn.executemany(
                    """INSERT OR IGNORE INTO score_log
                       (image_id, tag_score, cnn_score, fused_score, accepted)
                       VALUES (?, ?, ?, ?, ?)""",
                    score_log_batch
                )
            conn.commit()
            save_last_page(conn, page)
            total_screened = _p_stats["screened"]
            total_added += added_this_batch
            elapsed = time.time() - start_time
            rate = total_screened / elapsed * 60 if elapsed > 0 else 0

            if batch_num % 3 == 0:
                if batch_num % 30 == 0:
                    labeled_ids = get_labeled_ids()
                conn_count = conn.execute("SELECT COUNT(*) FROM candidates WHERE status='pending'").fetchone()[0]
                hit_pct = total_added / max(cnn_scored, 1) * 100
                mode_tag = ("V:GPU" if use_remote_gpu else "V:CNN") if vision_only else ("GPU" if use_remote_gpu else "CNN")
                w_avg_fused = win_sum_fused / win_added if win_added else 0
                w_avg_tag = win_sum_tag / win_added if win_added else 0
                w_avg_cnn = win_sum_cnn / win_cnn_added if win_cnn_added else 0
                if vision_only:
                    score_info = f" avg_score={w_avg_fused:.3f}" if win_added else ""
                else:
                    score_info = (f" avg_fused={w_avg_fused:.3f} avg_tag={w_avg_tag:.3f}"
                                  f" avg_cnn={w_avg_cnn:.3f}" if win_cnn_added else
                                  f" avg_fused={w_avg_fused:.3f} avg_tag={w_avg_tag:.3f}")
                score_range = f" range=[{win_min:.3f},{win_max:.3f}]" if win_added else ""
                skip_info = ""
                if thumb_404 or thumb_miss or video_skip:
                    skip_info = f" skip[404={thumb_404} empty={thumb_miss} video={video_skip}]"
                dq_sz = download_q.qsize()
                gq_sz = gpu_q.qsize()
                print(f"[batch {batch_num}|{mode_tag}|dq={dq_sz} gq={gq_sz}] screened={total_screened} added={total_added} "
                      f"pending={conn_count} vision={cnn_scored} rate={rate:.0f}/min hit={hit_pct:.1f}%"
                      f"{score_info}{score_range}"
                      f"{f' gpu_err={gpu_errors}' if gpu_errors else ''}"
                      f"{skip_info}",
                      flush=True)
                win_sum_fused = win_sum_tag = win_sum_cnn = 0.0
                win_added = win_cnn_added = 0
                win_max = 0.0; win_min = 1.0

            if pipeline_done:
                break

        fetcher.join(timeout=5)
        for t in download_threads:
            t.join(timeout=3)

    # ========== NON-GPU (TAG-ONLY) MODE ==========
    else:
        print(f"Resuming from page {page} (tag-only mode)", flush=True)
        while not _shutdown:
            batch_num += 1
            if total_batches > 0 and batch_num > total_batches:
                break

            images = fetch_batch(page=page)
            page += 1
            if not images:
                time.sleep(5)
                continue
            new_images = [img for img in images if img["id"] not in skip_ids]
            if not new_images:
                time.sleep(SLEEP_BETWEEN)
                continue

            total_new_in_round = len(new_images)
            score_log_batch = []
            added_this_batch = 0

            X = np.array([
                build_tag_features(img.get("tags", ""), img.get("rating", ""), model_data)
                for img in new_images
            ])
            tag_probas = xgb_model.predict_proba(X)[:, 1]

            for img, tag_prob in zip(new_images, tag_probas):
                skip_ids.add(img["id"])
                ext = img.get("ext", "jpg")
                if ext in ("mp4", "webm", "zip"):
                    video_skip += 1
                    continue
                tag_prob_f = float(tag_prob)
                fused = tag_prob_f
                accepted = 1 if fused >= MIN_SCORE else 0
                score_log_batch.append((img["id"], tag_prob_f, None, fused, accepted))
                if accepted:
                    if not check_preview_exists(img["id"], ext):
                        continue
                    conn.execute(
                        """INSERT OR IGNORE INTO candidates
                           (image_id, ext, score, rating, tags, preference_score, tag_score, cnn_score)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (img["id"], ext, img.get("score", 0),
                         img.get("rating", ""), img.get("tags", ""),
                         fused, tag_prob_f, None)
                    )
                    added_this_batch += 1
                    sum_fused += fused; win_sum_fused += fused
                    sum_tag += tag_prob_f; win_sum_tag += tag_prob_f
                    win_added += 1
                    win_max = max(win_max, fused); all_max = max(all_max, fused)
                    win_min = min(win_min, fused); all_min = min(all_min, fused)

            if score_log_batch:
                conn.executemany(
                    """INSERT OR IGNORE INTO score_log
                       (image_id, tag_score, cnn_score, fused_score, accepted)
                       VALUES (?, ?, ?, ?, ?)""",
                    score_log_batch
                )
            conn.commit()
            save_last_page(conn, page)
            total_screened += total_new_in_round
            total_added += added_this_batch
            elapsed = time.time() - start_time
            rate = total_screened / elapsed * 60 if elapsed > 0 else 0

            if batch_num % 5 == 0:
                if batch_num % 50 == 0:
                    labeled_ids = get_labeled_ids()
                conn_count = conn.execute("SELECT COUNT(*) FROM candidates WHERE status='pending'").fetchone()[0]
                hit_pct = total_added / max(total_screened, 1) * 100
                w_avg_fused = win_sum_fused / win_added if win_added else 0
                w_avg_tag = win_sum_tag / win_added if win_added else 0
                print(f"[batch {batch_num}|TAG] screened={total_screened} added={total_added} "
                      f"pending={conn_count} rate={rate:.0f}/min hit={hit_pct:.1f}%"
                      f" avg_fused={w_avg_fused:.3f} avg_tag={w_avg_tag:.3f}"
                      f"{f' range=[{win_min:.3f},{win_max:.3f}]' if win_added else ''}"
                      f"{f' skip[video={video_skip}]' if video_skip else ''}",
                      flush=True)
                win_sum_fused = win_sum_tag = win_sum_cnn = 0.0
                win_added = win_cnn_added = 0
                win_max = 0.0; win_min = 1.0

            time.sleep(SLEEP_BETWEEN)

    # Always save progress before exit
    save_last_page(conn, page)
    elapsed = time.time() - start_time
    conn_count = conn.execute("SELECT COUNT(*) FROM candidates WHERE status='pending'").fetchone()[0]
    reason = "signal" if _shutdown else "complete"
    print(f"\nDone ({reason})! Screened {total_screened} in {elapsed/60:.1f} min, stopped at page {page}", flush=True)
    print(f"Added {total_added} (hit {total_added/max(cnn_scored,1)*100:.1f}%), screened {total_screened}, vision scored {cnn_scored}", flush=True)
    if thumb_404 or thumb_miss or video_skip:
        print(f"Skipped: thumb_404={thumb_404} thumb_empty={thumb_miss} video={video_skip}", flush=True)
    if total_added:
        avg_fused = sum_fused / total_added
        avg_tag = sum_tag / total_added
        print(f"Scores: avg_fused={avg_fused:.3f} avg_tag={avg_tag:.3f}", end="", flush=True)
        if cnn_added:
            avg_cnn = sum_cnn / cnn_added
            print(f" avg_cnn={avg_cnn:.3f} (vision on {cnn_added}/{total_added})", end="", flush=True)
        print(f" range=[{all_min:.3f},{all_max:.3f}]", flush=True)
    print(f"Pending: {conn_count}", flush=True)
    conn.close()


def rescore_candidates():
    """Re-score all pending candidates with the current vision model (batch GPU inference)."""
    import io
    import torch
    from PIL import Image as PILImage
    from concurrent.futures import ThreadPoolExecutor, as_completed

    print("=== Rescore mode: re-scoring existing candidates ===", flush=True)

    # Load vision model (same as run())
    cnn_model = None
    cnn_transform = None
    _vision_type = None
    _siglip2_processor = None
    use_remote_gpu = False

    if GPU_INFERENCE_URL and _gpu_remote_available():
        use_remote_gpu = True
        try:
            info = _session.get(f"{GPU_INFERENCE_URL}/health", timeout=5).json()
            print(f"  Vision: REMOTE GPU @ {GPU_INFERENCE_URL}", flush=True)
            print(f"    model={info.get('model_name')}, batch_size={GPU_BATCH_SIZE}", flush=True)
        except Exception:
            print(f"  Vision: REMOTE GPU @ {GPU_INFERENCE_URL}", flush=True)
    elif os.path.exists(CNN_MODEL_PATH):
        try:
            import torch.nn as tnn
            _inf_mode = os.environ.get('INFERENCE_MODE', 'cpu')
            _use_cuda = (_inf_mode == 'local_gpu' and torch.cuda.is_available())
            _device = torch.device('cuda' if _use_cuda else 'cpu')
            checkpoint = torch.load(CNN_MODEL_PATH, map_location=_device, weights_only=False)
            model_class = checkpoint.get('model_class', 'timm')

            if model_class == 'NaFlexClassifier':
                from transformers import AutoModel, AutoProcessor

                class NaFlexClassifier(tnn.Module):
                    def __init__(self, hf_model, num_features, dropout=0.2):
                        super().__init__()
                        self.vision_model = hf_model.vision_model
                        self.num_features = num_features
                        hidden = 512
                        self.head = tnn.Sequential(
                            tnn.LayerNorm(num_features), tnn.Dropout(dropout),
                            tnn.Linear(num_features, hidden), tnn.GELU(),
                            tnn.LayerNorm(hidden), tnn.Dropout(dropout * 0.5),
                            tnn.Linear(hidden, 1),
                        )
                    def forward(self, pixel_values, pixel_attention_mask=None, spatial_shapes=None):
                        kwargs = {"pixel_values": pixel_values}
                        if pixel_attention_mask is not None:
                            kwargs["attention_mask"] = pixel_attention_mask
                        if spatial_shapes is not None:
                            kwargs["spatial_shapes"] = spatial_shapes
                        outputs = self.vision_model(**kwargs)
                        feats = outputs.pooler_output if outputs.pooler_output is not None else outputs.last_hidden_state.mean(dim=1)
                        return self.head(feats)

                model_name = checkpoint['model_name']
                num_features = checkpoint.get('num_features', 1152)
                dropout = checkpoint.get('dropout', 0.2)
                hf_model = AutoModel.from_pretrained(model_name, dtype=torch.float32, local_files_only=True)
                processor = AutoProcessor.from_pretrained(model_name, local_files_only=True)
                # Apply max_num_patches from checkpoint to processor
                _max_num_patches = checkpoint.get('max_num_patches', None)
                if _max_num_patches and hasattr(processor, 'image_processor') and hasattr(processor.image_processor, 'max_num_patches'):
                    processor.image_processor.max_num_patches = _max_num_patches
                clf = NaFlexClassifier(hf_model, num_features, dropout)
                clf.load_state_dict(checkpoint['model_state_dict'])
                clf.to(_device).eval()
                cnn_model = clf
                _siglip2_processor = processor
                _vision_type = 'siglip2'
                print(f"  Vision: LOCAL {'GPU' if _use_cuda else 'CPU'} {model_name} (NaFlexClassifier), "
                      f"AUC={checkpoint.get('cv_auc', 0):.4f}", flush=True)
            else:
                import timm
                from torchvision import transforms as T

                if model_class == 'PreferenceModel':
                    class PreferenceModel(tnn.Module):
                        def __init__(self, backbone, num_features, dropout=0.2):
                            super().__init__()
                            self.backbone = backbone
                            self.head = tnn.Sequential(
                                tnn.LayerNorm(num_features), tnn.Dropout(p=dropout),
                                tnn.Linear(num_features, 256), tnn.GELU(),
                                tnn.Dropout(p=dropout * 0.5), tnn.Linear(256, 1),
                            )
                        def forward(self, x):
                            feats = self.backbone(x)
                            if feats.ndim == 4: feats = feats.mean(dim=(2, 3))
                            elif feats.ndim == 3: feats = feats.mean(dim=1)
                            return self.head(feats)

                    backbone = timm.create_model(checkpoint['model_name'], pretrained=False, num_classes=0)
                    num_features = checkpoint.get('num_features', 1024)
                    cnn = PreferenceModel(backbone, num_features, checkpoint.get('dropout', 0.2))
                    cnn.load_state_dict(checkpoint['model_state_dict'])
                else:
                    cnn = timm.create_model(checkpoint['model_name'], pretrained=False, num_classes=1)
                    cnn.load_state_dict(checkpoint['model_state_dict'])

                cnn.to(_device).eval()
                _vision_type = 'timm'
                input_size = checkpoint.get('input_size', 224)
                cnn_transform = T.Compose([
                    T.Resize(int(input_size * 1.14), interpolation=T.InterpolationMode.BICUBIC),
                    T.CenterCrop(input_size),
                    T.ToTensor(),
                    T.Normalize(
                        mean=checkpoint.get('normalize_mean', [0.485, 0.456, 0.406]),
                        std=checkpoint.get('normalize_std', [0.229, 0.224, 0.225]),
                    ),
                ])
                cnn_model = cnn
                print(f"  Vision: LOCAL {'GPU' if _use_cuda else 'CPU'} {checkpoint['model_name']} ({model_class}), "
                      f"AUC={checkpoint.get('cv_auc', 0):.4f}", flush=True)
        except Exception as e:
            import traceback
            print(f"  Vision model load failed: {e}", flush=True)
            traceback.print_exc()
    else:
        print(f"  No vision model found at {CNN_MODEL_PATH}", flush=True)

    if not use_remote_gpu and cnn_model is None:
        print("ERROR: No vision model available for rescoring!", flush=True)
        return

    _cnn_device = next(cnn_model.parameters()).device if cnn_model else None

    # Read all pending candidates
    conn = sqlite3.connect(CANDIDATES_DB, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    rows = conn.execute("SELECT image_id, ext, tag_score FROM candidates WHERE status = 'pending'").fetchall()
    conn.close()

    total = len(rows)
    print(f"Candidates to re-score: {total}", flush=True)
    if total == 0:
        print("Nothing to rescore.", flush=True)
        return

    scored = 0
    errors = 0
    batch_size = GPU_BATCH_SIZE or 48
    start_time = time.time()

    for batch_start in range(0, total, batch_size):
        if _shutdown:
            break

        batch = rows[batch_start:batch_start + batch_size]

        # Download thumbnails in parallel
        def _download_thumb(item):
            image_id, ext, tag_score = item
            try:
                url = f"{DANBOORU_API}/thumbnail/{image_id}.{ext or 'jpg'}"
                resp = _session.get(url, timeout=10)
                if resp.status_code != 200 or len(resp.content) < 100:
                    return (image_id, ext, tag_score, None)
                pil = PILImage.open(io.BytesIO(resp.content)).convert('RGB')
                return (image_id, ext, tag_score, pil)
            except Exception:
                return (image_id, ext, tag_score, None)

        with ThreadPoolExecutor(max_workers=min(THUMB_WORKERS, 16)) as pool:
            results = list(pool.map(_download_thumb, batch))

        valid = [(iid, ext, ts, pil) for iid, ext, ts, pil in results if pil is not None]
        batch_errors = len(batch) - len(valid)
        errors += batch_errors

        if not valid:
            continue

        # Batch inference
        if use_remote_gpu:
            # Remote GPU
            import base64
            encoded = []
            for _, _, _, pil in valid:
                buf = io.BytesIO()
                pil.save(buf, format='JPEG', quality=90)
                encoded.append(base64.b64encode(buf.getvalue()).decode())
            try:
                resp = _session.post(
                    f"{GPU_INFERENCE_URL}/score_batch",
                    json={"images": encoded},
                    timeout=120,
                )
                resp.raise_for_status()
                probs = resp.json().get("scores", [])
            except Exception as e:
                print(f"  Remote GPU error: {e}", flush=True)
                errors += len(valid)
                continue
        else:
            # Local inference
            with torch.no_grad():
                if _vision_type == 'siglip2' and _siglip2_processor:
                    pil_images = [pil for _, _, _, pil in valid]
                    inputs = _siglip2_processor(images=pil_images, return_tensors="pt", padding="max_length")
                    inputs = {k: v.to(_cnn_device) for k, v in inputs.items()}
                    logits = cnn_model(**inputs).squeeze(-1)
                else:
                    tensors = []
                    for _, _, _, pil in valid:
                        tensors.append(cnn_transform(pil))
                    batch_tensor = torch.stack(tensors).to(_cnn_device)
                    logits = cnn_model(batch_tensor).squeeze(-1)
                probs_t = torch.sigmoid(logits)
                if probs_t.ndim == 0:
                    probs_t = probs_t.unsqueeze(0)
                probs = probs_t.cpu().tolist()

        # Update DB
        conn = sqlite3.connect(CANDIDATES_DB, timeout=30)
        conn.execute("PRAGMA busy_timeout=30000")
        for (iid, ext, tag_score, _), cnn_score in zip(valid, probs):
            fused = TAG_WEIGHT * tag_score + (1 - TAG_WEIGHT) * cnn_score if tag_score is not None else cnn_score
            conn.execute(
                "UPDATE candidates SET cnn_score = ?, preference_score = ? WHERE image_id = ?",
                (cnn_score, fused, iid),
            )
            scored += 1
        conn.commit()
        conn.close()

        elapsed = time.time() - start_time
        rate = scored / elapsed if elapsed > 0 else 0
        print(f"  Progress: {scored}/{total} ({rate:.1f}/s), errors: {errors}", flush=True)

    elapsed = time.time() - start_time
    print(f"Rescore done: {scored} scored, {errors} errors, {elapsed:.1f}s", flush=True)

    # GPU cleanup
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--batches", type=int, default=0)
    parser.add_argument("--min-score", type=float, default=MIN_SCORE)
    parser.add_argument("--sleep", type=float, default=SLEEP_BETWEEN)
    parser.add_argument("--tag-weight", type=float, default=TAG_WEIGHT)
    parser.add_argument("--reset-page", action="store_true", help="Reset scan to page 1")
    parser.add_argument("--gpu-url", type=str, default=GPU_INFERENCE_URL,
                        help="Remote GPU inference URL (overrides GPU_INFERENCE_URL env)")
    parser.add_argument("--gpu-batch", type=int, default=GPU_BATCH_SIZE,
                        help="Batch size for remote GPU scoring")
    parser.add_argument("--prefetch-pages", type=int, default=PREFETCH_PAGES,
                        help="Pages to accumulate before GPU inference (default: 3)")
    parser.add_argument("--thumb-workers", type=int, default=THUMB_WORKERS,
                        help="Parallel thumbnail download threads (default: 8)")
    parser.add_argument("--mode", choices=["tag+vision", "vision-only"], default="tag+vision",
                        help="Scoring mode: tag+vision (XGBoost + CNN) or vision-only (CNN/GPU only)")
    parser.add_argument("--rescore", action="store_true",
                        help="Re-score existing candidates with current vision model (batch GPU)")
    args = parser.parse_args()
    MIN_SCORE = args.min_score
    SLEEP_BETWEEN = args.sleep
    TAG_WEIGHT = args.tag_weight
    GPU_INFERENCE_URL = args.gpu_url
    GPU_BATCH_SIZE = args.gpu_batch
    PREFETCH_PAGES = args.prefetch_pages
    THUMB_WORKERS = args.thumb_workers
    if args.reset_page:
        conn = sqlite3.connect(CANDIDATES_DB, timeout=30)
        conn.execute("CREATE TABLE IF NOT EXISTS scan_state (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("DELETE FROM scan_state WHERE key='last_page'")
        conn.commit()
        conn.close()
        print("Page reset to 1")

    if args.rescore:
        rescore_candidates()
    else:
        run(args.batches, mode=args.mode)
