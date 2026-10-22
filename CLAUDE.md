# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

개발사업성 분석 V6: a real-estate development feasibility tool. A prebuilt React dashboard (`frontend/build/V6.template.html`) talks to a Python backend that calls Korean public APIs (VWorld, data.go.kr, Juso, KOSIS, SGIS) and runs the financial analysis engine. UI text, errors and comments are mostly Korean; keep that.

## Running

There is one server: the FastAPI app in `app/` (the old stdlib server `V6.py`/`backend/pf_server.py` was removed). `backend/` is the domain layer it uses.

## Commands

```sh
cp .env.example .env                # MYSQL_* = the user's EXISTING MySQL container, plus API keys
docker compose up -d --build        # api only → http://127.0.0.1:4175/
python -m app                       # same server without Docker (loads .env, 127.0.0.1:PUBLIC_PORT)

# Tests (unittest, no network/keys/MySQL). Interpreter needs requirements.txt installed.
python tests/run_tests.py
python -m unittest discover -s tests -p "test_engine.py"      # one file (set PYTHONPATH=backend;tests;.)
```

`tests/test_app_api.py` and `tests/test_app_storage.py` exercise `app/` against SQLite via `DATABASE_URL`. There is no linter config. Frontend (`frontend/`) is rebuilt separately with Node (`npm ci && npm run build`, copy `dist/index.html` to `frontend/build/V6.template.html`); its `AGENTS.md` and `protected-runtime.json` mark protected runtime files that must not be edited without the authorize script — don't touch the frontend unless asked.

## Architecture of `app/`

Organised **by feature**, so one feature reads top to bottom in one file. The user found the previous strict layering (api/services/repositories/db/core/container, ~35 files) too hard to follow; don't reintroduce per-layer packages.

- `main.py` — `create_app()`: lifespan builds everything (DB → `Collector` + `MySqlLandStore` → feature objects) and stores it on `app.state`; registers the `guard` middleware and the routers. Run with `uvicorn app.main:create_app --factory` (no module-level `app`).
- `settings.py` — `Settings.from_env()`. `web.py` — shared HTTP rules. `db.py` — ORM tables, `connect()`, `db_errors()`.
- `features/<name>.py` — each file: routes at the top (`router = APIRouter()`), then the rules/DB code (`SnapshotService`, `PortfolioService`, `PublicData`, `ModelHolder`). Routes reach their object via `request.app.state.<name>`. A new feature = a new file here + one line in `main.py`.
- `app/__init__.py` puts `backend/` on `sys.path` because the engine modules use flat imports (`from pf_engine import ...`). Don't add a top-level module that collides with `pf_*`.
- Errors: the `guard` middleware in `main.py` catches every exception and returns `web.error_response(exc)` → `{"error":{"code","message"}}` (`ValueError/KeyError/TypeError` → 400, `ApiError` keeps its status, other → 500 with a generic message, nothing logged). FastAPI's own 404/405/validation errors are mapped by registered exception handlers. Handlers return `ok(data)` (`SafeJSONResponse`), not dicts, to avoid re-serialising up-to-64MB documents; every response body is refused if it contains a configured API key or the DB password.
- Request bodies are parsed by the `json_body` dependency (JSON content type, 64MB cap, NaN rejected). `check_host` allows only `ALLOWED_HOSTS` (default `127.0.0.1:PORT`, `localhost:PORT`).
- Access logging is disabled on purpose (URLs carry addresses and upstream keys).

### Storage

The app does **not** run its own MySQL: it connects to a MySQL 8.4 container the user already runs on their PC (it also holds their own land-trade data). In Docker the api joins the external network `v6_mysql` (`MYSQL_NETWORK`) and reaches the container by name (`MYSQL_CONTAINER`, default `land-mysql`) on port 3306; the user connects it once with `docker network connect v6_mysql land-mysql`. Directly (`python -m app`), via `MYSQL_HOST`/`MYSQL_PORT`. `db.connect` only creates missing app tables, never alters/drops existing ones, and refuses to start if a same-named table lacks expected columns. Never add code that drops, truncates or migrates tables it did not create.

App tables (`app/db.py`) hold documents as LONGTEXT JSON strings (preserves key order/numbers): `analysis_snapshots`, `portfolio_samples`, `app_settings`, and the land-trade cache (`land_complete/pages/errors`). Table/column names must stay stable (existing data). `MySqlLandStore` subclasses `pf_land_store.LandStore` (SQLite) and keeps its interface/cache policy so `pf_api.Collector` is unchanged. Bundled read-only samples come from `data/samples/` (`default.json` names the default). `V6.html` is no longer written to disk; `features/pages.py` renders it per request.

### Services worth knowing

- `SnapshotService.recompute` never trusts client-computed results: it re-runs `validate_snapshot` + `export_snapshot`, and rejects any payload containing a configured secret.
- `PortfolioService` samples are frozen captures (`persistencePolicy=portfolio_frozen_v1`); reading one must not recompute it with the current engine. The default sample is an explicit pointer and is never silently replaced.
- `PublicData.slot()` allows at most 4 concurrent upstream lookups through `pf_api.Collector` (429 `BUSY` otherwise).

### Trained model (not built yet)

`features/model.py` defines the `Predictor` protocol and `ModelHolder`, which loads `MODEL_ENTRYPOINT=module:Class` from `MODEL_DIR` (`./data/models`, mounted read-only). With no entrypoint the app starts normally, `/api/model/status` reports `not_configured`, and `/api/model/predict` returns 503 `MODEL_NOT_READY`. Model failures at load never block startup. Details in `data/models/README.md`. The analysis engine does not depend on the model.

## `backend/` (domain layer)

Flat modules prefixed `pf_`: `pf_engine` (analysis/cashflow/validation; `analyze`, `validate_snapshot`), `pf_api` (`Collector`: all upstream HTTP, caches, comparables; `ApiError`), `pf_survey` (site survey, parcel enrichment), `pf_land`/`pf_boundary`/`pf_regions` (land classification, parcel boundary allocation, region catalog), `pf_persistence` (export rules), `pf_config` (key/.env loading), `pf_land_store` (SQLite land cache; base class of `MySqlLandStore`). Standard library plus shapely/pyproj only — do not add dependencies here. Export policy: Geocoder-derived/real-time revenue data is stripped from saved snapshots and must be re-queried (`exportPolicy: v5-geocoder-requery`).

## Configuration

All config is environment variables (see `.env.example`); in Docker they come from `.env` via compose, with `python -m app` from `pf_config.load_environment`. That loader rejects unknown names, so any new app variable must be added to `pf_config.APP_NAMES` (one `.env` serves Docker and `python -m app`). `app/settings.py` reads them. VWorld keys must match `VWORLD_DOMAIN`.
