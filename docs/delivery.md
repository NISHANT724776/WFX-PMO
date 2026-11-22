# Delivery and requirements (Phase 5)

Code: `backend/app/api/records.py` (one registry for all record types), `backend/app/modules/delivery/lifecycle.py` (the delivery rules), importers in `backend/app/modules/excel_intel/` (catalog, transform, committer), UI `frontend/src/components/delivery/`.
Data from `Shahi_Tracker_15OCT2026`: Delivery Schedule, Tech_Final, Finance BRD, Operations BRD, Open for Discussion, Out Of Scope Points, New-Open Points-Ops (plus Pending Items from Phase 3) and Tegra's Gap Tracker.

## Record types (project -> Delivery tab)
| Tab | Table | Source sheet | Notes |
|---|---|---|---|
| Delivery items | `delivery_items` | Delivery Schedule + Tech_Final | one ticket, two sheets, merged (below) |
| Requirements (BRD) | `brd_requirements` | Finance BRD | BRD serial repeats / "Not Received", so the source row number is kept separately |
| Helpdesk & operations | `helpdesk_items` | Operations BRD, New-Open Points-Ops | kind = ops_brd or open_point |
| Gaps & specifications | `gap_specifications` | Tegra Gap Tracker (Phase 2) | now editable; target date moves by revision |
| Open discussions | `discussion_items` | Open for Discussion | final decision and meeting remarks are entered here |
| Out of scope | `scope_decisions` | Out Of Scope Points | pending / approved / rejected |
Each list has search, filters built from the data, a "delayed only" switch, a report date, paging, and a drawer to read, edit and delete. Every change is audited. Writers need `projects:write`; deleting a record also removes its links and revision history.

## Delivery tickets: two sheets, one record
- The ticket number (`ID`) repeats in the real files (13-14 repeats), so it is a reference, not a key. The match key is the ID plus its n-th occurrence in the sheet, which lines the two sheets up.
- **Authority (decision 3).** When a ticket already came from the other sheet, **Delivery Schedule** decides the customer-facing dates (spec closure planned, dev initiation, handover to QA, QA release, UAT release, customer UAT release), the specs target and the specs/testing responsibility; **Tech_Final** decides the owners (functional, product, technical, QA), specs status, high/detail-level discussion, customer UAT closure, target BRD closure and the dev / meeting / PD remarks. Every other field is filled only if empty. Where the sheets disagree, the kept and the other value are stored in `merge_notes` and shown on the ticket ("the two source sheets disagree on N fields"). This is order-independent (unit-tested both ways) and nothing is lost.
- **Derived once:** the delivery commitment (`delivery_target_date`) = first available of customer UAT release, UAT release, QA release, dev completion. It is then a baseline: it is changed only by an approved date revision (full history, like the plan). Stage dates themselves stay as imported and can be edited.
- **Parent tickets.** "440679 : Party Configuration" is recorded as a child of 440679 (`parent_external_id`).
- **"Completed" under the specs target date means the specs are done, not the delivery** (`specs_completed`). It does not close a ticket. (I first read it as "delivered"; checking the first ticket in the UI showed the mistake, and a test now guards it.)
- IDs such as "On Hold" or "Explained" are kept but warned about; 6 rows with no ID and a description are rejected and listed.

## Delivery rules (`lifecycle.py`)
closed = status done/cancelled, helpdesk status done/cancelled (e.g. Closed, Deployed on Live), or an actual completion date. **Overdue** = not closed and delivery date (+ grace) passed. **Start delayed** = not closed, not overdue, no in-progress status and dev initiation (+ grace) passed. The lifecycle strip is built from planned dates; a stage shows green only when the ticket is closed or there is evidence (actual spec closure; work started), red when its planned date passed. These rules feed the Delay dashboard (new source "Development delivery"), the Week plan (deliveries due per stream, overdue carry-overs) and Needs attention. Development delays remain outside the completion formula (decision 9).

## Status wording (new in the mapping screen)
Statuses differ per sheet ("Pending For Delivery", "Deployed on Test", "Under Impl. Review" ...). The tool recognises only clear wording (e.g. In QA, Under Development -> in progress; Closed, Deployed on Live -> done; "Pending with <anyone>", "On hold" -> blocked). **Ambiguous wording is not guessed**: the mapping screen has a **Status values** panel listing every distinct value with its row count; you choose what it counts as, and the choice is saved in the mapping template. Unclassified values give one warning per distinct value (not one per row) and are never counted as done.

## Links between records (many-to-many)
`requirement_links` joins any two records. **Suggested links** (project -> Delivery -> Suggested links) shows only what the data itself supports, each with its evidence, and applies nothing until confirmed:
| Rule | Evidence | Result on the Shahi file |
|---|---|---|
| helpdesk_id | helpdesk ID = delivery ID | 106 of 109 helpdesk IDs match delivery tickets |
| parent_ticket | description names a parent ticket that exists (delivery -> delivery, and helpdesk -> child ticket) | 135 child tickets |
| brd_serial | discussion's BRD serial = requirement's BRD serial | only the serials present on both sides; 7 discussions name serials that are not in the requirements, and are reported, not linked |
Pairs where the same ID sits on several records are marked "ambiguous" and left unticked. Links can also be added and removed by hand from any record. Rolling back an import removes the links and revision history of the records it created.

## Date revisions on more records
Delivery items (delivery date), gap specifications and BRD requirements (target date) use the same revision engine as the plan: baseline never overwritten, reason required, only approved revisions move the date, history on screen. Scope decisions can be approved or rejected only with `plan:approve` and only with a named owner and a decision date.

## Real-data results
Delivery Schedule 385 rows + Tech_Final 388 rows -> 381 delivery tickets (378 in both sheets, merged; 3 only in Tech_Final); 14 rows rejected for a missing ID. Finance BRD 143, helpdesk 82 + 1 open point (34 Operations BRD rows rejected: no helpdesk ID or description), discussions 38, scope 4, pending 64. Corner cases the tool reported rather than hid: 383 of 385 Delivery Schedule rows are hidden in the workbook (filtered) and were imported anyway; 266 "#N/A" cells in Target BRD Closure; unknown status wording. 83 automated tests (all passing; frontend lint and build clean) recompute counts and links from the raw workbook.

## Not built yet (be aware)
- **Delivery-to-BRD links are not auto-detected.** The two files share no key between the Finance BRD and the delivery tickets (only helpdesk IDs and parent tickets match); those links are manual.
- **Product tagging for delivery tickets.** Tickets carry a stream (Finance, Logistics...) not a product; a product can be set by hand.
- **Delivery stage actuals.** The sheets hold planned dates only, so lifecycle stages cannot show true actuals until teams record an actual completion date.
- **Summary Schedule** (Shahi project milestones) is recognised as a project plan at low confidence and is not enabled by default.
- **WBS** sheets (Phase 7), **UAT, Reports + Prints, Integrations** (Phase 6).
- Gap-tracker import has no status-wording panel (its fields are free text).
- Editing is limited to roles with `projects:write`; "assigned to me" editing for developers/QA/consultants is still open.
