# WFX PMO Platform

Project management and delivery governance platform. Design docs are in `docs/`; start with `docs/workflow-and-structure-plan.md`.

Status: **Phases 1-5 complete; the interactive dashboard (stages 1-7: manage mode, drill-down, Gantt, gates, coverage, builder, Quick Add, exports and the acceptance test) is done, see `docs/interactive-dashboard-plan.md`; UAT, reports + prints and integrations trackers and flex-field administration are done, see `docs/trackers.md`** (foundation, Excel Intelligence + Tegra import, planning, dashboards, delivery and requirements). QA, UAT and integrations (Phase 6) are next. See `docs/excel-intelligence.md`, `docs/planning.md`, `docs/dashboards.md` and `docs/delivery.md`.

## Run locally (no Docker needed)

Backend (Python 3.12+):
```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy ..\.env.example .env      # then edit: set SECRET_KEY, ADMIN_PASSWORD (min 10 chars), and DATABASE_URL
.venv\Scripts\alembic upgrade head
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```
For a quick local database use `DATABASE_URL=sqlite:///C:/absolute/path/dev.db` (use an absolute path). API docs: http://localhost:8000/docs

Frontend (Node 22):
```powershell
cd frontend
npm install
npm run dev
```
Open http://localhost:3000 and sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD` from your `.env`. No admin is created if `ADMIN_PASSWORD` is empty.

## Tests
```powershell
cd backend
.venv\Scripts\python -m pytest -q
```
Frontend: `npm run lint` and `npm run build` in `frontend/`.

## Using Excel Intelligence
Sign in, open **Smart Import**, drop a workbook, review the mapping on the **Mapping** tab (medium-confidence suggestions need a click; every product column group must be linked or excluded), run **Validation**, then **Import** into a project. Uploaded files are kept under `backend/uploads/` (git-ignored); tests use real Tegra workbooks in `backend/tests/data/` (customer files, keep this repo private).

## Docker (not yet run)
`docker-compose.yml` defines Postgres, Redis, backend and frontend. Copy `.env.example` to `.env`, fill it in, `docker compose up --build`. This has not been executed yet because Docker was unavailable where it was written; treat it as unverified until run.
