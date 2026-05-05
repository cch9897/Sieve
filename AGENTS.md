# Repository Guidelines

## Project Overview

Sieve (booru-gallery) is a personal artwork curation tool. A FastAPI backend serves a React SPA and orchestrates ML subprocesses for image classification, auto-tagging, and preference scoring. The frontend provides gallery browsing, Tinder-style labeling, Danbooru integration, novel reading, and statistics dashboards.

## Architecture & Data Flow

Three-process system with no shared memory:

```
Frontend (React SPA)  →  /api/*  →  FastAPI routers  →  SQLite (aiosqlite)  →  JSON
                                            ↓
                                   subprocess.Popen  →  classifier/ scripts
                                            ↓
                                   ML models (lazy-loaded .pt / eager joblib)
```

- **Frontend → Backend**: All requests via `api.ts` fetch wrapper to relative `/api/...` paths. No CORS in production (same-origin).
- **Labeling flow**: Frontend POSTs verdict → router writes labels.db → `cache_clear()` invalidates TTL cache.
- **ML ops flow**: Frontend triggers → `ml_ops` router spawns `subprocess.Popen` → tracked by `state._*_process` + `asyncio.Lock` pair → logs polled via tail-read endpoint → model hot-reloaded on completion.
- **Image serving**: `/images/{path}` → `_safe_under_crawler()` path traversal check → `_range_file_response()` (HTTP Range for video).
- **Thumbnails**: `/api/thumb/{path}` → cache check → generate in `_image_executor` thread pool → cache to `.thumbs/`.

## Key Directories

| Path | Purpose |
|------|---------|
| `backend/` | FastAPI application — API server, image serving, SPA hosting, ML orchestrator |
| `backend/routers/` | API route modules (one `APIRouter` per domain, included by `main.py`) |
| `backend/tests/` | Pytest test suite with shared fixtures in `conftest.py` |
| `frontend/src/` | React SPA source — single stateful root in `App.tsx` |
| `frontend/src/components/` | React components organized by feature (labeler/, danbooru-labeler/) |
| `frontend/src/__tests__/` | Vitest test files |
| `frontend/src/test/` | Test infrastructure (MSW handlers, setup) |
| `classifier/` | Standalone ML scripts — training, scoring, packing, prefetching |
| `classifier/integrations/` | Site-specific scripts (remote pack, Twitter tagger) |

## Development Commands

### Backend (Python 3.13)

```bash
cd backend && python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt                          # runtime
pip install -r requirements-test.txt                     # test deps (extends above)
uvicorn main:app --host 0.0.0.0 --port 8780 --reload    # dev server
pytest                                                   # all tests
pytest tests/test_images.py::test_name                   # single test
ruff check backend/                                      # lint
ruff format backend/                                     # format
```

### Frontend (Node 20, npm)

```bash
cd frontend
npm install
npm run dev        # Vite dev server (proxies /api and /images to :8780)
npm run build      # tsc && vite build → frontend/dist
npm run test       # vitest run (jsdom + MSW)
npx tsc --noEmit   # type-check only
```

The backend serves `frontend/dist` as SPA fallback. Run `npm run build` once for the production UI to work.

### Configuration

All config via `.env` at repo root (loaded by `backend/config.py`). `CRAWLER_DIR` is **required** — backend refuses to start without it, and `dedup.db` must exist at `$CRAWLER_DIR/dedup.db`. See `.env.example` for full variable list.

## Code Conventions & Common Patterns

### State access (critical)

`backend/state.py` is the single source of truth for all mutable globals. **Always use attribute lookup (`state.xxx`), never `from state import xxx`** — the latter creates a stale snapshot and breaks lifespan-managed state. This is documented in the module docstring and is the most common footgun.

### Async patterns

- Backend is fully async (FastAPI + aiosqlite). Blocking work (image processing, file I/O, ML inference) dispatched to dedicated `ThreadPoolExecutor`s: `_image_executor`, `_io_executor`, `_db_executor`.
- `asyncio.to_thread()` wraps blocking checks in routers.
- TTL cache via custom `@ttl_cache(seconds, maxsize)` decorator in `backend/utils.py` — async-safe with thread lock and eviction.

### Database access

- Raw SQLite via aiosqlite — **no ORM**. All queries are parameterized SQL strings.
- Cross-database JOINs use SQLite `ATTACH DATABASE` (labels.db ATTACHes dedup.db as `main_db`).
- Read-only database (`dedup.db`) opened with `mode=ro` + `PRAGMA query_only=ON`. Never write to it.
- Schema defined inline in `database.py` with auto-migration on startup (e.g., composite PK migration for `vision_scores`).

### Subprocess management

ML subprocesses follow a consistent pattern per job type:
- `subprocess.Popen` with `start_new_session=True`
- Process handle + `asyncio.Lock` pair stored in `state.py` — only one of each job type can run at a time
- Log file handle tracked for tail-read endpoints
- `pgrep` fallback for detecting externally-started processes

### Frontend state

All state lives in `App.tsx`. No external state library (no Redux, Zustand). Views switched by keyboard shortcut or nav. State persisted to `localStorage` under key `sieve-ui-state` with debounced writes. Non-gallery views lazy-loaded.

### API client

`frontend/src/api.ts` is the sole HTTP client. Features:
- `apiFetch<T>()` with 30s timeout and `AbortSignal` support
- Request deduplication via `inFlightRequests` map
- Custom `ApiError` class
- All types defined inline — keep in sync with backend schemas when changing API responses

### Path security

All user-facing file serving routes through `state._safe_under_crawler(path)`, which resolves symlinks against `_ALLOWED_ROOTS`. When adding file-serving endpoints, always use this check and return 403 on failure.

### Styling

Tailwind CSS 3 with design-token system: CSS custom properties (`--bg`, `--accent`, etc.) mapped to `ed-*` Tailwind color utilities via `frontend/tailwind.config.js`. No CSS-in-JS.

### Component organization

- Feature components in subdirectories: `components/labeler/`, `components/danbooru-labeler/`
- Shared components at `components/` root: `ImageGrid`, `Lightbox`, `FilterBar`, `ErrorBoundary`
- Custom hooks in `hooks/`: `useFocusTrap`
- Utility functions in `utils.ts`, source metadata in `sourceMeta.ts`

## Important Files

| File | Role |
|------|------|
| `backend/main.py` | FastAPI entry point. Lifespan: validates DBs, loads models, creates indexes. Includes all 14 routers. Serves images with path traversal protection. Mounts SPA. |
| `backend/config.py` | Env-based configuration. All paths resolved relative to `PROJECT_ROOT`. |
| `backend/state.py` | Centralized mutable state: DB pools, model registry, subprocess handles, locks, caches, thread pools. |
| `backend/database.py` | DB connection management. Singleton async pools. Schema + auto-migration. |
| `backend/models.py` | ML model lifecycle: lazy weight loading, device migration, fusion scoring, hot-reload. |
| `backend/utils.py` | `@ttl_cache`, range file response, novel meta cache, path date extraction. |
| `frontend/src/App.tsx` | Sole stateful component. All view routing, filters, pagination, lightbox state. |
| `frontend/src/api.ts` | HTTP client with timeout, dedup, and typed responses. |
| `frontend/src/types.ts` | TypeScript interfaces mirroring backend response shapes. |
| `backend/tests/conftest.py` | Test fixture stack: `tmp_crawler`, `patch_config`, `reset_state`, `app` (no-ML lifespan), `client`. |
| `start.sh` | Production launcher: venv creation, pip sync, uvicorn on :8780. |
| `.env.example` | Template for all environment variables. |

## Runtime/Tooling Preferences

| Concern | Choice |
|---------|--------|
| Python version | 3.13 |
| Node version | 20 |
| Python package manager | pip + venv (no Poetry/Pipenv) |
| Frontend package manager | npm (package-lock.json) |
| Backend framework | FastAPI + uvicorn |
| Frontend framework | React 18 + Vite 5 + TypeScript 5.6 (strict) |
| Styling | Tailwind CSS 3 (no CSS-in-JS) |
| Database | SQLite via aiosqlite (no ORM) |
| Python linter | Ruff (line-length 120, target py313, select E/F/W/I, ignore E501) |
| Frontend type-checking | `tsc --noEmit` (strict mode, noUnusedLocals, noUnusedParameters) |
| Frontend linter | None (no ESLint/Prettier — strict TS compiler is the gate) |
| ML runtime | PyTorch (CUDA optional, CPU fallback) |
| No Docker | No containerization — production runs via `start.sh` |

## Testing & QA

### Backend (pytest)

- Framework: pytest 8.x + pytest-asyncio (auto mode)
- Location: `backend/tests/test_*.py`
- Fixtures in `conftest.py`: `tmp_crawler` (temp DB + fake PNGs), `patch_config` (monkeypatch all paths), `reset_state` (zero globals), `app` (FastAPI with no-ML lifespan), `client` (httpx AsyncClient over ASGITransport)
- **Never import ML models or run the real lifespan in tests** — use the no-ML `app` fixture
- Run: `cd backend && pytest tests/ -v --tb=short`

### Frontend (Vitest)

- Framework: Vitest 4.x + @testing-library/react + MSW 2.x
- Location: `frontend/src/__tests__/*.test.tsx`
- MSW handlers in `frontend/src/test/handlers.ts` mock all `/api/*` endpoints
- Setup in `frontend/src/test/setup.ts` manages MSW server lifecycle
- Run: `cd frontend && npx vitest run`

### CI (GitHub Actions)

Triggered on push/PR to `main`. Two jobs:
- **Backend**: Python 3.13 → `ruff check` → `pip-audit` → `pytest` with `CRAWLER_DIR=/tmp/test_crawler`
- **Frontend**: Node 20 → `npm ci` → `npm audit --production` → `tsc --noEmit` → `vitest run` → `npm run build`

### Known gaps

- No coverage measurement or enforcement
- No E2E tests (no Playwright/Cypress)
- No frontend linting beyond `tsc --noEmit`
- No pre-commit hooks
- Frontend test coverage is minimal (2 test files)
- MSW handlers return identical data — no edge-case or error scenario tests
