# Planning (Phase 3): plan, revisions, dependencies, pending register

Code: `backend/app/api/plan.py`, `pending.py`, `flex_values.py`, `backend/app/modules/planning/delays.py`; UI `frontend/src/components/project/` and `frontend/src/app/(app)/projects/[id]/page.tsx`.

## The project workspace
Overview (KPIs, delay rule, products, sites) · **Plan** (Table, Gantt, Calendar; filters; item drawer) · **Pending** (customer / WFX / external / internal) · **Trackers** (imported events, gates, gap specs, read-only).

## Rules that are enforced (and tested)
- **Baseline is immutable.** `planned_start/finish` (tasks) and `original_target_date` (pending items) are set at creation or import and cannot be edited afterwards (422). Changes are *date revisions*: a reason is mandatory, every one is kept (proposed, approved, rejected), and only an **approved** revision moves the effective date. Resulting finish before start is refused.
- **Who approves.** Anyone with `projects:write` can propose. `plan:approve` (PMO, project manager, admin) approves or rejects, or approves in the same step. A role without it gets 403 on approval, even for its own proposal.
- **Delay rule, defined once** (`delays.py`): closed = status done/cancelled or an actual finish exists; **overdue** = not closed and effective finish + grace days < report date; **start delayed** = not started, effective start + grace < report date and not already overdue. Grace days is a per-project setting (0-60, default 0) because the business has not fixed the rule. The report date defaults to today and can be set.
- **Slippage is measured against the baseline**, so moving a date never hides a delay: a task pushed 20 days shows "+20 d" even when it is no longer overdue.
- **"Done" is not an actual date.** Setting a status to done does not invent an actual finish; the UI warns when it is missing.
- **Dependencies** are finish-to-start links between tasks with loop, self, duplicate and cross-project checks. The plan's free-text "Dependencies" column becomes suggestions only on an **exact task title** match; phase names are reported as phase references and never guessed; nothing is applied without a click/confirmation.
- **Product tagging is a deliberate action.** Plans carry no product column. "Tag with product" on a phase tags every task of it (audited, reversible); a product view shows tagged tasks plus, optionally, project-wide ones.
- **Flex fields** (5 dropdown + 5 date + 5 text per entity): values per record, validated (dropdown must be one of the options, dates must parse, required cannot be cleared), shown only for global fields and the project's own customer.
- **Pending register** has four views by who it is pending with, an overdue view, and a summary. Its dates use the same revision history.
- **Everything is audited** (create, update, delete, approve/reject, product tagging, flex values) and respects project-level access (404 for projects the user cannot see).

## Importing pending items (Shahi "Pending Items" sheet)
- Mapped fields: Components -> description, Responsibility -> pending with, Responsibility (WFX Owner) -> owner, Target / Revised Target / Actual Closure dates, Meeting Remarks.
- `WFX` is recognised. Any other value (e.g. the customer's name) must be classified by the user in the mapping screen (Customer / WFX / External / Internal / **Skip these rows**); nothing is guessed, and the import is blocked until it is done.
- "Completed" typed in the date column means closed, not an invalid date. With no status column, an item is closed if it has a closure date or was written as "Completed".
- The section a row was listed under (e.g. "Finance") becomes its category. The source's Revised Target Date becomes the first, approved entry in the item's revision history.
- Rows with a description but nobody named are rejected and listed, never silently dropped. Hidden rows are imported and reported.

## Real-data results
Tegra plan as of 21-Nov-2026: 185 tasks, 3 delayed (matching the 3 overdue phases on the status slide); approving one revision dropped it to 2 and the history shows who approved it and why. Shahi pending items: 64 imported (53 customer, 11 WFX; 44+11 open), 3 rejected, 33 hidden rows imported.

## Not built yet (be aware)
- **Assigned-to-me editing.** The permission matrix says functional consultants, developers and QA update only their own assigned work. That needs a link between users and resources/owners; for now only roles with `projects:write` edit the plan.
- **Milestone WBS, daily and weekly WBS** (Phase 7), **dashboards and export** (Phase 4).
- **Dependencies are not yet used to flag schedule conflicts** (a successor starting before its predecessor ends) or to move dates automatically.
- Revisions for tracker events and gap specifications; only plan tasks and pending items have them.
- Parent/child (sub-task) is stored and shown as a flat list; there is no tree view yet.
- The Gantt draws up to a few hundred rows without virtualisation; very large plans are untested.
- Calendar shows due dates only (not spans).

## Interactive Gantt (interactive dashboard, Stage 3)
Plan tab → Gantt (users with `projects:write`; others see the same chart read-only).
- **Move / resize:** drag a bar to move it, drag either end to resize. Releasing asks for a reason, then calls `POST /projects/{id}/work-items/{id}/reschedule`. The baseline is never overwritten: each changed date becomes a date revision (start and/or finish) with the reason, requester and approver; callers with `plan:approve` have it applied at once, otherwise it stays a proposal (dotted outline) until approved. A milestone is one date.
- **Validation (server side, repeated for direct API calls):** finish may not precede start; a task may not start before a predecessor's finish + lag (422, nothing saved); moving a task later reports successors it now squeezes (saved, with a warning); read-only roles get 403.
- **Dependencies:** drag the ○ at a bar's end onto another bar (finish-to-start, cycle check); click an arrow to see slack and remove it. `slack = successor start − (predecessor finish + lag)`; violated < 0; critical = predecessor still open and slack ≤ 0 (`modules/planning/graph.py`). Hovering a bar highlights its predecessors and successors.
- **Critical milestones:** an open milestone that is overdue, or has a critical incoming link, or is blocked by an open overdue predecessor (ringed diamond).
- **Add:** + Phase / + Task / + Milestone in the toolbar, + task / + ◆ / ✎ on a phase row, + sub on a task row (subtasks show indented). Empty phases stay visible; a phase can be deleted only when it holds no tasks, archived or trashed ones included.
- **% complete** (`percent_complete`, 0-100) is what the task's owner reports and darkens the bar. Dashboards still count status (done / ½ in progress) so the two are never mixed; if they disagree the task shows a notice, and nothing is changed automatically.
- Tests: `backend/tests/test_stage3.py` (slack and flags are re-computed independently on the real Tegra plan).
