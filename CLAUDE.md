# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (FastAPI, Python 3.13)
```bash
# First-time setup
cd backend && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# Run server (from repo root)
./start.sh                              # venv + uvicorn on :8780
# Or dev-mode with reload:
cd backend && source venv/bin/activate && uvicorn main:app --host 0.0.0.0 --port 8780 --reload

# Tests (pytest-asyncio auto-mode, testpaths=tests)
cd backend && source venv/bin/activate && pip install -r requirements-test.txt
pytest                                  # all
pytest tests/test_images.py             # one file
pytest tests/test_images.py::test_name  # one test
pytest -k "expression"

# Lint (ruff, line-length=120, ignores E501; tests/ allows E402)
ruff check backend/
ruff format backend/
```

### Frontend (React + TypeScript + Vite + Tailwind)
```bash
cd frontend
npm install
npm run dev      # vite dev server (proxies to backend)
npm run build    # tsc && vite build → frontend/dist (served by FastAPI)
npm run test     # vitest run (jsdom + MSW)
```

The backend serves `frontend/dist` as the SPA fallback, so you must run `npm run build` at least once for the production route (`/`) to return the UI. In dev, run the Vite server separately.

### Configuration

All config is env-based via `.env` at repo root (loaded by `backend/config.py` via python-dotenv). `CRAWLER_DIR` is **required** — the backend refuses to start without it, and the crawler's `dedup.db` must exist at `$CRAWLER_DIR/dedup.db`. See `.env.example` for the full list.

## Architecture

### Three-process system

1. **FastAPI backend** (`backend/`) — serves API, thumbnails, images, and the built SPA.
2. **React SPA** (`frontend/`) — single-page app; all state in `App.tsx` persisted via `localStorage` under `sieve-ui-state`.
3. **Classifier pipeline** (`classifier/`) — standalone scripts the backend launches as subprocesses (retrain, pack, prefetch, rescore, vision-score, tag-train).

The backend is the orchestrator: ML-ops router endpoints spawn `classifier/*.sh` / `classifier/*.py` via `ManagedSubprocess` from `backend/subprocess_manager.py`, which wraps `subprocess.Popen` + an `asyncio.Lock` + log-tail buffer (one manager per long-running job kind, registered in `state._subprocesses`). Only one of each can run at a time.

### Service layer (`backend/services/`)

Routers stay thin; the heavy lifting lives next door:

- `labeler_service.py` — label / unlabel / tag CRUD shared by `labeler` and `danbooru_labeler`.
- `danbooru_candidates_repo.py` — read-only stats aggregations (buckets, histogram, CI) over `candidates.db`, used by `danbooru_recommend`.
- `export_service.py` — `build_export_zip()` wraps `export_utils.build_zip_to_temp` + `StreamingResponse` for the two `/export/liked` endpoints.

### Three databases

- `$CRAWLER_DIR/dedup.db` — **read-only**, owned by the external booru-crawler project. The async pool opens it with `mode=ro` + `PRAGMA query_only=ON`. Never write to it. Indexes are added at lifespan startup (`main.py`) but only via the sync connection with `mode=rwc` — writes target indexes, not data.
- `backend/labels.db` — user labels, tags, vision scores, auto-tags. Writable. Multi-model vision scores use composite PK `(image_id, model_name)`; `database.py` auto-migrates from the old single-PK schema on startup.
- `backend/danbooru_labels.db` — separate Danbooru labeler state.
- `backend/candidates.db` — AI pre-screening queue populated by `prefetch_candidates.py`.

### Global state pattern

`backend/state.py` is the single source of truth for mutable globals (DB pools, model registry, subprocess handles, locks, caches). **Always access via attribute lookup (`state.xxx`), never `from state import xxx`** — the latter creates a stale snapshot and breaks lifespan-managed state. This is called out in the module docstring and is easy to get wrong.

### ML model registry

At startup, `main.py` scans `classifier/*.pt` and registers metadata **without loading weights** (lazy-load on first inference). Each checkpoint's `model_class` field dispatches to one of:
- `NaFlexClassifier` → SigLIP2 NaFlex (variable input size)
- `PreferenceModel` / `timm` → timm backbone + optional custom head

Weights are loaded into `state._models[key]['model']` on demand by the multi-model router. The registry coexists with the legacy XGBoost tag model (`PREFERENCE_MODEL_PATH`, joblib) which is eagerly loaded at startup. Fusion scoring combines both: `score = tag_weight × xgb + (1 - tag_weight) × vision`.

### Router layout (`backend/routers/`)

Each file is a `APIRouter` included by `main.py`. Domains:
- `images`, `novels`, `thumbnails`, `stats` — gallery read paths
- `labeler`, `danbooru_labeler` — like/dislike/skip writes
- `autotags`, `vision_scores`, `multi_model` — tagging + scoring
- `ml_ops` — subprocess orchestration (retrain, pack, prefetch, etc.)
- `danbooru_proxy`, `danbooru_recommend`, `danbooru_candidates` — DanbooruFinder integration

### Path security

All user-facing file serving goes through `state._safe_under_crawler(path)`, which resolves symlinks against `_ALLOWED_ROOTS`. The set is seeded with `CRAWLER_DIR.resolve()` and (if `$CRAWLER_DIR/downloads` is a symlink) its target's parent — this is intentional for NFS setups. When adding new file-serving endpoints, route through `_safe_under_crawler` and return 403 on failure; do not construct paths ad-hoc.

For writes outside `CRAWLER_DIR` (e.g. the Danbooru likes downloader writing to `DANBOORU_LIKES_DIR`), don't reuse `_safe_under_crawler`: validate the extension with a strict regex *and* verify `dest.resolve().is_relative_to(root.resolve())`. See `routers/danbooru_labeler._is_safe_ext` and the `/danbooru/label/{id}` download path for the pattern.

### Tests

`backend/tests/conftest.py` defines the canonical fixture stack: `tmp_crawler` builds a minimal `dedup.db` + fake PNG files in a tmpdir, `patch_config` monkeypatches every path in `config` **and rebinds `CRAWLER_DIR` on already-imported modules** (`utils`, `state`, `auto_tagger`, …) that did `from config import CRAWLER_DIR` at import time, `reset_state` zeroes out pools + model registry + clears `_novel_meta_cache`, and `app` builds a FastAPI app with a **no-ML lifespan** (it skips the `.pt` scan and joblib load). Use `client` (AsyncClient over ASGITransport) for endpoint tests. Never import models or run the real lifespan in tests.

Routers not mounted on the default test `app` (e.g. `danbooru_recommend`, `danbooru_candidates`) get a custom client fixture that also re-binds their module-level `*_DB_PATH` constants after the monkeypatch — see `test_danbooru_recommend.dr_client` / `test_danbooru_candidates.dc_client`.

### Frontend entry

`frontend/src/App.tsx` orchestrates state and view switching but delegates work to hooks under `frontend/src/hooks/`:
- `useGalleryFilters` / `useNovelFilters` — filter+sort state with localStorage persistence.
- `useGallery` — image list fetch / pagination / infinite scroll, surfacing `errorKind` ('network' | 'empty') so the shell renders the right `EmptyState`.
- `useTaskPoller` — generic polling for `ml_ops` long-running jobs.
- `useFocusTrap` — modal focus containment, used by `Lightbox` and any dialog.
- `usePersistedState` — typed `useState` mirrored to localStorage.

View switching uses URL hash (`#gallery` / `#novels` / `#labeler` / `#danbooru` / `#stats`) with `pushState` + `popstate` so the browser back button works, and CSS [View Transitions API](https://developer.mozilla.org/docs/Web/API/View_Transitions_API) for a cross-fade between views.

API requests go through `frontend/src/api/` (split into `core` + per-domain modules; `index.ts` re-exports). All requests are relative `/api/...` paths (same origin, no CORS in prod). `types.ts` mirrors backend response shapes by hand; keep them in sync when changing API schemas.
