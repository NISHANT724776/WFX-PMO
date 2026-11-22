"""Permission catalogue and default role matrix. Seeded into the DB; DB is the runtime source of truth."""

PERMISSIONS: dict[str, str] = {
    "users:read": "View users",
    "users:write": "Create/edit users, reset passwords, grant project access",
    "master:read": "View master data",
    "master:write": "Create/edit master data (customers, products, locations, ...)",
    "projects:read": "View projects (scoped by project access)",
    "projects:create": "Create / delete projects",
    "projects:write": "Edit projects, products, sites (scoped by project access)",
    "custom_fields:write": "Configure flex fields",
    "audit:read": "Read audit log",
    "dashboards:export": "Export dashboards to PowerPoint",
    "dashboards:manage": "Create, edit and delete organisation-wide (management) dashboard layouts",
    "comments:read": "Read internal comments and attachments (customers cannot)",
    "comments:write": "Add comments and attachments on records they can see",
    "plan:approve": "Approve or reject date revisions",
    "imports:read": "View own / accessible Excel imports and templates",
    "imports:upload": "Upload workbooks, edit mappings, validate and preview (no commit)",
    "imports:commit": "Approve and commit an import into a project (project-scoped)",
    "imports:rollback": "Roll back a committed import",
}

# role code -> (display name, is_global_scope, permissions)
_READ = ["master:read", "projects:read"]
ROLE_MATRIX: dict[str, tuple[str, bool, list[str]]] = {
    "super_admin": ("Super Admin", True, list(PERMISSIONS)),
    "pmo": (
        "PMO",
        True,
        ["master:read", "master:write", "projects:read", "projects:create", "projects:write",
         "custom_fields:write", "audit:read", "users:read",
         "imports:read", "imports:upload", "imports:commit", "imports:rollback", "plan:approve", "dashboards:export", "dashboards:manage", "comments:read", "comments:write"],
    ),
    "project_manager": ("Project Manager", False, [*_READ, "projects:write", "imports:read", "imports:upload", "imports:commit", "plan:approve", "dashboards:export", "comments:read", "comments:write"]),
    "functional_consultant": ("Functional Consultant", False, [*_READ, "imports:read", "imports:upload", "comments:read", "comments:write"]),
    "developer": ("Developer", False, [*_READ, "comments:read", "comments:write"]),
    "qa": ("QA", False, [*_READ, "comments:read", "comments:write"]),
    "management": ("Management / Executive", True, [*_READ, "dashboards:export", "comments:read"]),
    "customer_user": ("Customer User", False, ["projects:read"]),
}
