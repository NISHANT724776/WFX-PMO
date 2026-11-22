# Database ERD

PostgreSQL is the target. Phase 1 tables exist and migrate (`backend/alembic/versions/0001_phase_1_foundation.py`); later groups are the design agreed in the plan.
Rules: UUID primary keys; external references (Issue ID, Helpdesk ID, BRD serial) are separate non-unique columns; planned dates are baselines and revisions are appended; raw imported status is kept beside the normalized status; JSONB (JSON) only for audit snapshots, option lists and import provenance.

## Phase 1 (implemented)

```mermaid
erDiagram
  roles ||--o{ users : has
  roles }o--o{ permissions : "role_permissions"
  users ||--o{ user_project_access : granted
  projects ||--o{ user_project_access : scopes
  customers ||--o{ projects : owns
  projects ||--o{ project_products : has
  products ||--o{ project_products : used_in
  projects ||--o{ project_sites : has
  locations ||--o{ project_sites : used_in
  departments ||--o{ resources : employs
  users ||--o| resources : "optional login"
  users ||--o{ projects : manages
  customers ||--o{ custom_field_definitions : "options per customer"
  custom_field_definitions ||--o{ custom_field_values : holds
  users ||--o{ audit_logs : "actor (no FK, append-only)"
```

## Planned groups (Phases 2-7)

```mermaid
erDiagram
  projects ||--o{ project_phases : has
  project_phases ||--o{ work_items : contains
  work_items ||--o{ work_items : "parent/child"
  work_items }o--o{ work_items : "work_item_dependencies"
  work_items ||--o{ date_revisions : history
  work_items }o--|| project_sites : at
  work_items }o--o| resources : assigned
  projects ||--o{ tracker_events : "event x product"
  projects ||--o{ approval_gates : has
  projects ||--o{ brd_requirements : has
  brd_requirements }o--o{ delivery_items : "requirement_links"
  brd_requirements ||--o{ gap_specifications : "N specs"
  gap_specifications }o--o{ delivery_items : links
  delivery_items ||--o{ delivery_stage_history : tracks
  helpdesk_items ||--o{ delivery_items : "1..N"
  projects ||--o{ dependency_items : "pending_with Customer/WFX/External/Internal"
  uat_scenarios ||--o{ test_executions : runs
  test_executions ||--o{ defects : raises
  wbs_weeks ||--o{ wbs_nodes : "L1 week -> L2 source -> L3 package"
  wbs_nodes }o--o| work_items : "references, never duplicates"
  import_batches ||--o{ uploaded_sheets : has
  uploaded_sheets ||--o{ detected_columns : has
  detected_columns ||--o{ column_mappings : mapped_by
  import_batches ||--o{ import_row_references : provenance
  import_batches ||--o{ validation_errors : reports
  mapping_templates ||--o{ column_mappings : reused
  generated_dashboards ||--o{ dashboard_widgets : has
```

## Constraints worth knowing (Phase 1)
- `customers.code`, `products.code`, `departments.code`, `locations.code`, `projects.code`, `users.email`: unique.
- `project_products(project_id, product_id)` and `project_sites(project_id, location_id)`: unique pairs.
- `custom_field_definitions`: slot 1..5, type in (dropdown, date, text), unique (customer, entity, type, slot); a partial unique index covers the NULL-customer (global) case because a plain UNIQUE ignores NULLs.
- `status_configs`: unique (entity_type, code); category in (not_started, in_progress, done, cancelled, blocked).
- Deleting a customer/product/location that is referenced returns 409 (use is_active=false instead).
