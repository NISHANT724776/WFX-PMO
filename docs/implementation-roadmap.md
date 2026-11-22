# Implementation Roadmap and Backlog

Legend: DONE = runs and is tested. Everything else is not started.

## Phase 0 - Discovery: DONE
workflow-and-structure-plan.md (decisions log), source-mapping.md, database-erd.md, data-dictionary.md, architecture.md, this file.

## Phase 1 - Foundation: DONE (see status report in README.md for test evidence)
Login/JWT, 8 roles + permission matrix, user admin, master data (customers, products, locations, departments, resources, status config), projects with products/sites, flex-field definitions (5+5+5), audit log, Alembic migration, frontend shell. 21 backend tests pass; frontend builds, lints, and was exercised in a browser.
Gaps: Docker stack not run; no Postgres run; flex-field *values* API pending; no project-access UI (API exists); no rate limiting on login.

## Phase 2 - Excel Intelligence + Tegra import: DONE for steps 1-13 of the 18-step scenario
Built and tested on the real workbooks (see docs/excel-intelligence.md): safe upload, profiling, header/group/section detection, sheet classification, semantic mapping with confidence, matrix unpivot, validation + error report, preview, create/update commit with provenance, rollback, duplicate-file guard, reusable templates, relationship detection, dashboard-field suggestions, full UI. 41 backend tests pass (20 new); verified in the browser: upload by drag-and-drop, mapping review, product linking, validation, and import of both Tegra files into the Tegra project (185 tasks, 135 events, 17 gates, 252 gap rows).
Not done from the original Phase 2 list: Celery/Redis worker (background task used instead; no Redis here), pandas (not needed), import targets for UAT/integration/reports (Phases 5-6), dashboard generation itself (Phase 4, needs the metric engine), steps 14-18 of the scenario (need Phase 3 plan UI + Phase 4 dashboard).

## Phase 3 - Planning: DONE (see docs/planning.md)
Edit tasks/milestones, date revisions with full history and approval, dependencies with loop checks and suggestions, phase-to-product tagging, flex-field values, delay rule with per-project grace days, pending register (customer / WFX / external / internal) incl. import of the Shahi Pending Items sheet, project workspace with Table / Gantt / Calendar, Pending and Trackers tabs. 56 backend tests pass (15 new); verified in the browser on the real Tegra and Shahi data.
Not done: assigned-to-me editing for non-PM roles, schedule-conflict flags from dependencies, revisions for tracker events/gap specs, sub-task tree view, other Shahi sheets (Phase 5).

## Phase 4 - Dashboard engine: DONE for the four fixed templates (see docs/dashboards.md)
Metric engine with named formulas; Overall status, Product coverage (Sign-Off Gate Tracker, needs attention), Week plan (this / next week / next month) and Delay dashboard; drill-down from KPIs and bars to source records and task editing with live refresh; PowerPoint export (rendered and checked in PowerPoint) and print-to-PDF. 69 backend tests pass; headline numbers match the status slide (39%, 5 completed, 3 overdue phases). Steps 14-18 of the first slice work end to end.
Not done: configurable/saved dashboards and the widget tables, server-side PDF, multi-product areas, department x site matrix, development-delivery delays (Phase 5).

## Phase 5 - Delivery and requirements: DONE (see docs/delivery.md)
Delivery tickets from two sheets merged by field authority (decision 3) with recorded disagreements, BRD requirements, helpdesk and operations points, gap specifications (editable, revisable), open discussions, out-of-scope decisions with approval rules; many-to-many links with evidence-based suggestions; delivery lifecycle and delay rules feeding the Delay, Week and Needs-attention views; a Status values panel so ambiguous wording is classified by the user, not guessed; date revisions extended to delivery items, gap specs and BRD requirements. Verified on the real Shahi workbook (381 tickets, 143 requirements, 236 link suggestions) and in the browser.
Not done: automatic delivery-to-BRD links (no shared key in the files), product tagging for tickets, stage actuals, Summary Schedule defaults, 'assigned to me' editing.

## Phase 6 - QA/UAT, reports/prints, integrations: DONE (see docs/trackers.md)
## Phase 7 - WBS and analytics (Dashboard D)
## Phase 8 - MCP/AI (only after authorization is proven)
## Phase 9 - Hardening
Postgres test run, security testing, httpOnly-cookie auth, login rate limiting, backups/recovery runbook, production compose, UAT.

## Open items
Delay rule (grace days) - user to decide; defaults to 0. Hosting target. Whether SSO is available.
