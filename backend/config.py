import os
from pathlib import Path

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

PROJECT_ROOT = Path(__file__).parent.parent

# Data sources
CRAWLER_DIR = Path(os.environ.get("CRAWLER_DIR", ""))
if not CRAWLER_DIR.is_absolute():
    CRAWLER_DIR = PROJECT_ROOT / CRAWLER_DIR
DB_PATH = CRAWLER_DIR / "dedup.db"
DOWNLOADS_DIR = CRAWLER_DIR / "downloads"

# Server
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8780"))

# Labels DB (always in backend/)
LABELS_DB_PATH = Path(__file__).parent / "labels.db"

# DanbooruFinder
DANBOORU_API = os.environ.get("DANBOORU_API", "http://localhost:5001")
DANBOORU_LABELS_DB_PATH = Path(__file__).parent / "danbooru_labels.db"
DANBOORU_LIKES_DIR = Path(os.environ.get("DANBOORU_LIKES_DIR", PROJECT_ROOT / "data" / "danbooru_liked"))

# Preference classifier models
_model_path = os.environ.get("PREFERENCE_MODEL_PATH", "classifier/model.joblib")
PREFERENCE_MODEL_PATH = Path(_model_path) if Path(_model_path).is_absolute() else PROJECT_ROOT / _model_path

_cnn_path = os.environ.get("CNN_MODEL_PATH", "classifier/model_aesthetic.pt")
CNN_MODEL_PATH = Path(_cnn_path) if Path(_cnn_path).is_absolute() else PROJECT_ROOT / _cnn_path

_siglip2_path = os.environ.get("SIGLIP2_MODEL_PATH", "classifier/model_siglip2_naflex.pt")
SIGLIP2_MODEL_PATH = Path(_siglip2_path) if Path(_siglip2_path).is_absolute() else PROJECT_ROOT / _siglip2_path

# Candidates DB
_candidates = os.environ.get("CANDIDATES_DB", "backend/candidates.db")
CANDIDATES_DB_PATH = Path(_candidates) if Path(_candidates).is_absolute() else PROJECT_ROOT / _candidates
