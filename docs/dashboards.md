# Dashboards (Phase 4)

Code: `backend/app/modules/dashboards/metrics.py` (all numbers), `export_pptx.py` (PowerPoint), `backend/app/api/dashboards.py`; UI `frontend/src/components/dash/`.
Layouts follow the Tegra status deck: slide 3 (overall), slides 4-8 (product coverage), slide 9 (next week), plus the delay dashboard from your brief.

## One engine, named formulas, shown on every dashboard
| Name | Definition |
|---|---|
| Completion | `(Done + ½ In Progress) ÷ (plan tasks + tracker events)` — the status slides' own formula, kept as a named legacy calculation (decision 2). Numerator, denominator and formula text are in the payload and the footer. |
| Closed item | status done/cancelled, or an actual finish/date exists |
| Phase state | **Done** all items closed · **Overdue** any open item is past its date (+grace) or has not started although its start passed · **In progress** some work started · **Planned** nothing started |
| Gate state | **Done** actual date · **Overdue** planned (+grace) passed · **Due** within 14 days · **Planned** |
| Gates | tracker events whose name contains Sign-off / Approval / Acceptance, plus Go-Live (a rule, printed in the footer; make it configurable if it needs to change) |
| Delayed item | the same delay rule as the plan (docs/planning.md) applied to plan tasks, tracker events, pending items, gap specifications and sign-off gates |

Rules: no number is typed in; a dashboard with nothing to measure says so instead of showing 0% or 0 delays; a data source that is not imported (development delivery) is shown greyed as "later phase", never as zero; changing the report date recalculates everything; grace days come from the project setting.

## The four dashboards
- **Overall status** — KPI strip (overall, completed, in progress, overdue phases, upcoming), quarter/month timeline with area and phase rows, bar fill = % done, ★ key sign-offs, status column, Today line, legend and source/formula footer. Click a KPI to filter the rows it counts; click a row to see the source tasks behind the bar and open any task to update it.
- **Product coverage** — KPI strip (overall %, done/total items, overdue/start-delayed items with drill-down, next gate, go-live), timeline left, **Sign-Off Gate Tracker** right (date, "(plan dd-Mon)" when actual differs, status chip), blueprint approvals by department, **Needs attention** (rule-generated: overdue gates, late tasks, pending with Customer/WFX, revisions awaiting approval, specifications past target, overdue tasks that block others — each links to its records).
- **Week plan** — This week / Next week / Next month (Monday-Sunday). Numbered cards grouped by product, Project-wide, Gap specifications, Customer inputs and WFX commitments; "Starts", "Due" and labelled overdue carry-overs (capped at 5 per group); gap specifications aggregated per team with owner counts.
- **Delays** — delayed items by source, ageing buckets, by product, Customer vs WFX, owners, most delayed first, and slippage against the original date (revised dates never hide a delay).

## Export
PowerPoint (`GET /projects/{id}/dashboard-exports/{overall|product|next-week|delays}`) is built from the same payload with native, editable shapes; permission `dashboards:export` (admin, PMO, project manager, management); every export is audited. Print / save as PDF uses the browser's print layout (landscape, navigation hidden). I rendered all four exports with PowerPoint to check them.

## Checked against your data (as of 17-Nov-2026)
Overall completion **39%**, **5 completed phases**, **3 overdue phases** — the same headline as slide 3. In progress (7) and upcoming (7) differ from the slide (12, 20) because the slide's ~40 rows are hand-curated while these rows come from the imported plan phases and tracker events. ERP page: BBP Sign-Off **overdue since 21-May-26**, PLM: **done 14-Aug-26 (plan 21-May)**, both as on slides 4-5. Week plan cards match slide 9 (gap-scope submission starting 23-Nov, PLAN BBP sign-off 27-Nov, MES blueprint submission 24-Nov). Automated tests recompute every figure independently from the raw workbooks (69 tests in total pass).

## Not built yet (be aware)
- **Configurable / saved dashboards** (add, remove, reorder widgets, publish) and the `generated_dashboards` / `dashboard_widgets` tables. The four layouts are fixed templates; the importer already tells you which templates the data supports.
- **Server-side PDF.** PDF is browser print; there is no server-rendered PDF file.
- **Area = one product.** A phase is tagged with a single product (or Project-wide); the slides' combined areas such as "PLM / ERP / PLAN" cannot be expressed yet.
- **Department × site coverage matrix** (slides 7-8) is not shown: the blueprint sheet has no site column. It will appear only when the source has that dimension.
- **Development delivery delays** wait for the delivery tracker import (Phase 5).
- **Scheduled / emailed reports** and the AI-assisted dashboard configuration (Phase 8).
- The slide's curated phase list (e.g. "Fit & Gap – Prototype Solution Review" built from several sources) is not reproduced; a mapping layer would be needed.
- The PowerPoint export was visually checked on this data only; a plan with hundreds of phases paginates 30 rows per slide.

## KPI drill-down (interactive dashboard, Stage 2)
On the Overall status dashboard, a second strip shows **Total phases, Completed, In-progress, Overdue and Upcoming activities, Upcoming milestones**. Each tile opens the records behind it (`GET /projects/{id}/dashboards/drilldown/{metric}`): server-side search, owner filter, sort and paging (25 per page), showing owner, original date, revised date, current date, delay in days and status. Clicking a plan task opens its editor; edits (owner, status, date revisions) refresh the tile and the list.
- **One rule per tile** (`metrics.ACTIVITY_METRICS`): the tile number and the list come from the same predicate, so they cannot disagree (a test checks this against the raw Tegra files). Completed = closed; in progress = started and not closed; overdue = not closed and current finish + grace passed; upcoming activities = not closed, not in progress, not overdue; upcoming milestones = open milestones/sign-offs dated on or after the report date.
- Scope is plan tasks plus tracker events. Pending, delivery and gap items stay on the Delay dashboard.
- Tracker milestones come from the import and have no editor yet, so they open read-only (marked "tracker"); plan tasks are editable.
- Archived and trashed tasks are excluded from tiles and lists.
