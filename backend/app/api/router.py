from fastapi import APIRouter

from app.api import auth, builder, dashboards, flex_values, imports, lifecycle, pending, plan, platform, project_data, projects, records, users, workspace
from app.api.crud import build_crud
from app.models import Customer, Department, Location, Product, Resource, StatusConfig
from app.schemas.master import (
    CustomerCreate,
    DepartmentCreate,
    LocationCreate,
    ProductCreate,
    ResourceCreate,
    StatusConfigCreate,
)

api = APIRouter(prefix="/api/v1")
api.include_router(auth.router, prefix="/auth", tags=["auth"])
api.include_router(users.router, prefix="/users", tags=["users"])
api.include_router(projects.router, prefix="/projects", tags=["projects"])
api.include_router(dashboards.router, prefix="/projects", tags=["dashboards"])
api.include_router(builder.router, tags=["dashboard-builder"])
api.include_router(plan.router, prefix="/projects", tags=["plan"])
api.include_router(pending.router, prefix="/projects", tags=["pending"])
api.include_router(records.router, prefix="/projects", tags=["records"])
api.include_router(project_data.router, prefix="/projects", tags=["project-data"])
api.include_router(lifecycle.router, prefix="/projects", tags=["lifecycle"])
api.include_router(workspace.router, prefix="/projects", tags=["workspace"])
api.include_router(flex_values.router, prefix="/custom-field-values", tags=["custom-fields"])
api.include_router(imports.router, prefix="/imports", tags=["excel-intelligence"])
api.include_router(imports.templates_router, prefix="/import-templates", tags=["excel-intelligence"])
api.include_router(platform.audit_router, prefix="/audit-logs", tags=["audit"])
api.include_router(platform.custom_fields_router, prefix="/custom-fields", tags=["custom-fields"])

_master = dict(read_perm="master:read", write_perm="master:write")
for path, model, schema, entity, search in [
    ("customers", Customer, CustomerCreate, "customer", ["code", "name"]),
    ("products", Product, ProductCreate, "product", ["code", "name"]),
    ("departments", Department, DepartmentCreate, "department", ["code", "name"]),
    ("locations", Location, LocationCreate, "location", ["code", "name", "country"]),
    ("resources", Resource, ResourceCreate, "resource", ["full_name", "email"]),
    ("status-configs", StatusConfig, StatusConfigCreate, "status_config", ["code", "label", "entity_type"]),
]:
    api.include_router(
        build_crud(model, schema, entity=entity, search_fields=search, **_master),
        prefix=f"/{path}",
        tags=["master-data"],
    )
