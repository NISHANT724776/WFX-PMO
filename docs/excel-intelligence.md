# Excel Intelligence (Phase 2): how it works and what it will and will not do

Code: `backend/app/modules/excel_intel/`, API `backend/app/api/imports.py`, UI `frontend/src/app/(app)/excel-intelligence/`.

## Pipeline
Upload -> safety checks -> background analysis -> user reviews mapping -> validate -> preview -> commit (one transaction) -> optional template -> dashboard suggestions.

| Step | What happens | Where |
|---|---|---|
| Safety | `.xlsx/.xls/.csv` only; macro workbooks (`vbaProject.bin`) refused; zip-bomb guard (expanded size and ratio); 25 MB cap; stored under a random name, never the user's filename; formulas are read, never evaluated | `reader.py` |
| Profile | every sheet: header row, group band, section rows, per-column type, samples, unique values, hidden columns, formula/error cells, duplicate rows | `profiler.py` |
| Classify | project plan, milestone matrix, gap tracker, sign-off gates, UAT, integration, reports inventory, delivery, BRD, dependencies, WBS, lookup, unknown | `classifier.py` |
| Map | per column: 0.60 header similarity + 0.25 value pattern + 0.15 context, +history, template override. High >= 0.85, Medium 0.65-0.84, Low 0.45-0.64, none below | `mapper.py`, `catalog.py` |
| Relationships | candidate cross-sheet links (value overlap), unique-ID columns, repeated references; user confirms/rejects (recorded, not yet used by import) | `relations.py` |
| Validate | parse + normalise + check; every issue stored with sheet, row, column, original value | `transform.py` |
| Commit | create-only or update, in one transaction, with provenance per row | `committer.py` |
| Templates | approved mapping saved; recognised next time when >= 80% of headers match | `service.py` |
| Dashboard hints | which templates the mapped fields can support. No numbers are computed here | `recommender.py` |

## Rules that are enforced (and tested on the real Tegra files)
- **Confidence policy.** High is pre-applied. Medium does nothing until a person confirms it (validation blocks). Low and unmapped are never applied.
- **Nothing is dropped silently.** Rows that cannot be imported are *rejected with a reason* and listed in the error report (CSV download, formula-injection safe). Committing with rejected rows needs an explicit confirmation.
- **Nothing is invented.** A product column group is linked to a product only if its name matches a Product exactly (case-insensitive); otherwise the user chooses or excludes it. Plan tasks have no product column, so they are stored project-wide (`product_id` NULL).
- **Unparseable values.** `-`/blank markers are "no value" (no warning). `TBA`/`TBD` and other non-dates become empty plus a warning, and the original text is kept in `raw_values`.
- **Excel errors (`#REF!`).** In a required field the row is rejected; in an optional field it is a warning and the row is kept. (The real Gap Tracker has 125 broken S.No. cells: warnings, rows kept.)
- **Statuses and Onsite/Online** are normalised (`Done`->done, `In-Progress`->in_progress, `Remote`->online); the raw text is kept (`status_raw`). Unknown values warn and leave the category empty.
- **Same value, different capitalisation** (`Tegra`/`TEGRA`) is harmonised to the most common spelling and reported. **Near-duplicates** (`Fjord, US`/`Fjord, USA`, `price valiation`/`price validation`) are only reported, never merged.
- **External IDs are not keys.** Matching on re-import uses a business key (e.g. issue ID + description hash, or phase + task + planned start), with `#n` suffixes for repeats.
- **Duplicate files.** The same file (SHA-256) cannot be committed twice into one project; a warning appears at upload. Roll back first to re-import.
- **Update mode never erases.** An empty cell in the new file keeps the stored value (a workbook saved without recalculated formulas would otherwise blank every duration).
- **Rollback is safe or refused.** Created rows are deleted and updated rows restored from their saved "before" values, but only if none were edited after the import; otherwise 409 and nothing changes.
- **Permissions.** `imports:upload` (functional, PM, PMO, admin) can upload/map/validate; `imports:commit` (PM, PMO, admin, project-scoped) approves; `imports:rollback` is PMO/admin. Non-global users only see their own batches or batches of projects they can access.

## Real findings from the Tegra files (reported by the tool, not hand-picked)
- Gap Tracker rows 130-254: S.No. is `#REF!` (125 cells). Six target dates are `TBA`.
- Plan: 8 of 18 section title rows do not match any task's Phase value (later titles were reworded); phases come from the Phase column, giving 16.
- Plan: `TEGRA` vs `Tegra`, `onsite` vs `Onsite`, `Fjord, US` vs `Fjord, USA`; 7 location labels are not in the Location master.
- Master Sheet: SPOC column is hidden; "Finance + Actual Costing" matches no product by name.
- `Lists` sheet is hidden in the workbook.

## Not built yet (be aware)
- Import targets exist for fifteen entities (twelve below plus UAT scenarios, the integration register and the reports + prints inventory, see docs/trackers.md): plan task, tracker event (matrix), approval gate, gap specification, pending item (docs/planning.md), delivery schedule + technical tracker (merged into one ticket), BRD requirement, helpdesk item, open point, discussion, out-of-scope request (docs/delivery.md). WBS sheets are classified and profiled but report "import arrives in Phase N".
- Plan->product assignment (no source column). Needs a business rule from you.
- Revised dates and date-revision history (Phase 3); the plan has none to import.
- Confirmed relationships are stored but not yet acted on.
- Analysis runs in a background task in the API process (FastAPI `BackgroundTasks`); the same function can be a Celery task once Redis is available. Commit is synchronous and atomic (fine for files up to the 25 MB cap).
- pandas was not needed: openpyxl/xlrd plus plain Python covers the profiling, with less memory.
- Large-file performance (tens of thousands of rows) is untested; the real files are a few hundred rows.
- `.xls` reading is implemented but only tested through code review, not with a real `.xls` fixture.
