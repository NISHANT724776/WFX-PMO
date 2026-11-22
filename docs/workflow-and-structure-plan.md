# WFX PMO Platform — Workflow & Structure Plan (Pre-Phase 0)

Status: DRAFT for review. Nothing is built yet. Date: 2026-11-21.
Basis: the 4 Excel trackers + project plan, the Tegra status PPT (10 slides), the architecture PDF (25 pp.) and the master prompt.

---

## 1. What I found in the source files (confirmed by inspection)

| Source | Structure | Consequence for the build |
|---|---|---|
| **Tegra Tracker (3)** (newer) | 8 sheets: Master Sheet (wide: events × PLM/ERP/Plan/WMS/MES/Finance, each with Planned/Actual date pair), Blue Printing Signoff, Gap Tracker (254×20), E2E, UAT Acceptance, Reports+Prints, Integration (23 cols), Lists | Master Sheet must be **unpivoted** (1 row → N product-event rows). Title row + 2-level headers → header detection is mandatory. |
| **Tegra Tracker (1)** (older) | Sheet1 (2-row header, **no WMS**), "PI Point + AS-IS + Blueprint Mapping" (no Status col), Gap Tracker (276×12, different columns: Received On, Proto Created, Specs Created…), Integration (17 cols, no Company) | Same template family, different versions → must be detected as "Tegra Tracker v1 vs v3", not silently merged. Version diff report required. |
| **Tegra_Consolidated_ProjectPlan_V4** | 1 sheet, 205 rows: Phase header rows + task rows (Phase, Task, Responsible, Location, Start/End, Duration, Actual Start/End, Onsite/Remote, Status, Dependencies, Resource) | Phase rows are *group headers inside the data* → parser must treat them as parents, not tasks. Primary source for Gantt. |
| **Shahi Tracker** | 12 sheets: Dashboard, Open for Discussion, Summary Schedule, Delivery Schedule (386×22), Finance BRD, Pending Items (grouped by component), Operations BRD, New-Open Points-Ops, Out Of Scope, WBS Week Summary, Tech_Final (389×30), WBS Week Wise (714×18, Level 1/2/3 hierarchy) | Delivery Schedule and Tech_Final **overlap on ID** → one canonical `delivery_item` + reconciliation rule. WBS is hierarchical (Level/WBS Code). |
| **Tegra PPT** | Slide 3 = overall status (280 shapes, 5 KPIs, Q/M timeline, phase rows); Slides 4–8 = PLM/ERP, PLAN, WMS, MES, Finance product pages; Slide 9 = Next Week Plan (4 groups, numbered cards); Slide 10 = closing | 3 dashboard templates to reproduce: **Overall Status**, **Product Coverage & Status** (right panel varies: Sign-Off Gates vs Dept×Site matrix), **Next Week Plan**. |

### Anomalies I noticed (go on the open-questions list, not silently "fixed")
1. PPT slide 1 says "As on 19th Feb 2026" in one text and "17th Nov 2026" in another — stale text.
2. Shahi `WBS Week Summary` shows **WK47-2025** with 2025 dates while the dashboard is "As of 2026-11-17" — year likely wrong in source or a legacy week.
3. Shahi `Delivery Schedule` rows are ragged (e.g. Priority blank → values shift left in some rows) — validates why every import needs a row-level error report.
4. Tegra Gap Tracker repeats `Issue ID` across rows (e.g. 409562 ×2) → Issue ID cannot be a unique key.
5. PPT completion formula "(Done + ½ In-Progress) ÷ events" is a **legacy calculation** — keep as a named formula, don't mix with a new one.

---

## 2. End-to-end workflow

### 2.1 Business workflow (requirement → release → report)
```
Customer requirement / Helpdesk ID / BRD serial
        │  (external refs kept as separate fields)
        ▼
 BRD Requirement ──► Gap / Specification ──► Delivery Item ──► QA release ──► UAT ──► Production
        │                │ (N specs per Issue ID)   │ (N items per helpdesk)   │          │
        │                ▼                          ▼                          ▼          ▼
        │         Sign-off gate / approval     Dependencies (Customer / WFX / External)   Test scenarios, defects, acceptance
        ▼
 Project Plan (phase → milestone → task)  ◄──── Weekly/Daily WBS work packages (reference, never duplicate)
        │
        ▼
 Dashboards (Overall, Product Coverage, Next Week, WBS) — all computed from the same tables
```

### 2.2 Excel Intelligence pipeline (the core differentiator)
```
1 Upload ─► 2 Profile ─► 3 Classify sheets ─► 4 Header & structure detection
   │ (hash, size,    (all sheets, types,    (plan / matrix / gap /      (title rows, 2-row headers,
   │  dup-import      formulas, dates,       delivery / UAT / WBS…)      group-header rows, product
   │  check)          uniques)                                           date-pairs)
   ▼
5 Match saved template? ─yes─► pre-fill mapping (re-validate)
   │no
   ▼
6 Column mapping suggestions (header synonyms + value patterns + sheet context + history) → confidence High/Med/Low
7 Relationship detection (Issue ID / Helpdesk ID / BRD / WBS refs) → user resolves uncertain ones
8 Validation (dates, dup IDs, mandatory, status vocab, FK, types, formula errors) → error report (downloadable)
9 Preview (create / update / skip, rejected rows) ─► user approval
10 Commit in ONE transaction from staging → canonical tables + provenance (file, sheet, row, hash, mapping version)
11 Save mapping as reusable template
12 Dashboard recommender → deterministic metric engine → preview → configure → publish
```
Rules baked in: low-confidence is never auto-approved; invalid rows are never deleted (kept as rejected with reason); AI only *suggests* layout/mapping — **all numbers come from deterministic SQL/Python**; a widget is hidden when its source fields are missing.

### 2.3 Vertical-slice acceptance scenario (milestone 1, your 18 steps)
Login → Excel Intelligence → upload Tegra Tracker → sheets/headers detected → mappings + confidence → flags → manual fix → preview → import → Tegra project created/linked → Product Coverage dashboard → click milestone → see source tasks → edit a task → dashboard recalculates from DB.
*Dependency:* step 14–16 need the **Project Plan V4 import** too (tracker alone has gates/events but not the phase/task hierarchy), so the slice imports **both** Tegra files. I'll state this in Phase 2.

### 2.4 User/role workflow
Admin creates Customer → Project → Products → Sites → PMO/PM imports plan & trackers → Functional owns BRD/gaps → Dev owns delivery dates → QA owns scenarios/defects → everyone updates weekly WBS → Management reads dashboards. Permissions enforced in backend (module + project + record level) and every write goes to `audit_log`.

---

## 3. Structure plan

### 3.1 Repository layout (modular monolith)
```
D:\Project Management Tool\
├─ docs\                       architecture.md, data-dictionary.md, source-mapping.md,
│                              database-erd.md, implementation-roadmap.md, open-questions.md
├─ reference\                  (copies/links of source Excel, PPT, PDF — read-only, untracked by app)
├─ backend\                    Python 3.12 / FastAPI
│  ├─ app\
│  │  ├─ main.py, config.py, deps.py
│  │  ├─ core\                 security (JWT, RBAC, record-level), audit, storage abstraction, pagination
│  │  ├─ db\                   base, session, models registry
│  │  ├─ modules\
│  │  │  ├─ admin\             users, roles, master data, custom fields, status dictionaries
│  │  │  ├─ projects\          customers, projects, products, sites, phases, milestones, work_items, gates
│  │  │  ├─ delivery\          BRD, gaps, delivery_items, helpdesk, reports, integrations
│  │  │  ├─ governance\        dependencies, discussions, scope decisions, approvals
│  │  │  ├─ testing\           scenarios, cases, executions, defects, UAT
│  │  │  ├─ wbs\               weeks, nodes, assignments, history
│  │  │  ├─ excel_intel\       profiler, header_detect, classifier, mapper, relations, validator,
│  │  │  │                     staging, committer, templates, rollback, tasks (Celery)
│  │  │  └─ dashboards\        metric_engine (deterministic), templates, recommender, export (PDF/PPT)
│  │  └─ mcp\                  (Phase 8 only, after authz is stable)
│  ├─ alembic\                 migrations
│  └─ tests\                   unit, api, import (golden files from the real workbooks)
├─ frontend\                   Next.js + TS + Tailwind
│  └─ src\
│     ├─ app\                  routes: /login, /projects/[id]/{overview,plan,products,deliveries,brd,
│     │                         dependencies,qa,wbs}, /excel-intelligence/{upload,[batch]/{profile,mapping,
│     │                         relations,validation,preview}}, /dashboards/{overall,product,next-week,wbs}, /admin
│     ├─ components\           ui\, gantt\, timeline\, kpi-strip\, gate-tracker\, coverage-matrix\,
│     │                         needs-attention\, mapping-editor\, data-table\ (server-side paging/filter)
│     ├─ lib\                  api client (typed from OpenAPI), auth, formatting
│     └─ tests\
├─ docker-compose.yml          postgres, redis, backend, worker, frontend
├─ docker-compose.prod.yml
├─ .env.example
└─ README.md
```

### 3.2 Database groups (full ERD comes in `database-erd.md`)
Master · Project plan · Requirements & delivery · Testing · Governance · WBS · Excel intelligence (file → sheet → column → mapping → staging_row → import_issue → commit_record) · Dashboard (template/widget/metric_definition) · Platform (custom fields, status dictionary, audit, notifications).
Key rules: UUID PKs; external IDs (Issue ID, Helpdesk ID, BRD serial) in their own columns and **never unique alone**; `date_revision` append-only (baseline immutable); raw status kept next to normalized status; JSONB only for source snapshots/config.

### 3.3 API shape
`/api/v1/auth`, `/admin/*`, `/projects/*`, `/delivery/*`, `/governance/*`, `/testing/*`, `/wbs/*`, `/imports/*` (upload, profile, mapping, validate, preview, commit, rollback, templates), `/dashboards/*` (data endpoints return computed metrics + the formula used + source record IDs for drill-down).

---

## 4. Delivery plan

| Step | What | "Done" means (must run, not just exist) |
|---|---|---|
| **0 – Docs** | The 5 docs + `open-questions.md`, source-to-module mapping incl. Tegra v1↔v3 diff | You review & approve mappings/status maps |
| **1 – Foundation** | Docker Compose, Postgres, FastAPI, Next.js, JWT login, roles, Customer/Project/Product/Site master, audit log, nav shell | `docker compose up`, login works, RBAC test passes |
| **2 – Excel Intelligence + Tegra slice** | Everything in §2.2 steps 1–11, templates, history, rollback; Tegra tracker + Plan V4 importers; golden-file tests on the real workbooks | Your 18-step scenario passes end-to-end |
| **3 – Planning** | Plan, milestones, tasks, deps, Gantt, calendar | Plan V4 round-trips |
| **4 – Dashboard engine** | Overall / Product Coverage / Next Week, PDF + PPT export | Visual comparison against PPT slides 3, 4–8, 9; numbers reconcile with SQL |
| **5–9** | Delivery/BRD, QA/UAT, WBS, MCP/AI, hardening | As per your roadmap |

Order note: I put Phase 1 + 2 + the minimum of 3/4 needed for the slice first; full Gantt/calendar polish and export come after the slice works.

---

## 5. Decisions I'll make unless you object (technical, non-blocking)
- Python 3.12 + `uv`/venv, Pydantic v2, SQLAlchemy 2.x, Alembic; **Celery + Redis**; local-disk storage behind an interface (S3/Azure-compatible later).
- Mapping engine v1 = deterministic (synonym dictionary + fuzzy header match + value-pattern scoring + template history). An LLM is an optional pluggable *suggester* later; it is not required for the slice and never computes numbers.
- Auth v1 = email/password + JWT (argon2); OIDC/SSO hook left for WFX IT.
- Charts/Gantt/timeline: custom SVG/CSS components (the PPT layout is too specific for stock chart widgets); Recharts for the secondary charts (status breakdown, workload).
- PPT export via `python-pptx` built from the same metric payload; PDF via headless-browser print of the dashboard route.
- Tegra Tracker v3 is treated as the current template; v1 is a historical snapshot.

## 6. Open business questions (need your answer; none block Step 0/1)
1. **Customer vs product naming:** is "Tegra" the customer and Decotex / Fjord-TVC / Arena the sites/entities? (PPT subtitles say "Decotex (El Salvador) & Arena".)
2. **Completion formula:** keep the PPT's (Done + ½ In-Progress) ÷ Events, or adopt a weighted model? I'll implement the legacy one as a named formula first.
3. **Shahi Delivery Schedule vs Tech_Final:** which wins on conflicts (dates/status/owners)? Proposed: Tech_Final for ownership/QA fields, Delivery Schedule for customer-facing dates.
4. **Tegra Tracker v1 vs v3:** v3 is newer — confirm v1 is only history, and whether date differences should be loaded as revisions.
5. **Reports + Prints** is only folder/count in Tegra — OK to import as inventory counts now and enrich per-report later?
6. **WBS Week Summary 2025 weeks:** source error or real legacy data?
7. **Users/SSO:** WFX SSO (OIDC) available, or start with local accounts?
8. **Hosting target** (Azure / on-prem) — affects storage and Docker prod config only.

## 7. Risks
- Wide Master Sheet and ragged Shahi rows are the hardest parsing cases → built first and tested against the real files.
- The PPT is the visual spec but it is a *rendered slide* (hundreds of shapes); I'll rebuild layout from structure/terminology, not pixel-copy, and compare screenshots side-by-side.
- Scope is very large; the slice is deliberately narrow so something real runs early.

---

## 8. Traceability to the 8-point business brief (added 2026-11-21)

These 8 points are the **confirmed business requirements**; the rest of this document is my technical design. Coverage check:

| # | Brief | Where it lives | Status vs. plan |
|---|---|---|---|
| 1.1 | Plan by customer + product; all products or one product | `projects` module: `project_product`, plan view with product filter ("All" = consolidated) | Covered |
| 1.2 | Milestone, task, responsibility, planned / revised / actual dates | `milestone`, `work_item`, `owner_assignment`, append-only `date_revision` (baseline stays; each revision keeps reason + approver) | Covered |
| 1.3 | Location in plan | `project_site` FK on every work_item (source column "Location", e.g. Arena (Honduras)) | Covered |
| 1.4 | Type Onsite / Online | `work_item.delivery_mode` enum. Source files say "Remote"; I map Remote → Online and keep the raw value. | Covered (naming assumption) |
| 1.5 | Flex fields: DDL, Date, Text | `custom_field_definition` with exactly 3 types: dropdown (admin-defined options), date, text; per entity, per project. Usable on **all** trackers, not only the plan. | Covered, will make this explicit in the admin UI |
| 2 | Same customer tracker like Tegra + Shahi Dev plan, all those columns | Tegra Master Sheet → gate events per product; Shahi Delivery Schedule / Tech_Final → `delivery_item`. Per-customer tracker = a saved column/stage configuration over the same tables, not a new table per customer. | Covered. **Confirmed by user (2026-11-21):** a customer can have both a milestone tracker (Tegra style) and a dev plan (Shahi style). |
| 3 | Pending with Customer | `dependency_item` filtered `pending_with = Customer` | Covered |
| 4 | Pending with WFX | same register, `pending_with = WFX` | Covered |
| 5 | UAT scenarios + status | `uat_scenario`, `test_execution` (Pass/Fail/Blocked/Not run) | Covered |
| 6 | Reports + Prints + Integrations tracker | `report_print`, `integration_record` | Covered (Tegra Reports sheet is only folder + count, so per-report rows start empty/manual) |
| 7 | **Delay dashboard** across plan + all trackers + pending activities + dev delays | **Gap in my earlier plan.** I had Overall / Product / Next-Week / WBS only. Adds **Dashboard F: Delay Dashboard**. | **Added** |
| 8 | Tasks due this week / next week | Dashboard C "Next Week Plan", extended with a This Week / Next Week toggle and all sources | Extended |

### 8.1 Dashboard F: Delay Dashboard (new)
One deterministic **delay engine** feeding it, so the numbers are defined once:

| Source | A record is delayed when |
|---|---|
| Project plan task / milestone | not complete and latest approved finish < report date (or start passed, not started = "start delayed") |
| Tracker event / sign-off gate (Tegra-style) | planned date < report date and no actual date / not approved |
| Pending with Customer / WFX | not closed and target (or latest revised) < report date |
| Dev delivery item (Shahi-style) | a stage date (dev completion, QA release, UAT release, production) < report date and stage not done |

Display: delay count by source, by product, by owner, by responsibility (Customer vs WFX), ageing buckets (1-7, 8-14, 15-30, 30+ days), and **slippage vs. original baseline** (so revising a date never hides a delay). Each row drills to the source record. Source-of-truth fields missing for a source = that source is greyed out, not shown as zero.

### 8.2 Dashboard C extension: Due This Week / Next Week
Union of: plan tasks, tracker events, pending items (customer and WFX) and dev stage dates falling in the Monday-Sunday range, grouped by product/workstream, with owner, due date and responsibility, plus carried-over overdue items labelled. Cards open the source record.

### 8.3 Changes to the build order
- Delay engine + Delay Dashboard and Due This Week/Next Week move into **Step 4 (dashboards)** and are part of the accepted milestone alongside the Tegra Product dashboard.
- Pending-with-Customer/WFX and the flex-field admin are pulled forward (they are needed for the delay engine); BRD/Helpdesk/Out-of-scope stay later.
- Excel Intelligence stays in Step 2 as the master prompt requires; the 8 points above are manually usable even without an import.

### 8.4 New open questions from the brief
9. "Revised Dates": is one revised date enough, or do you need the full revision history shown (I will store full history, show latest by default)?
10. Delay threshold: is a record delayed from the day after the date, or is there a grace period per customer?
11. Should dev delays (Shahi) count toward the Tegra-style overall completion %, or stay a separate stream?
12. Flex fields: how many per entity, and are dropdown options per customer or global?

---

## 9. Decisions log (answered by user, 2026-11-21)

| # | Decision |
|---|---|
| 1 | Tegra = customer; sites/entities = Decotex, Fjord/TVC, Arena; products = PLM, ERP, PLAN, WMS, MES, Finance. |
| 2 | Completion % = PPT legacy formula (Done + 1/2 In-Progress) / events, stored as a named calculation. |
| 3 | Shahi conflicts: Tech_Final wins for owner/QA fields, Delivery Schedule wins for customer-facing dates. |
| 4 | Tegra Tracker (3) = current; (1) = history snapshot; differences reported, not loaded as revisions. |
| 5 | Reports + Prints imported as folder/count inventory; individual reports entered later. |
| 6 | Shahi WBS Week Summary imported as-is; 2025-week anomaly flagged in validation report. |
| 7 | Full date-revision history must be visible on screen (latest shown by default, full history one click away). |
| 8 | **Delay rule: TBD by user.** Build it as a configurable setting (grace days per customer/project, default 0) so no rework is needed when decided. |
| 9 | Dev delays (Shahi) stay separate from overall completion %. |
| 10 | Flex fields: 5 dropdown + 5 date + 5 text per entity; dropdown options per customer. |
| 11 | Local accounts (argon2 + JWT) first; SSO hook left for later. |
| 12 | Hosting undecided; storage behind an interface, Docker prod config generic. |
