"""Values of the flex fields (5 dropdown + 5 date + 5 text per entity) for a concrete record."""
import uuid
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.deps import ensure_project_access, get_db, require
from app.models import CustomFieldDefinition, CustomFieldValue, Project, User
from app.modules.excel_intel.profiler import parse_date

router = APIRouter()
# every record type people can edit can carry flex fields (5 dropdown + 5 date + 5 text each, options per customer)
ENTITY_LABELS = {
    "work_item": "Plan tasks and milestones", "dependency_item": "Pending items", "delivery_item": "Delivery items", "brd_requirement": "Requirements (BRD)",
    "helpdesk_item": "Helpdesk and operations", "gap_specification": "Gaps and specifications", "discussion_item": "Open discussions", "scope_decision": "Out of scope",
    "action_item": "Actions", "approval_gate": "Sign-off gates", "coverage_activity": "Coverage activities", "week_plan_item": "Week plan activities",
    "uat_scenario": "UAT scenarios", "uat_defect": "UAT defects", "integration_item": "Integrations", "report_item": "Reports + prints",
}


def entity_model(entity_type: str):
    if entity_type not in ENTITY_LABELS:
        return None
    from app.api.lifecycle import MANAGED  # noqa: PLC0415  (imported late: lifecycle imports the record registry)

    spec = MANAGED.get(entity_type)
    return spec.model if spec else None


def _record(db: Session, user: User, entity_type: str, entity_id: uuid.UUID) -> Project:
    model = entity_model(entity_type)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Flex fields are not available for '{entity_type}'")
    obj = db.get(model, entity_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found")
    ensure_project_access(db, user, obj.project_id)  # 404 if the user may not see the project
    return db.get(Project, obj.project_id)


def _definitions(db: Session, project: Project, entity_type: str) -> list[CustomFieldDefinition]:
    """Global fields plus the customer's own fields."""
    return list(db.scalars(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.entity_type == entity_type,
            or_(CustomFieldDefinition.customer_id.is_(None), CustomFieldDefinition.customer_id == project.customer_id),
        ).order_by(CustomFieldDefinition.field_type, CustomFieldDefinition.slot)
    ))


@router.get("/{entity_type}/{entity_id}")
def get_values(entity_type: str, entity_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    project = _record(db, user, entity_type, entity_id)
    vals = {v.definition_id: v for v in db.scalars(select(CustomFieldValue).where(CustomFieldValue.entity_type == entity_type, CustomFieldValue.entity_id == entity_id))}
    out = []
    for d in _definitions(db, project, entity_type):
        v = vals.get(d.id)
        value = None if v is None else (v.value_date.isoformat() if d.field_type == "date" and v.value_date else v.value_text)
        out.append({"definition_id": d.id, "label": d.label, "field_type": d.field_type, "slot": d.slot, "options": d.options,
                    "is_required": d.is_required, "value": value})
    return out


class ValueItem(BaseModel):
    definition_id: uuid.UUID
    value: Optional[str] = None  # None or "" clears


class ValuesBody(BaseModel):
    values: list[ValueItem]


@router.put("/{entity_type}/{entity_id}")
def put_values(entity_type: str, entity_id: uuid.UUID, body: ValuesBody, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project = _record(db, user, entity_type, entity_id)
    defs = {d.id: d for d in _definitions(db, project, entity_type)}
    existing = {v.definition_id: v for v in db.scalars(select(CustomFieldValue).where(CustomFieldValue.entity_type == entity_type, CustomFieldValue.entity_id == entity_id))}
    changes: dict[str, Any] = {}
    for it in body.values:
        d = defs.get(it.definition_id)
        if d is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown flex field for this record")
        raw = (it.value or "").strip()
        if raw == "":
            if d.is_required:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"'{d.label}' is required")
            if it.definition_id in existing:
                db.delete(existing[it.definition_id])
                changes[d.label] = None
            continue
        vtext: str | None = raw
        vdate: date | None = None
        if d.field_type == "dropdown" and raw not in (d.options or []):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"'{raw}' is not an option for '{d.label}'")
        if d.field_type == "date":
            vdate = parse_date(raw)
            if vdate is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"'{d.label}' needs a valid date")
            vtext = None
        row = existing.get(it.definition_id)
        if row is None:
            db.add(CustomFieldValue(definition_id=d.id, entity_type=entity_type, entity_id=entity_id, value_text=vtext, value_date=vdate))
        else:
            row.value_text, row.value_date = vtext, vdate
        changes[d.label] = raw
    write_audit(db, user, "update", "flex_values", entity_id, after={"entity_type": entity_type, "values": changes})
    db.commit()
    return {"ok": True}
