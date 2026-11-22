# Interactive dashboard and manage mode: gap analysis and plan

Checked against the repository on 2026-11-21 (83 tests pass; lint and build clean). Nothing below is built yet unless marked "exists".

## 1. What exists and is reused
| Requirement | Today |
|---|---|
| Database-derived KPIs, product coverage, gates, needs attention, next week, delays | Exists (`modules/dashboards/metrics.py`), computed per request from source tables |
| Plan CRUD, date revisions (baseline immutable, approve/reject), dependencies, audit | Exists (`api/plan.py`, work item drawer) |
| Gantt, calendar, pending, trackers, delivery lists with filters/paging/edit | Exists (read-oriented Gantt) |
| PowerPoint export, print-to-PDF | Exists (`export_pptx.py`, print CSS) |
| Roles, record-level access, audit log | Exists |

## 2. Gaps (verified by search)
| Area | Gap |
|---|---|
| Soft delete / archive / restore / duplicate / bulk update | None. Deletes are hard. No `deleted_at`/`archived` column anywhere |
| Comments and attachments | No tables, no upload API for records |
| Gantt | No drag, resize, or dependency drawing |
| KPI drill-down | KPIs do not link to filtered record lists |
| Approval states | Gate status is a fixed set; no approvers, comments, documents |
| Department x location coverage | Not built (noted in earlier docs) |
| Needs Attention actions | Derived only; no owner/priority/due/escalate/resolve/reopen records |
| Next Week | Read-only; no create, move between weeks, remove |
| Dashboard Builder | None: no widget registry, saved layouts, scopes (personal/project/management), default template |
| Quick Add | None |
| Side panels, inline edit, unsaved-changes warning | Drawer exists for some records only |
| Exports | PPTX and browser print only. No Excel; no server-side PDF; no export for gates, coverage, needs attention, week plan, overdue list |
| Tests | No end-to-end test of the 18-step acceptance scenario |

## 3. Stages (each ends with tests and a browser check on the Tegra data)
1. **Manage foundation.** Migration 0005: `deleted_at/archived_at/deleted_by` on plan and record tables; `comments`, `attachments` (local storage, size/type limits), `action_items` (Needs Attention), configurable `approval_states`. Generic archive/restore/duplicate/bulk-update endpoints with confirmation, permissions and audit. All lists and dashboards exclude archived rows.
2. **KPI drill-down and overdue list.** KPI cards navigate to server-filtered lists (overdue shows owner, baseline date, revised date, days late, status). Same calculation service everywhere.
3. **Interactive Gantt and plan editing.** Drag/resize with validation against dependencies, saved as date revisions (baseline preserved, reason prompted). Dependency create/remove with cycle check, predecessor/successor view, critical-milestone highlight, quick add of phases, milestones, tasks, subtasks.
4. **Gates, coverage, Needs Attention, Next Week actions.** Approvers, comments, documents, configurable states; department x location activity counts with calculated percentages; action items with escalate/resolve/reopen; week planner (Monday-Sunday) with create, move, remove, remarks.
5. **Dashboard Builder.** Widget registry (one definition per widget: id, data source, config schema, renderer); saved layouts at personal, project and management scope; duplicate, restore default; the Tegra layout is the locked default template; layout restored on next login.
6. **Quick Add and UX.** Global button with project/product context prefilled; side panels, inline edits, success/error toasts, leave-page warning.
7. **Exports and acceptance.** Excel (all listed views), server-side PDF, richer PPTX; automated test of the full 18-step scenario.

## 4. Decisions needed from you before Stage 1
- **PDF:** server-side PDF needs a rendering engine (a headless browser or a PDF library); on this machine I can add a Python PDF library (ReportLab-style tables, not pixel-identical to the screen). Browser print stays as the exact-look option. Which do you want?
- **Attachments storage:** local disk under the backend (works now) or object storage later?
- **Management dashboard:** which role may publish organisation-wide layouts?
- **Scale:** this is seven stages, roughly the size of Phases 2-5 combined. I recommend going stage by stage as before.

## 5. Stage 1 status: DONE (manage foundation)
Built and verified (92 backend tests pass; frontend lint and build clean; checked in the browser on the Shahi data):
- **Archive, soft delete (trash), restore, permanent delete (purge), duplicate, bulk update** for plan tasks, sign-off gates, pending items, delivery items, requirements, helpdesk items, gap specs, discussions, scope decisions and the new action items. One automatic filter (`app/db/lifecycle_filter.py`) hides archived and trashed rows from every list, count, facet, the plan, dependencies and every dashboard. Imports see all states so nothing is duplicated.
- Existing DELETE endpoints now mean "move to trash". Permanent deletion needs `projects:create` and an explicit `confirm`; bulk delete needs `confirm`; field updates in bulk are all-or-nothing; dates are not bulk-editable (they move only by revision).
- **Comments** (new permission `comments:write`, given to PMO, PM, consultants, developers, QA; customers read only) and **attachments** (allow-list of file types, 25 MB, stored under a generated name, always downloaded, never rendered).
- **Action items** (Needs Attention records): owner, priority, due date, latest action and who did it; escalate, resolve and reopen each need a reason and are audited.
- UI: selection and bulk bar, Active/Archived/Trash switch, confirmation dialogs, comments and files panel and archive/duplicate/delete in record, plan-task and pending drawers, an Archive tab per project.
- Migration `0005`. Tests: `backend/tests/test_stage1.py`.
Not yet in the UI: the Needs Attention panel on the dashboard that creates actions (Stage 4); archive/duplicate for sign-off gates (no gate editor yet, Stage 4).

## 6. Stage 4 status: DONE (gates, coverage, Needs Attention actions, week plan)
Migration `0007`; tests `backend/tests/test_stage4.py`; checked in the browser on a scratch project (removed afterwards).
- **Sign-off gates** (Dashboards → Sign-off gates; same records as the blueprint approvals): add and edit gates, approver, planned / submission / approval dates, comments, files. States are configurable under Status Configuration (entity `approval_gate`; defaults Not submitted, Submitted, Under review, Changes requested, Approved, Rejected) and each state's **category** decides what counts as approved. Rules (server side): approving needs `plan:approve`, a submission date and an approval date (never assumed), the approval date may not precede the submission date, a blocked state (rejected, changes requested) needs a reason in Comments, reopening an approved gate clears its approval date (the old value stays in the audit log). Overdue = not approved and planned date + grace passed; overdue gates feed the Delay dashboard and Needs Attention. Imported gates keep the old rule (sign-off date or "Approved" text) until someone edits them.
- **Department × location coverage** (Dashboards → Dept × location): activities (department, location, optional product, responsible person, planned and completed counts). Percentages are always calculated, completed ÷ planned, per cell, department, location and overall; a cell with nothing planned shows n/a. Completed may not exceed planned. Locations are compared side by side. Clicking a cell filters the activity list. The Tegra files hold no department-by-location data, so this starts empty and is filled by people.
- **Needs Attention → actions:** each item on the product dashboard has "Create action" (owner, priority, due date, what must happen). Once raised, the item shows the owner, status, due date, latest step and who took it; escalate, resolve and reopen are in the action's drawer. Escalated or overdue actions with no item of their own appear in the panel by themselves; resolved actions leave it.
- **Week plan:** "Add activity" (workstream, owner, product, module, target date, % complete, remarks), "Add to plan" on any derived card (which then shows "on the plan"), move to the previous / next week (the target date keeps its weekday), remove from the plan (archive, restorable), activities grouped by workstream, weeks run Monday to Sunday (a week must start on a Monday; a target date must fall inside its week). Unfinished planned work from earlier weeks is carried over. Export: PowerPoint (as before) and **Excel** (`format=xlsx`), both with the planned activities.
- Known limits: gate planned dates are audited but do not yet have the baseline-and-revision history that plan tasks have; "assign approvers" is a name, not a link to a user account; the week plan has no separate workflow for approving a move.

## 7. Stage 5 status: DONE (Dashboard Builder)
Migration `0008`; tests `backend/tests/test_stage5.py` (12); checked in the browser on the real Tegra project (the test layout was deleted afterwards). Dashboards → **My dashboards**.
- **Default template:** "Project status (default)" reproduces the status-report layout (KPI strip, phase timeline, status mix, sign-off gate tracker, needs attention, week plan, coverage). It is read-only and always available; "Customise" saves a copy, and "Restore default layout" puts its arrangement back into any layout. The four fixed dashboards are unchanged.
- **Widgets (11):** KPI strip, status breakdown (data source: plan activities, pending, delivery, gates or actions), delays (split by source, product, party, age or owner), phase timeline, sign-off gate tracker, needs attention, week plan, department/location coverage, product-wise completion, upcoming milestones, text. Each can show bars, a donut or a table where it is a chart, has its own heading, and can be limited to a product or location (or follow the dashboard-wide product/location filter). A widget's own choice wins over the dashboard filter. KPI numbers open the same records list as the fixed dashboard.
- **Editing:** add, remove, drag by the header, resize from the corner, or use the keyboard (arrow keys move, Shift + arrows resize) on a widget header. Widgets never overlap; the others settle around the one being moved. Settings forms are built from the registry.
- **Three levels:** personal (only you), project (everyone with access to the project; needs `projects:write` to create or edit) and management (everyone; needs the new `dashboards:manage` permission, given to Super Admin and PMO). A layout you may not see answers 404. Names are unique within a level. Duplicate / Save as copies a layout, including unsaved changes, into any level you are allowed to create.
- **Saved and restored:** the layout you last chose per project is remembered per user and reopens on the next visit; if it is deleted the default template is used. Saves name the version they started from, so a second editor is refused (409) instead of overwriting. The browser warns about unsaved changes when you change layout, switch dashboard or close the page.
- **Always live:** a layout stores only which widgets, where, and their settings. Every number is read from the database each time. Widget settings and layouts are validated on the server (unknown settings, bad values, overlaps, sizes, at most 40 widgets) even for direct API calls.
- **Extending:** a new widget is one entry in `backend/app/modules/dashboards/widgets.py` (title, settings, size, data function). If it returns one of the existing shapes (kpis, series, table, timeline, attention, gates, week, matrix, text) the screen draws it with no front-end change and the palette, settings form and validation come from the registry.
- Limits: leaving the project's Dashboards tab for another project tab does not prompt about unsaved changes (closing the page and switching dashboards do); a layout is the same for every project it is opened on (the data comes from the project being viewed); no widget-to-widget cross filtering.

## 8. Stage 6 status: DONE (Quick Add, inline editing, messages, unsaved-changes warnings)
Tests `backend/tests/test_stage6.py` (the exact requests the screens send); checked in the browser on a scratch project (removed afterwards).
- **Quick Add** (the "＋ Quick add" button on every screen for people who may edit, or Alt+Q): Task, Milestone, Project activity (an action with owner, priority, due date), Delivery item, Dependency (waiting on someone, or one task before another with a loop check), Discussion point, Weekly activity (this week unless a date is given) and Sign-off gate. It opens already set to the project you are in, shows the customer, and takes the product from the product dashboard or the Plan's product filter you are looking at (a product that does not belong to the chosen project is dropped). Required fields are checked, server errors appear in the form, "keep open to add another" is available, and the view you are on refreshes at once (or, if you have unsaved edits, asks you to refresh).
- **Inline editing:** in the Plan table the owner and status change in place and the finish date changes through a small dialog that asks for a reason (the original date is kept and the change goes into the date history). In the Delivery lists every simple text, date and choice column, and the status, change in place. Derived and calculated columns (current dates after revisions, percentages) are never inline. A failed save keeps the old value and says why.
- **Messages:** success and error toasts (errors stay until dismissed).
- **Unsaved changes:** drawers and forms warn before closing with edits, and a single guard warns when you follow a link, switch a project tab or dashboard, or close the browser tab while anything is unsaved (including a dashboard layout being edited).
- Limits: the quick date change is for plan tasks (other records change dates in their drawer); inline editing is not offered for fields that are lookups (product, department, location) or long text.

## 9. Stage 7 status: DONE (reports, exports, acceptance test)
Tests `backend/tests/test_stage7.py` (6) and `backend/tests/test_acceptance.py` (the 18 steps). Dashboards → **Reports & exports**.
- **Eight reports, each in Excel, PDF and PowerPoint** (`GET /projects/{id}/exports/{report}?format=xlsx|pdf|pptx&as_of=&product_id=&period=`; the list is at `/exports`): Overall project status, Product-wise status (needs a product), Project timeline, Sign-off gate tracker, Department and location coverage, Needs attention, Next week plan, Overdue activity list. Needs `projects:read` and `dashboards:export` (a role that can read but not export gets 403); every export is written to the audit log with report, format and report date.
- **One source of numbers:** each report is built once (`modules/dashboards/reports.py`) from the same calculation service as the dashboards, then only laid out. Tests compare the files with the dashboards: KPI values, phase rows and their %, overdue rows and days late, gate and approval counts, needs-attention text, week-plan counts, and coverage totals and ordering.
- **Excel:** a Summary sheet (headline numbers, how it was counted, report date) and one sheet per table, real date cells, filters, frozen header. **PDF:** A4 landscape, headline strip, a drawn timeline (bars with % fill and the report date) for the status reports, tables with repeating headers and page numbers. **PowerPoint:** the status slide layouts of Phase 4 for overall, product and week plan; table slides in the same style for the others (timeline adds the phase bars first). Long lists are cut at 150 rows in PowerPoint and the slide says the rest is in Excel.
- **Acceptance test:** all 18 steps of the brief run against the real Tegra workbooks as a project manager: sign in; open the project; see the status dashboard; click the overdue KPI and open the list; open an activity; change its owner and target date; check the database (original date kept, revision approved with the reason), the audit trail (who, before and after) and the dashboard (one fewer overdue); add a milestone; see it in the Gantt data; update its status; check completion and product numbers recalculate; export PDF and PowerPoint and find the updated figures and the new milestone; customise and save a layout; sign in again and find it restored.
- Limits: PDF text uses the built-in fonts (no Devanagari or other non-Latin scripts; an en dash prints as a hyphen); the Excel and PDF files are snapshots, not live; PowerPoint is generated, not edited from the original Tegra PPT file (the structure and legend are reproduced).

## 10. Final review of the interactive dashboard
Method: every endpoint was called without a token (146 operations: all answer 401 except `/health` and login); the new routers were read for permission and project-access checks; uploads, downloads and the three export formats were read for injection risks. Two problems were found and fixed, each with a test:
1. **Customers could read internal comments and files.** The customer role has `projects:read`, which let it list comments, list attachments and download files attached to records. New permission `comments:read` (every internal role has it, the customer role does not) now guards all three, and the drawer hides the section for customers. (`test_customers_cannot_read_internal_comments_or_attachments`)
2. **Typed text could run as an Excel formula.** A task title or remark beginning with `=` would have been written to a cell as a formula (spreadsheet injection). Text cells are now always stored as text, in all Excel exports. (`test_text_typed_by_people_never_becomes_a_spreadsheet_formula`)

Open items that need a decision or later work (not bugs in what was built):
- **The customer role still sees every project record** (plan, pending items "with WFX", delivery, actions, dashboards, gates). Only editing, comments, files and exports are withheld. If customers should see a narrower view (for example only "pending with customer" and sign-offs), that needs a defined visibility rule; it was not specified.
- **Sign-in hardening is Phase 9:** the token is kept in session storage (not an httpOnly cookie) and there is no login rate limit.
- **Tracker milestones from the import have no editor**, and gate planned dates have audit history but not the baseline-and-revision history plan tasks have.
- **PostgreSQL and Docker have never been run here** (development and all tests use SQLite); the migrations and the code use no SQLite-only features that were knowingly relied on, but they must be exercised on PostgreSQL before go-live.
- Leaving the project's Dashboards tab for another project tab does not warn about an unsaved layout (switching dashboards, following links and closing the page do).
