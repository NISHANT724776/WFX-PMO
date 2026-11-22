# Source-to-Module Mapping

Columns below were read from the actual workbooks (header rows as observed). "Phase" = the roadmap phase that implements the target. Nothing here is invented: where a source holds only a count or a folder name, that is stated. Original source references (workbook, sheet, row, column) are preserved by the import engine (Phase 2); no source field is silently dropped: unmapped columns stay in raw import storage.

## 1. Tegra Tracker (3) (current) and (1) (history)

| Sheet | Observed columns | Target | Phase | Notes |
|---|---|---|---|---|
| Master Sheet (v3) / Sheet1 (v1) | Events, Responsibility, SPOC, then per product **Planned Date / Actual Date** pairs: PLM, ERP, Plan, WMS (v3 only), MES, Finance (+ Actual Costing in v3) | `tracker_event` (one row per event x product): project, product, event, responsibility, SPOC, planned date, actual date | 2/3 | **Unpivot** wide columns. Title row + 2-row header (v1). v1 has no WMS. |
| Blue Printing Signoff (v3) / PI Point + AS-IS + Blueprint Mapping (v1) | Department/Team, Mapping Date, Submission Date, Sign-Off Date, Status (v3 only), Sign-Off Status | `approval_gate` per department/team (+ site) | 3/4 | Feeds the Sign-Off Gate Tracker and Business Blueprint Coverage panels. |
| Gap Tracker (v3, 254x20) | S.No., Issue ID, Event, Team, Module, Development Scope, Brief Description, Priority, Category, WFX Solution, Spec Status, Remarks, Responsibility, Specs Target Date (+ remaining columns to 20) | `gap_specification` | 5 | `Issue ID` repeats; stored as `external_issue_id`, never unique. |
| Gap Tracker (v1, 276x12) | Event, Issue ID, Description, Product, Area, Received On Date, Created On Date, Proto Created, Specs Created, Submitted On Date, Signed off Date, Current Status | `gap_specification` (same target, different column set) | 5 | v1 has proto/received dates that v3 lacks; v3 has priority/category/responsibility that v1 lacks. Both load into one table; missing fields stay NULL. |
| E2E | Description, Target Date, Actual Date, Submission Date, Sign-Off Date, Approval Status | `approval_gate` (type = e2e) | 4 | Rows: Modified, Non-Modified (Inline, Stock). |
| UAT Accecptence Criteria (sic) | Module, Functionality, Scenario ID, Source ID, Scenario Type, Scenario Title, Business Objective, Pre-Conditions, Expected Results, Test Data, Source, Linked Test Cases, Status (Pass/Fail), Remarks/Defects | `uat_scenario` + `test_execution` | 6 | 133 rows incl. title rows. |
| Reports + Prints | Folder, Sub-Folders, Reports Count (Updated) | `report_print_inventory` (folder, sub-folder, count) | 6 | **Counts only**: no per-report rows exist in the source (decision 5). |
| Integration | (v3) Company, Business Domain, Partner / System, Process, Message / Format, Technology, Direction, Region / Entity, Status, Notes, System path / URL Endpoint, Reference Info, ERP Reference, Template; (v1) same without Company, plus Documented | `integration_record` | 6 | v3 adds Company. |
| Lists | Product, Event, Yes/No, Current Status | Lookup/config seed for product x event applicability | 3 | Controls which events apply to which product. |

## 2. Tegra_Consolidated_ProjectPlan_V4 (Detailed Project Plan-A)

| Source column | Target (`work_item`) | Notes |
|---|---|---|
| Phase | parent `project_phase` | Phase title rows are *inside* the data: parse as parents, not tasks. |
| Task / Activity | title | |
| Responsible Party | responsibility (JOINT / WFX / Tegra ...) | |
| Location | `project_site` | e.g. Arena (Honduras) |
| Start Date / End Date | baseline planned start / finish | Immutable after baseline (revisions go to `date_revision`). |
| Duration (Days) | derived; stored raw | |
| Actual Start / End Date | actual start / finish | |
| Onsite/Remote | `delivery_mode` (Remote -> Online, raw kept) | |
| Status | raw status + normalized via `status_configs` | |
| Dependencies | text kept raw; resolved to `work_item_dependency` where the reference is unambiguous | |
| Resource Allocation / Resource Name | `resource` assignment | |

## 3. Shahi Tracker (15 Oct 2026, as of 17 Nov)

| Sheet | Observed columns (abridged) | Target | Phase |
|---|---|---|---|
| Dashboard | KPI counts per sheet (Total items, Total BRD points, Total components, ...) | Not imported. Reference for the WBS dashboard; counts are recomputed from data. | 4/7 |
| Summary Schedule | Project Stage, Project Milestone, Start Date, End Date, Finance SPOC, Operational SPOC, Delivery Schedule | `milestone` | 3 |
| Delivery Schedule (386x22) | ID, Stream, Module, Description, Priority, WFX helpdesk Status, Status, Functional Owner, Customer Discussion Status, Customer Spec Closure date, Dev Initiation date, Handover to QA Date, QA Release Date, Internal Release to UAT ... | `delivery_item` (customer-facing dates win, decision 3) | 5 |
| Tech_Final (389x30) | ID, Stream, Module, Description, Priority, WFX helpdesk Status, Status, Functional Specs Status, Functional Owner, Product Owner, Tech Owner, QA Owner, Customer Discussion Status, Customer Spec Closure date ... | `delivery_item` (owner/QA fields win, decision 3) | 5 |
| Finance BRD | Sr No, BRD SR, Key Pointers, Module, BRD Status, Development Phase, Covered in Proto, Responsibility, Target Date, Remarks, Type | `brd_requirement` | 5 |
| Operations BRD | S.no., Category, Helpdesk ID, Shahi Tracker Ref, Helpdesk Description, BRD status, BRD Responsibility-WFX, Target Closure Date | `helpdesk_item` + `requirement_link` | 5 |
| Pending Items | Components, Responsibility, Target Date, Revised Target Date, Actual Closure Date, Responsibility (WFX Owner), Meeting Remarks | `dependency_item` (pending_with = Customer or WFX) | 3 |
| Open for Discussion | Sr No, Name, BRD Serial No, Tracker Sr No, Remarks, Type, Module, Concern, Functionality status, Document Reference, Report Responsibility, Target Date | `discussion_item` | 5 |
| New-Open Points-Ops | S.No, Request Date, Request From, Division, Description, Status | `helpdesk_item` (open ops points) | 5 |
| Out Of Scope Points | Feedback, Scope as per BRD, Requirement | `scope_decision` | 5 |
| WBS Week Wise (714x18) | WBS Code, Level, Week, Week Start, Week End, Source Sheet, Workstream / Module, Activity / Work Package, Ref IDs, Owner, Item Count, Planned Start, Planned Finish, % Complete ... | `wbs_node` (Level 1 week, 2 source, 3 work package) | 7 |
| WBS Week Summary | Week, Week Start, Week End, per-sheet counts, Total Items, Overdue Packages, Due in 7 Days, Weighted % Complete | Not imported: recomputed. Used as a reconciliation check. First row shows WK47-**2025** (anomaly, decision 6). | 7 |

## 4. Tegra PPT -> dashboard components

| Slide | Content | Component / data needed |
|---|---|---|
| 3 | Overall status: 5 KPIs (overall %, completed, in progress, overdue phases, upcoming), Q/M timeline, phases grouped by area | Dashboard A: needs `project_phase` with planned/actual dates + status |
| 4-8 | PLM/ERP, PLAN, WMS, MES, Finance: KPI strip, Gantt left, Sign-Off Gate or Dept x Site coverage right, Needs Attention | Dashboard B: `work_item` + `approval_gate` + `tracker_event` |
| 9 | Next Week Plan: week banner, groups (PLM/ERP, PLAN, MES, WMS & Tegra Inputs), numbered cards | Dashboard C: union of due items for the week |
| 1, 2, 10 | Title, contents, closing | Export cover only |

## 5. Version differences to report on import (Tegra v1 vs v3)
Master: v3 adds WMS and Finance + Actual Costing pairs. Gap Tracker: different column sets (see section 1). Blueprint sheet renamed and gains Status. Integration gains Company. The import engine must show this as a diff, never merge silently (decision 4).

## 6. Not derivable from the files (must not be invented)
Project health, weighting of completion beyond the PPT formula, per-report details for Reports + Prints, revision reasons/approvers for historical date changes, user accounts.
