# UAT, reports + prints, integrations and flex fields

Code: `backend/app/models/workspace.py` (tables), `backend/app/api/records.py` (rules), `backend/app/modules/dashboards/trackers.py` (summaries and delay rules), importer entries in `backend/app/modules/excel_intel/`, UI `frontend/src/components/qa/` and `frontend/src/app/(app)/admin/flex-fields/`. Migration `0009`; tests `backend/tests/test_trackers.py`.

## UAT (project → UAT)
- **Scenarios** (scenario ID, scenario, module, UAT cycle, tester, planned date, executed on, result, actual result, defect reference, pre-condition, test data, steps, expected result, business objective). Result: not run, in progress, passed, failed, blocked, retest.
- **Rules (server side):** Passed and Failed need a tester and an execution date that is not in the future; Failed needs the actual result; a scenario cannot be Passed while it has an open defect. The history of result changes is in the audit log.
- **Defects** (ref, title, scenario, severity, status, raised on/by, owner, target, closed on, resolution): Closed needs the closed date and the resolution; Rejected needs a reason; reopening clears the closed date (the close stays in the audit log); an open defect cannot be raised against a scenario marked Passed (mark it Failed or Retest first); the scenario must belong to the same project.
- **Numbers** (named formulas, shown on screen): pass rate = passed ÷ all scenarios; executed = (passed + failed) ÷ all; overdue = still to run (not run, in progress, blocked, retest) and the planned date (+ grace days) has passed. Results by module and by cycle, open defects by severity, oldest open defect.

## Reports + prints and integrations (project → Reports & integrations)
- **Integrations** (integration, partner, system, direction, technology, message/object, business domain, region, endpoint, owner, status, target, UAT status) and **reports + prints** (name, type, module, folder, sub folder, reports count, complexity, owner, status, target, UAT status).
- Status uses the configurable status list (Status Configuration: `integration_item`, `report_item`). The **target date is a baseline**: it is entered when the item is created and afterwards moves only through a dated revision with a reason (approved by someone with the approve permission); slippage is measured against the baseline. Overdue = not closed (status done/cancelled or an actual date) and the current target (latest approved revision, else the baseline) + grace days has passed.

## Where they show up
- **Delays dashboard:** four new sources (UAT scenarios, UAT defects, integrations, reports + prints), with the same split by product, owner, age and party.
- **Week plan:** UAT scenarios to run (grouped by module), defects due, integrations and reports due, with overdue carry-overs.
- **Needs attention:** scenarios not run past their date, open critical/high defects, overdue integrations and reports.
- **Dashboard builder:** a UAT status widget (results, pass rate by module or cycle, open defects by severity) and the status-breakdown widget can use UAT, defects, integrations and reports as data sources.
- **Reports and exports:** two more reports, "UAT status" and "Reports, prints and integrations", in Excel, PDF and PowerPoint.
- **Quick add:** UAT scenario, Integration and Report / print.

## Excel import
Smart Import now imports the three sheet types it already recognised: UAT scenarios, an integration register and a reports + prints inventory (headers such as Scenario ID / Expected Result / Test Status; Partner / Technology / Direction; Folder / Sub Folder / Reports Count).
- UAT result wording is mapped (Pass/Passed/OK, Fail/Failed, Blocked/On hold, Re-test, In progress/Testing, Not started/Pending). **Wording it cannot place is not guessed**: the scenario is imported as Not run, the original text is kept, and the import reports it.
- An integration with no name column is named from partner + message (or system); an inventory row with only folders is named from the sub folder (or folder). A row with nothing to name it from is rejected and listed.
- Rolling back an import removes what it created, as for the other sheets.

## Flex fields (Administration → Flex fields)
Define up to 5 drop-down, 5 date and 5 text fields for each of 16 record types (plan tasks, pending items, delivery items, requirements, helpdesk, gaps, discussions, out of scope, actions, sign-off gates, coverage, week plan, UAT scenarios, UAT defects, integrations, reports + prints), for every customer or for one customer. Drop-downs take a list of choices; any field can be required. They show under "Custom fields" in the record's side panel. Removing a field deletes the values entered in it (the screen says so first). The kind of field and its position cannot be changed after creation.

## What the real Tegra tracker gives (checked against the workbook)
Importing `Tegra Tracker (3).xlsx` now also fills the three trackers: **129 UAT scenarios** (sheet "UAT Accecptence Criteria", all "not run" because its Pass/Fail column is empty; none are invented), **68 integrations** (sheet "Integration") and **22 report folders totalling 1,794 reports** (sheet "Reports + Prints"). Counts are recomputed from the raw sheets in the tests. Headers map at high confidence (Scenario Title, Scenario ID, Module, Functionality, Scenario Type, Source ID, Business Objective, Test Data, Linked Test Cases, UAT Role; Partner / System, Direction, Technology, Region / Entity, Message / Format, System path / URL endpoint, Documented, WFX Status; Folder, Reports Count).
- **Classify the integration statuses when you import.** The sheet's status wording ("Currently In Use", "Required – not implemented") is not in the standard list, so it is left unclassified and, by the rule that unknown wording is never counted as done, those integrations count as open. The mapping screen's Status values panel lists each wording with its row count; set "Currently In Use" to Done and they stop showing as late. The integration sheet's only date columns are the specification target and actual dates, which are what become the integration's target and actual dates.
- A few columns of the integration sheet have no home yet and are listed as ignored on the mapping screen (Reference Info, ERP Reference, WFX Review Date, WFX Comment, the specification submission and sign-off dates, Approval Status). Nothing is dropped silently: add them as flex fields if you need them.
