# Architecture

## Style
Modular monolith. One FastAPI service, one PostgreSQL database, one Next.js frontend. Background worker (Celery + Redis) joins in Phase 2 for large Excel imports. No microservices until a boundary demands one.

```
Browser (Next.js, TypeScript, Tailwind)
   |  REST /api/v1  (JWT bearer)
FastAPI  --  core (security, RBAC, audit, pagination)
   |-- modules: admin | projects | delivery | governance | testing | wbs | excel_intel | dashboards | (mcp, Phase 8)
   |-- SQLAlchemy 2 + Alembic --> PostgreSQL
   |-- Celery worker + Redis (Phase 2) --> file storage abstraction (local disk dev, S3/Azure later)
```

## Rules (enforced in code, not just convention)
1. **Backend is the security boundary.** Every route declares `require("module:action")`; the frontend only hides buttons as a UX hint. Record-level scoping is applied inside queries (`accessible_project_ids`), and out-of-scope records return 404 so their existence is not revealed.
2. **Audit in the same transaction.** `write_audit` adds to the caller's session, so a change and its audit row commit or roll back together. Secrets (`password_hash`) are redacted.
3. **One canonical record per business object.** Dashboards and trackers are views over the same tables.
4. **Deterministic numbers.** All KPIs come from backend queries with a named formula and source record IDs. AI may suggest mappings/layout only (Phase 2+).
5. **Baselines are immutable; revisions are appended** (Phase 3).
6. **Provenance on every import** (file hash, sheet, row, mapping version, user, time) (Phase 2).
7. **Config over code.** Statuses, products, locations, flex fields, delay grace days are data/settings.

## Auth
Email + password (argon2), JWT HS256, 60-minute lifetime. Login failures are indistinguishable for unknown user vs wrong password and cost the same hashing time. Every login/failed login is audited. Production refuses to start with a weak or default `SECRET_KEY`. SSO (OIDC) hook is left for later (decision 11).

## Frontend
Next.js App Router. Auth state in a context; token held in `sessionStorage` (cleared on tab close). Trade-off: readable by script if an XSS bug existed; moving to an httpOnly cookie is a Phase 9 hardening item. Master-data screens are config-driven (`lib/masterConfig.ts`) so a new master list is a config entry, not a new page.

## Environments
- **Dev/test here:** SQLite (file) so the stack runs without Docker; SQLAlchemy models use portable types. Tests and migrations are run on SQLite.
- **Target:** PostgreSQL 16 via `docker-compose.yml`. **Written but not yet run** (no Docker on the authoring machine). First action on a Docker machine: `docker compose up --build`, then run the same pytest suite against Postgres.
- Config via environment (`.env.example`); no credentials in the repo.

## Dashboard architecture (Phases 2-4)
A deterministic *metric engine* returns `{value, formula, numerator, denominator, source_ids}`. Dashboard templates (Overall, Product Coverage, Next Week, Delay, WBS) are React components fed by those payloads; a widget whose required source fields are missing renders as "no data", not zero. PPT export uses python-pptx from the same payload; PDF via headless print of the route.
