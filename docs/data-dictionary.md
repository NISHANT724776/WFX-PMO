# Data Dictionary (Phase 1 tables)

All tables have `id` (UUID PK). `created_at`/`updated_at` (UTC) where marked T. Later-phase tables are added to this file as they are built.

| Table | Column | Type | Rules / meaning |
|---|---|---|---|
| **users** (T) | email | str(255) | unique, lower-cased |
| | full_name | str(150) | |
| | password_hash | str(255) | argon2; never returned by the API or written to the audit log |
| | is_active | bool | inactive users' tokens are rejected immediately |
| | role_id | FK roles | one role per user |
| **roles** | code | str(50) | super_admin, pmo, project_manager, functional_consultant, developer, qa, management, customer_user |
| | is_global_scope | bool | true = sees all projects; false = only projects in user_project_access |
| **permissions** | code | str(80) | `module:action`, e.g. `projects:write` |
| **role_permissions** | role_id, permission_id | PK pair | |
| **user_project_access** | user_id, project_id | PK pair | record-level grant for non-global roles |
| **customers** (T) | code, name, country, is_active | | code unique |
| **products** (T) | code, name, description, is_active | | PLM, ERP, PLAN, WMS, MES, Finance are data, not code |
| **departments** (T) | code, name, is_active | | |
| **locations** (T) | code, name, country, timezone, is_active | | master list (Arena, Decotex ...) |
| **resources** (T) | full_name, email, department_id, user_id, is_active | | consultant/employee; optional login link |
| **status_configs** (T) | entity_type, code, label, category, color, sort_order | | `category` (not_started, in_progress, done, blocked, cancelled) drives KPI logic; labels are editable. Seeded for work_item, milestone, delivery_item, dependency |
| **projects** (T) | customer_id, code, name, description, status, start_date, target_go_live, manager_id | | go-live must not precede start |
| **project_products** | project_id, product_id, go_live_date | | unique pair |
| **project_sites** | project_id, location_id, entity_name | | e.g. Arena / "The Arena, Honduras" |
| **custom_field_definitions** (T) | customer_id (null = global), entity_type, field_type, slot, label, options (JSON), is_required | | 5 dropdown + 5 date + 5 text per entity; dropdown options per customer; options only for dropdown |
| **custom_field_values** (T) | definition_id, entity_type, entity_id, value_text, value_date | | one value per (definition, entity). Value API arrives with the plan entities (Phase 3) |
| **audit_logs** | at, user_id, user_email, action, entity_type, entity_id, before (JSON), after (JSON) | | append-only; actions: create, update, delete, login, login_failed. user_id has no FK so history outlives users |

## Phase 2 tables (migration 0002)
| Table | Purpose / key columns |
|---|---|
| **import_batches** | one uploaded file: filename, stored_name, size_bytes, sha256, status (uploaded, analyzing, ready, failed, committed, rolled_back), uploaded_by, project_id, template_id, meta (relationships, validation summary), commit_summary |
| **uploaded_sheets** | per sheet: name, classification + confidence, entity (target), enabled, config (header_row, product_map, value_maps, gate_type), profile |
| **detected_columns** | per column: index, letter, header, group_label (product band), inferred_type, profile (samples, uniques, hidden, non-date values) |
| **column_mappings** | one per column: target_field, score, level (high, medium, low, none, manual), status (suggested, confirmed, ignored, unmapped), source (auto, history, template, user), alternatives |
| **mapping_templates** | name, definition (per-sheet headers, mappings, header row, product map), use_count |
| **validation_errors** | batch, sheet, row, column, field, severity, code, message, raw_value, rejects_row |
| **import_row_references** | provenance: batch, sheet, source_row, entity_type, entity_id, action (created, updated, skipped), before (for rollback), row_stamp, raw (original cells) |
| **project_phases** | project_id, name, sort_order (unique per project) |
| **work_items** | plan task: project, phase, product (NULL = all), title, responsible_party, owner_name, location_label/location_id, delivery_mode (onsite/online), planned_start/finish (baseline), duration_days, actual_start/finish, status_raw + status_category, dependencies_text, resource_allocation, remarks |
| **tracker_events** | event x product: project, product, event_name, responsibility, spoc, planned_date, actual_date |
| **approval_gates** | project, gate_type (from sheet name), name, mapping/planned/actual/submission/signoff dates, approval_status, comments |
| **gap_specifications** | project, serial_no, external_issue_id (not unique), event, team, product_name, module, development_scope, description, priority, category, wfx_solution, spec_status, remarks, responsibility, target/actual/submission/signoff/received/created dates, approval_status, proto_status, specs_created |

All four imported-record tables also carry `match_key` (business key for re-import), `raw_values` (original text of unparseable cells) and `import_batch_id`.

## API surface (Phase 1), all under `/api/v1`
`POST /auth/login`, `GET /auth/me` · `GET/POST /users`, `PATCH /users/{id}`, `GET /users/roles`, `GET/PUT /users/{id}/project-access` · `GET/POST/PATCH/DELETE` on `/customers`, `/products`, `/locations`, `/departments`, `/resources`, `/status-configs` (search `q`, `page`, `size`) · `GET/POST/PATCH/DELETE /projects`, `POST/DELETE /projects/{id}/products|sites` · `GET/POST/PATCH/DELETE /custom-fields` · `GET /audit-logs` · `GET /health`. Interactive docs: `/docs`.

## Permission matrix (Phase 1)
| Permission | super_admin | pmo | project_manager | other project roles | management | customer_user |
|---|---|---|---|---|---|---|
| users:read / users:write | both | read | no | no | no | no |
| master:read / master:write | both | both | read | read | read | no |
| projects:read | yes | yes | yes (granted only) | yes (granted only) | yes (all) | yes (granted only) |
| projects:create | yes | yes | no | no | no | no |
| projects:write | yes | yes | yes (granted only) | no | no | no |
| custom_fields:write, audit:read | yes | yes | no | no | no | no |

## API surface (Phase 2)
`POST /imports` (multipart) · `GET /imports`, `GET/DELETE /imports/{id}` · `GET/PATCH /imports/{id}/sheets/{sheet_id}` · `PUT .../sheets/{sheet_id}/mappings` · `POST /imports/{id}/validate` · `GET /imports/{id}/errors`, `/errors.csv`, `/preview?sheet_id=`, `/relationships`, `/dashboard-suggestions` · `PATCH /imports/{id}/relationships/{n}` · `POST /imports/{id}/commit`, `/rollback` · `GET/DELETE /import-templates` · `GET /projects/{id}/phases|work-items|tracker-events|approval-gates|gap-specifications`.

New permissions: `imports:read`, `imports:upload`, `imports:commit`, `imports:rollback` (see docs/excel-intelligence.md).

## Phase 3 additions (migration 0003)
| Table | Purpose / key columns |
|---|---|
| **work_items** (extended) | + kind (task / milestone), parent_id, revised_start, revised_finish (latest APPROVED revision; planned_* stay the baseline) |
| **date_revisions** | append-only: project, entity_type (work_item / dependency_item), entity_id, field, old_date (effective at request time), new_date, reason, status (proposed, approved, rejected), requested_by(+email, at), decided_by(+email, at) |
| **work_item_dependencies** | predecessor, successor, dep_type (FS), lag_days; unique pair; loops refused in the API |
| **dependency_items** | pending activity: project, product, category (section), pending_with (customer, wfx, external, internal), description, owner_name, original_target_date (baseline), revised_target_date, actual_closure_date, status_raw/category, remarks, linked_work_item_id |
| **projects** (extended) | + delay_grace_days (0-60, default 0) |

New permission `plan:approve` (super_admin, pmo, project_manager). New endpoints under `/projects/{id}`: `work-items` (CRUD + filters), `work-items/{id}/revisions`, `revisions/{rid}/decision`, `revisions`, `work-items/{id}/dependencies`, `dependencies`, `dependencies/bulk`, `dependency-suggestions`, `phases/{pid}/assign-product`, `pending-items` (CRUD, `/revisions`), `pending-summary`; and `/custom-field-values/{entity_type}/{entity_id}` (GET, PUT).

## Phase 4 additions (no new tables)
New permission `dashboards:export` (super_admin, pmo, project_manager, management). New endpoints under `/projects/{id}`: `dashboards/overall`, `dashboards/product/{product_id}`, `dashboards/next-week?period=this_week|next_week|next_month`, `dashboards/delays` (all take `as_of`), and `dashboard-exports/{overall|product|next-week|delays}` (PowerPoint file). Dashboards are computed on request from the canonical tables; nothing is stored.

## Phase 5 additions (migration 0004)
| Table | Purpose / key columns |
|---|---|
| **delivery_items** | ticket: external_id (repeats), parent_external_id, stream, module, description, priority, status_raw/category, helpdesk_status_raw/category, functional/product/tech/QA owner, specs/testing responsibility, spec/discussion statuses, stage dates (spec_closure_date, spec_closure_actual, dev_initiation, dev_completion, qa_release, uat_release, customer_release, customer_uat_closure), delivery_target_date (baseline, derived once), revised_target_date, actual_completion, specs_completed, remarks, sources (which sheets), merge_notes (disagreements) |
| **brd_requirements** | sr_no, brd_serial (repeats), description, module, brd_status, development_phase, covered_in_proto, responsibility, target_date, revised_target_date, req_type, remarks |
| **helpdesk_items** | kind (ops_brd / open_point), external_id, category, tracker_ref, description, status_raw/category, responsibility, target_date, request_date/from, division |
| **discussion_items** | name, brd_serial, tracker_sr_no, concern, module, item_type, functionality_status, responsibility, target_date, status (open/decided/closed), final_decision, meeting_remarks |
| **scope_decisions** | customer_feedback, original_scope, new_requirement, reason, approval_status (pending/approved/rejected), decision_owner, decision_date |
| **requirement_links** | source/target type + id, link_type (related, same_ticket, parent_child, brd_discussion), basis (the evidence), unique per pair |
| gap_specifications (extended) | + revised_target_date |
| import_row_references (extended) | + seq (write order; rollback undoes newest first) |

New endpoints under `/projects/{id}`: `records/{delivery-items|requirements|helpdesk-items|gap-specifications|discussions|scope-decisions}` (list with filters/search/paging, `/facets`, `/{rid}` detail, create, PATCH, DELETE, `/{rid}/revisions`), `links` (create, DELETE), `link-suggestions`, `links/bulk`. Sheet detail now returns `status_values`; sheet PATCH accepts `value_maps` (status wording -> category).

## Stage 1 additions (migration 0005)
| Table / column | Purpose |
|---|---|
| `archived_at/by`, `deleted_at/by` on work_items, approval_gates, gap_specifications, dependency_items, delivery_items, brd_requirements, helpdesk_items, discussion_items, scope_decisions, action_items | archive and trash state; a row is active when both are empty |
| **comments** | entity_type + entity_id, body, author, time |
| **attachments** | entity_type + entity_id, filename (label), content_type, size, storage_name (generated), note, uploader |
| **action_items** | title, description, owner_name, priority (low/medium/high/critical), due_date, status (open/in_progress/escalated/resolved), escalation level/to/reason, resolution note, reopen count, linked task, last action + by + at |

Endpoints under `/projects/{id}`: `lifecycle` (counts), `lifecycle/{type}` (archived or trashed list), `lifecycle/{type}/{rid}/{archive|restore|delete|purge|duplicate}`, `lifecycle/{type}/bulk`; `comments` (list, add, delete); `attachments` (list, upload, download, delete); `records/action-items` (same CRUD as other records) plus `records/action-items/{rid}/{escalate|resolve|reopen}`. Record lists and details accept `state=active|archived|deleted`.

## Trackers (migration 0009)
| Table | Purpose / key columns |
|---|---|
| **uat_scenarios** | scenario_id (reference), title, module, cycle, tester, planned_date, executed_date, result (not_run/in_progress/passed/failed/blocked/retest), result_raw (imported wording), actual_result, defect_ref, pre_condition, test_data, steps, expected_result, business_objective |
| **uat_defects** | scenario_id (FK), defect_ref, title, severity, status (open/in_fix/retest/closed/rejected), raised_on/by, owner_name, target_date, closed_on, resolution |
| **integration_items** | name, partner, system, direction, technology, message_type, business_domain, region, endpoint, owner_name, status_raw/category, target_date (baseline), revised_target_date, actual_date, uat_status |
| **report_items** | name, report_type, module, folder, sub_folder, reports_count, complexity, owner_name, status_raw/category, target_date (baseline), revised_target_date, actual_date, uat_status |

All four carry archive/trash columns and the import provenance columns. New endpoints: `records/{uat-scenarios|uat-defects|integration-items|report-items}` (the common record API, revisions for the last two), `GET /projects/{id}/uat/summary`, `GET /projects/{id}/deliverables/summary`, `GET /custom-fields/entities`.
