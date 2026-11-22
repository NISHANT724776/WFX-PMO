# UI redesign: regression report

**Scope:** presentation only. Backend, API, database, permissions, routes and calculations untouched.

## Verified
- ESLint and TypeScript clean; production build passes (`/guide` included).
- Browser pass (desktop 1440 px, tablet 768 px for the drawer): login, Home, Projects, project Overview, Dashboards (Overall status, Week plan, Delays), Plan (table, Gantt), Delivery, Pending (+ side panel), UAT, Reports & integrations, Trackers, Smart Import, Users, Audit Log, Flex fields (+ Define dialog), collapsed sidebar rail with tooltips.
- Not opened: the Archive tab, the Smart Import detail screen and master-data record dialogs after the restyle.
- Backend test suite (143 tests) not re-run, because no backend file changed.

## Visual changes
Light collapsible sidebar and breadcrumb header; new palette (navy ink, indigo-blue accent); softer corners; table headers and row hover; badge style; segmented switchers; KPI cards; date strip (original / current approved / actual) with revision timeline; login page; read-only `/guide`.

## Preserved
All routes, permission-based menu visibility, forms and validation, revisions rules, delay calculation, import/export, audit.

## Existing issues found
- Wide tables pushed the page sideways (fixed: they now scroll inside the content panel).
- Customer role can still see every project record (known, unchanged).
- A link opened in a new browser tab signs the user out (token is stored per tab).
- UAT empty state repeats its message.

## Future suggestions (need functional change)
Project/customer chip in header; daily/weekly WBS; notifications; global search; team workload; gate date revision history; sticky table headers.

## Before images
No version control exists, so "before" screenshots were produced by rebuilding the original shell and shared components from their original code and capturing them with the same data. Some small details inside screens (for example list timelines in side panels) were rebuilt by hand.
