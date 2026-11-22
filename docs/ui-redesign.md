# UI redesign: design system and rollout

Presentation only. No API, database, permission, route, calculation or form behaviour changed.

## Design system (where it lives)
| Piece | Where |
|---|---|
| Palette tokens (navy ink, indigo-blue accent, canvas `#f4f5f8`) | `frontend/src/app/globals.css` (`@theme`). Re-points the `blue-*` shades once, so every screen inherits it. |
| Font | Geist (already installed via `next/font`) |
| Icons | `components/icons.tsx`: Lucide-style line icons drawn inline; no icon package added |
| Buttons, inputs, selects, badges, page header, empty state | `components/ui.tsx` |
| Date components | `Slip` (days moved) and `DateJourney` (original → current approved → actual) in `components/ui.tsx` |
| Tables | One base style in `globals.css` (small caps headers, row hover) |
| Motion | 120–200 ms transitions only; `.wfx-enter` fade; all disabled under `prefers-reduced-motion` |

## Shell
Collapsible sidebar (240 px / 64 px rail, tooltips, grouped and collapsible sections, drawer below 1024 px), breadcrumb header, user chip, white content panel on a grey canvas. Only the existing routes appear, filtered by permission as before. Collapsed state and group state are stored in the browser only.

## Screens covered
Login, Home, Projects, project workspace (tabs, KPI cards, dashboards, plan, Gantt, delivery, pending, UAT, reports and integrations, trackers), master data, Smart Import, users, audit, flex fields, side panels and dialogs. Segmented controls (dashboard kinds, plan views, delivery kinds, trackers, UAT, integrations) now share one style.

## Date commitments (requirements 9)
- Plan table: planned shown muted when revised, revised in bold with a ±days badge, actual in green once finished.
- Side panels (plan item, pending item, delivery/BRD/gap/integration/report records): an Original → Current (approved) → Actual strip, then the revision history as a timeline with status, reason, requester and approver.
- Only data the record already holds is shown; a missing history is shown as "No revisions", never invented.

## Verification
ESLint clean, TypeScript clean, production build passes, browser pass over every route and project tab at desktop and tablet width. Backend untouched.

## Future recommendations (need functional change, not done)
- Project/customer context chip in the header (needs the shell to know the open project).
- Global search, notifications, "My workspace": not built in the product.
- Gate planned dates have no revision history to show.
- Sticky table headers need a scroll container per table.
- Daily/weekly WBS is not built.

## Guide: "How WFX PMO works"
Route `/guide` (read-only, frontend only, linked from Home; it is not in the sidebar because the sidebar lists only existing working routes). Nine stages with real screenshots of the redesigned app (`frontend/public/guide/*.png`, captured from the running app) and a ten-row requirements coverage matrix. Stage 7 states plainly that a daily/weekly WBS board is not built; the Week plan dashboard is the weekly view. Screenshots show local sample data and need recapturing if the screens change.
