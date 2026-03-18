#!/usr/bin/env python3
"""
Continuous pre-screening: fetch random Danbooru images, score with XGBoost + CNN fusion,
and save high-scoring candidates to a local SQLite DB for later labeling.
"""

import io
import os
import signal
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

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
_session = requests.Session()
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
MIN_SCORE = 0.55
BATCH_SIZE = 40
SLEEP_BETWEEN = 1
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


def run(total_batches=0):
    print("Loading XGBoost model...", flush=True)
    model_data = joblib.load(MODEL_PATH)
    xgb_model = model_data['model']
    print(f"  XGBoost: AUC={model_data['auc']:.4f}, vocab={len(model_data['tag_vocab'])}", flush=True)

    # Load CNN/Vision model
    cnn_model = None
    cnn_transform = None
    if os.path.exists(CNN_MODEL_PATH):
        try:
            import torch
            import timm
            import torch.nn as tnn
            from torchvision import transforms as T
            from PIL import Image as PILImage

            checkpoint = torch.load(CNN_MODEL_PATH, map_location='cpu', weights_only=False)
            model_class = checkpoint.get('model_class', 'timm')
            input_size = checkpoint.get('input_size', 224)

            if model_class == 'PreferenceModel':
                # Custom PreferenceModel: timm backbone (num_classes=0) + head
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
            else:
                # Legacy: plain timm model with num_classes=1
                cnn = timm.create_model(checkpoint['model_name'], pretrained=False, num_classes=1)
                cnn.load_state_dict(checkpoint['model_state_dict'])

            cnn.eval()
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
            print(f"  Vision: {checkpoint['model_name']} ({model_class}), "
                  f"input={input_size}, AUC={checkpoint.get('cv_auc', 0):.4f}", flush=True)
        except Exception as e:
            print(f"  Vision model load failed: {e}", flush=True)
    else:
        print(f"  Vision model not found at {CNN_MODEL_PATH}", flush=True)

    print(f"  Fusion: tag_weight={TAG_WEIGHT}, cnn_weight={1-TAG_WEIGHT}", flush=True)

    conn = init_db()
    labeled_ids = get_labeled_ids()
    existing_ids = get_existing_candidate_ids(conn)
    skip_ids = labeled_ids | existing_ids
    print(f"Skipping {len(labeled_ids)} labeled + {len(existing_ids)} existing = {len(skip_ids)} total", flush=True)

    batch_num = 0
    total_screened = 0
    total_added = 0
    cnn_scored = 0
    start_time = time.time()

    page = get_last_page(conn)
    print(f"Resuming from page {page}", flush=True)
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

        # XGBoost batch scoring
        X = np.array([
            build_tag_features(img.get("tags", ""), img.get("rating", ""), model_data)
            for img in new_images
        ])
        tag_probas = xgb_model.predict_proba(X)[:, 1]

        added_this_batch = 0
        for img, tag_prob in zip(new_images, tag_probas):
            skip_ids.add(img["id"])

            # Skip videos entirely — not useful for review
            ext = img.get("ext", "jpg")
            if ext in ("mp4", "webm", "zip"):
                continue

            # Quick filter: if tag score is very low, skip CNN
            if tag_prob < MIN_SCORE * 0.5:
                continue

            # CNN scoring
            cnn_prob = None
            fused = float(tag_prob)

            if cnn_model is not None:
                thumb_data, accessible = fetch_thumbnail(img["id"], ext)
                if not accessible:
                    # Image not in DanbooruFinder tar cache, skip entirely
                    continue
                if thumb_data:
                    try:
                        from PIL import Image as PILImage
                        import torch
                        pil_img = PILImage.open(io.BytesIO(thumb_data)).convert('RGB')
                        tensor = cnn_transform(pil_img).unsqueeze(0)
                        with torch.no_grad():
                            logit = cnn_model(tensor).squeeze()
                            cnn_prob = torch.sigmoid(logit).item()
                        fused = TAG_WEIGHT * float(tag_prob) + (1 - TAG_WEIGHT) * cnn_prob
                        cnn_scored += 1
                    except Exception:
                        pass
            else:
                # No CNN model, but still check if image exists
                if not check_preview_exists(img["id"], ext):
                    continue

            if fused >= MIN_SCORE:
                conn.execute(
                    """INSERT OR IGNORE INTO candidates
                       (image_id, ext, score, rating, tags, preference_score, tag_score, cnn_score)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (img["id"], ext, img.get("score", 0),
                     img.get("rating", ""), img.get("tags", ""),
                     fused, float(tag_prob), cnn_prob)
                )
                added_this_batch += 1

        conn.commit()
        save_last_page(conn, page)
        total_screened += len(new_images)
        total_added += added_this_batch
        elapsed = time.time() - start_time
        rate = total_screened / elapsed * 60 if elapsed > 0 else 0

        if batch_num % 5 == 0:
            if batch_num % 50 == 0:
                labeled_ids = get_labeled_ids()

            conn_count = conn.execute("SELECT COUNT(*) FROM candidates WHERE status='pending'").fetchone()[0]
            hit_pct = total_added / max(total_screened, 1) * 100
            print(f"[batch {batch_num}] screened={total_screened} added={total_added} "
                  f"pending={conn_count} cnn={cnn_scored} rate={rate:.0f}/min hit={hit_pct:.1f}%",
                  flush=True)

        time.sleep(SLEEP_BETWEEN)

    # Always save progress before exit
    save_last_page(conn, page)
    elapsed = time.time() - start_time
    conn_count = conn.execute("SELECT COUNT(*) FROM candidates WHERE status='pending'").fetchone()[0]
    reason = "signal" if _shutdown else "complete"
    print(f"\nDone ({reason})! Screened {total_screened} in {elapsed/60:.1f} min, stopped at page {page}", flush=True)
    print(f"Added {total_added} (hit {total_added/max(total_screened,1)*100:.1f}%), CNN scored {cnn_scored}", flush=True)
    print(f"Pending: {conn_count}", flush=True)
    conn.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--batches", type=int, default=0)
    parser.add_argument("--min-score", type=float, default=MIN_SCORE)
    parser.add_argument("--sleep", type=float, default=SLEEP_BETWEEN)
    parser.add_argument("--tag-weight", type=float, default=TAG_WEIGHT)
    parser.add_argument("--reset-page", action="store_true", help="Reset scan to page 1")
    args = parser.parse_args()
    MIN_SCORE = args.min_score
    SLEEP_BETWEEN = args.sleep
    TAG_WEIGHT = args.tag_weight
    if args.reset_page:
        conn = sqlite3.connect(CANDIDATES_DB, timeout=30)
        conn.execute("CREATE TABLE IF NOT EXISTS scan_state (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("DELETE FROM scan_state WHERE key='last_page'")
        conn.commit()
        conn.close()
        print("Page reset to 1")
    run(args.batches)
