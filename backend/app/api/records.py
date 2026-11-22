"""Project records beyond the plan: delivery items, requirements (BRD), helpdesk items, gap specifications, discussions,
out-of-scope decisions, and the links between them. One registry drives list / facets / detail / create / edit / delete / revisions."""
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import Uuid, func, inspect, or_, select
from sqlalchemy.orm import Session

from app.api.plan import RevisionIn, _apply_status_generic, create_revision, project_or_404, revisions_out
from app.core.audit import row_to_dict, write_audit
from app.core.lifecycle import move
from app.db.base import utcnow
from app.core.deps import get_db, require
from app.models import Department, Location, Product, Project, StatusConfig, User
from app.models.workspace import ActionItem, CoverageActivity, IntegrationItem, ReportItem, UatDefect, UatScenario, WeekPlanItem
from app.modules.dashboards.trackers import DEFECT_OPEN, UAT_NOT_DONE
from app.modules.planning.gates import gate_closed, gate_days_late, gate_overdue
from app.models.canonical import (
    ApprovalGate, BrdRequirement, DateRevision, DeliveryItem, DiscussionItem, GapSpecification, HelpdeskItem, RequirementLink, ScopeDecision, WorkItem,
)
from app.modules.delivery.lifecycle import delivery_extras
from app.modules.excel_intel.committer import derive_delivery_target
from app.modules.excel_intel.profiler import parse_date
from app.modules.planning.delays import assess

router = APIRouter()
HIDE = {"raw_values", "match_key"}


@dataclass
class Spec:
    slug: str
    type_name: str  # used by links and audit
    model: Any
    title: Callable[[Any], str]
    search: list[str]
    filters: list[str]
    fields: dict[str, str]  # editable field -> type: str | text | date | int | bool | uuid | choice:a|b
    required_on_create: list[str]
    order: list[str]
    status_entity: str | None = None  # a 'status' field is accepted and stored as status_raw + status_category
    revision: tuple[str, str, str] | None = None  # (revision field name, baseline column, revised column)
    extras: Callable[[Any, date, int], dict] | None = None
    approval_field: str | None = None  # setting it to approved/rejected needs plan:approve


def _t(*parts: Any, n: int = 90) -> str:
    return " ".join(str(p) for p in parts if p)[:n]


def _gap_extras(g: GapSpecification, as_of: date, grace: int) -> dict:
    closed = bool(g.signoff_date) or (g.approval_status or "").lower().startswith("approved")
    a = assess(None, g.target_date, None, g.revised_target_date, "done" if closed else None, None, None, as_of, grace)
    return {"is_closed": closed, "is_overdue": a.overdue, "days_late": a.days_late, "slippage_days": a.slippage_days,
            "effective_target_date": a.effective_finish.isoformat() if a.effective_finish else None}


def _target_extras(o: Any, as_of: date, grace: int) -> dict:
    closed = o.status_category in ("done", "cancelled") if hasattr(o, "status_category") else False
    base = getattr(o, "target_date", None)
    a = assess(None, base, None, getattr(o, "revised_target_date", None), "done" if closed else None, None, None, as_of, grace)
    return {"is_closed": closed, "is_overdue": a.overdue, "days_late": a.days_late, "effective_target_date": a.effective_finish.isoformat() if a.effective_finish else None}


def _brd_extras(o: BrdRequirement, as_of: date, grace: int) -> dict:
    closed = (o.brd_status or "").strip().lower() in ("closed", "completed", "done")
    a = assess(None, o.target_date, None, o.revised_target_date, "done" if closed else None, None, None, as_of, grace)
    return {"is_closed": closed, "is_overdue": a.overdue, "days_late": a.days_late, "slippage_days": a.slippage_days,
            "effective_target_date": a.effective_finish.isoformat() if a.effective_finish else None}


def _discussion_extras(o: DiscussionItem, as_of: date, grace: int) -> dict:
    late = o.status == "open" and o.target_date is not None and o.target_date < as_of
    return {"is_closed": o.status == "closed", "is_overdue": late, "days_late": (as_of - o.target_date).days if late else 0}


def _action_extras(o: ActionItem, as_of: date, grace: int) -> dict:
    open_ = o.status != "resolved"
    late = open_ and o.due_date is not None and o.due_date < as_of
    return {"is_closed": not open_, "is_overdue": late, "days_late": (as_of - o.due_date).days if late else 0}


def _gate_extras(g: ApprovalGate, as_of: date, grace: int) -> dict:
    return {"is_closed": gate_closed(g), "is_overdue": gate_overdue(g, as_of, grace), "days_late": gate_days_late(g, as_of, grace)}


def _coverage_extras(o: CoverageActivity, as_of: date, grace: int) -> dict:
    return {"pct": round(o.completed_count / o.planned_count * 100, 1) if o.planned_count else None, "is_closed": o.planned_count > 0 and o.completed_count >= o.planned_count}


def _week_extras(o: WeekPlanItem, as_of: date, grace: int) -> dict:
    late = o.status != "done" and o.target_date is not None and o.target_date + timedelta(days=grace) < as_of
    return {"is_closed": o.status == "done", "is_overdue": late, "days_late": (as_of - o.target_date).days - grace if late else 0,
            "week_end": (o.week_start + timedelta(days=6)).isoformat()}




def _uat_extras(o: UatScenario, as_of: date, grace: int) -> dict:
    late = o.result in UAT_NOT_DONE and o.planned_date is not None and o.planned_date + timedelta(days=grace) < as_of
    return {"is_closed": o.result == "passed", "is_overdue": late, "days_late": (as_of - o.planned_date).days - grace if late else 0}


def _defect_extras(o: UatDefect, as_of: date, grace: int) -> dict:
    late = o.status in DEFECT_OPEN and o.target_date is not None and o.target_date + timedelta(days=grace) < as_of
    return {"is_closed": o.status in ("closed", "rejected"), "is_overdue": late, "days_late": (as_of - o.target_date).days - grace if late else 0,
            "age_days": (as_of - o.raised_on).days if o.raised_on and o.status in DEFECT_OPEN else None}


def _deliverable_extras(o: Any, as_of: date, grace: int) -> dict:
    closed = o.status_category in ("done", "cancelled") or o.actual_date is not None
    a = assess(None, o.target_date, None, o.revised_target_date, "done" if closed else None, None, o.actual_date, as_of, grace)
    return {"is_closed": closed, "is_overdue": a.overdue, "days_late": a.days_late, "slippage_days": a.slippage_days,
            "effective_target_date": a.effective_finish.isoformat() if a.effective_finish else None}


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


SPECS: dict[str, Spec] = {s.slug: s for s in [
    Spec("delivery-items", "delivery_item", DeliveryItem, lambda o: _t(o.external_id, o.description),
         ["description", "external_id", "module", "tracker_ref"],
         ["stream", "module", "status_category", "helpdesk_status_category", "priority", "customer_discussion_status", "functional_owner", "tech_owner", "qa_owner"],
         {"external_id": "str", "stream": "str", "module": "str", "description": "text", "priority": "str", "product_id": "uuid", "functional_owner": "str",
          "product_owner": "str", "tech_owner": "str", "qa_owner": "str", "specs_responsibility": "str", "testing_responsibility": "str",
          "customer_discussion_status": "str", "functional_specs_status": "str", "spec_closure_date": "date", "spec_closure_actual": "date",
          "dev_initiation": "date", "dev_completion": "date", "qa_release": "date", "uat_release": "date", "customer_release": "date",
          "customer_uat_closure": "date", "actual_completion": "date", "dev_remarks": "text", "meeting_remarks": "text", "pd_remarks": "text", "remarks": "text"},
         ["description"], ["sort_order"], "delivery_item", ("delivery_target_date", "delivery_target_date", "revised_target_date"), delivery_extras),
    Spec("requirements", "brd_requirement", BrdRequirement, lambda o: _t("BRD", o.brd_serial or o.sr_no, o.description),
         ["description", "brd_serial", "module", "remarks"], ["module", "brd_status", "covered_in_proto", "development_phase", "responsibility"],
         {"sr_no": "str", "brd_serial": "str", "description": "text", "module": "str", "brd_status": "str", "development_phase": "str", "covered_in_proto": "str",
          "responsibility": "str", "req_type": "str", "remarks": "text"},
         ["description"], ["sort_order"], None, ("target_date", "target_date", "revised_target_date"), _brd_extras),
    Spec("helpdesk-items", "helpdesk_item", HelpdeskItem, lambda o: _t(o.external_id, o.description),
         ["description", "external_id", "tracker_ref"], ["kind", "category", "status_category", "responsibility", "division"],
         {"external_id": "str", "category": "str", "description": "text", "responsibility": "str", "target_date": "date", "remarks": "text",
          "request_from": "str", "division": "str", "request_date": "date"},
         ["description"], ["sort_order"], "helpdesk_item", None, _target_extras),
    Spec("gap-specifications", "gap_specification", GapSpecification, lambda o: _t(o.external_issue_id, o.description),
         ["description", "external_issue_id", "module", "wfx_solution"], ["event", "team", "module", "priority", "category", "spec_status", "responsibility", "approval_status"],
         {"external_issue_id": "str", "event": "str", "team": "str", "module": "str", "development_scope": "str", "description": "text", "priority": "str",
          "category": "str", "wfx_solution": "text", "spec_status": "str", "remarks": "text", "responsibility": "str", "actual_date": "date",
          "submission_date": "date", "signoff_date": "date", "approval_status": "str"},
         ["description"], ["sort_order"], None, ("target_date", "target_date", "revised_target_date"), _gap_extras),
    Spec("discussions", "discussion_item", DiscussionItem, lambda o: _t(o.name),
         ["name", "concern", "module", "remarks"], ["item_type", "module", "status", "responsibility", "functionality_status"],
         {"name": "text", "concern": "text", "responsibility": "str", "target_date": "date", "status": "choice:open|decided|closed", "final_decision": "text",
          "meeting_remarks": "text", "remarks": "text", "module": "str", "item_type": "str", "functionality_status": "str", "product_id": "uuid"},
         ["name"], ["sort_order"], None, None, _discussion_extras),
    Spec("action-items", "action_item", ActionItem, lambda o: _t(o.title),
         ["title", "description", "owner_name", "last_action"], ["status", "priority", "owner_name", "product_id"],
         {"title": "str", "description": "text", "owner_name": "str", "priority": "choice:low|medium|high|critical", "due_date": "date",
          "status": "choice:open|in_progress", "product_id": "uuid", "linked_work_item_id": "uuid", "source_type": "str", "source_id": "uuid"},
         ["title"], ["due_date", "sort_order"], None, None, _action_extras),
    Spec("approval-gates", "approval_gate", ApprovalGate, lambda o: _t(o.name),
         ["name", "approver_name", "comments", "gate_type"], ["gate_type", "approval_status", "approver_name"],
         {"name": "str", "gate_type": "str", "product_id": "uuid", "approver_name": "str", "planned_date": "date", "submission_date": "date",
          "signoff_date": "date", "comments": "text"},
         ["name"], ["sort_order"], None, None, _gate_extras),
    Spec("coverage-activities", "coverage_activity", CoverageActivity, lambda o: _t(o.title),
         ["title", "responsible_name", "remarks"], ["department_id", "location_id", "responsible_name"],
         {"title": "str", "department_id": "uuid", "location_id": "uuid", "product_id": "uuid", "responsible_name": "str",
          "planned_count": "int:0", "completed_count": "int:0", "remarks": "text"},
         ["title", "department_id", "location_id"], ["sort_order"], None, None, _coverage_extras),
    Spec("week-plan-items", "week_plan_item", WeekPlanItem, lambda o: _t(o.title),
         ["title", "owner_name", "module", "remarks", "workstream"], ["workstream", "owner_name", "status", "module"],
         {"title": "str", "workstream": "str", "owner_name": "str", "product_id": "uuid", "module": "str", "target_date": "date", "week_start": "date",
          "percent_complete": "int:0:100", "status": "choice:planned|in_progress|done", "remarks": "text", "source_type": "str", "source_id": "uuid"},
         ["title"], ["week_start", "target_date", "sort_order"], None, None, _week_extras),
    Spec("uat-scenarios", "uat_scenario", UatScenario, lambda o: _t(o.scenario_id, o.title),
         ["title", "scenario_id", "module", "tester", "expected_result"], ["module", "result", "tester", "cycle"],
         {"scenario_id": "str", "title": "text", "module": "str", "functionality": "str", "scenario_type": "str", "source_ref": "str", "linked_cases": "text", "uat_role": "str", "product_id": "uuid", "business_objective": "text", "pre_condition": "text", "test_data": "text", "steps": "text",
          "expected_result": "text", "tester": "str", "cycle": "str", "planned_date": "date", "executed_date": "date",
          "result": "choice:not_run|in_progress|passed|failed|blocked|retest", "actual_result": "text", "defect_ref": "str", "remarks": "text"},
         ["title"], ["scenario_id", "sort_order"], None, None, _uat_extras),
    Spec("uat-defects", "uat_defect", UatDefect, lambda o: _t(o.defect_ref, o.title),
         ["title", "defect_ref", "description", "owner_name"], ["severity", "status", "owner_name"],
         {"defect_ref": "str", "title": "text", "description": "text", "scenario_id": "uuid", "product_id": "uuid", "severity": "choice:low|medium|high|critical",
          "status": "choice:open|in_fix|retest|closed|rejected", "raised_on": "date", "raised_by": "str", "owner_name": "str", "target_date": "date", "closed_on": "date",
          "resolution": "text", "remarks": "text"},
         ["title"], ["raised_on", "sort_order"], None, None, _defect_extras),
    Spec("integration-items", "integration_item", IntegrationItem, lambda o: _t(o.name, o.partner),
         ["name", "partner", "system", "message_type", "owner_name"], ["status_category", "direction", "technology", "partner", "region", "owner_name"],
         {"name": "str", "company": "str", "process": "str", "documented": "str", "wfx_status": "str", "partner": "str", "system": "str", "direction": "choice:inbound|outbound|bidirectional", "technology": "str", "message_type": "str", "business_domain": "str",
          "region": "str", "endpoint": "text", "owner_name": "str", "product_id": "uuid", "actual_date": "date", "uat_status": "str", "remarks": "text"},
         ["name"], ["sort_order"], "integration_item", ("target_date", "target_date", "revised_target_date"), _deliverable_extras),
    Spec("report-items", "report_item", ReportItem, lambda o: _t(o.name),
         ["name", "folder", "sub_folder", "module", "owner_name"], ["status_category", "report_type", "module", "folder", "complexity", "owner_name"],
         {"name": "str", "report_type": "str", "module": "str", "folder": "str", "sub_folder": "str", "complexity": "choice:low|medium|high", "reports_count": "int:0",
          "owner_name": "str", "product_id": "uuid", "actual_date": "date", "uat_status": "str", "remarks": "text"},
         ["name"], ["sort_order"], "report_item", ("target_date", "target_date", "revised_target_date"), _deliverable_extras),
    Spec("scope-decisions", "scope_decision", ScopeDecision, lambda o: _t(o.customer_feedback),
         ["customer_feedback", "original_scope", "new_requirement"], ["approval_status", "decision_owner"],
         {"customer_feedback": "text", "original_scope": "text", "new_requirement": "text", "reason": "text", "approval_status": "choice:pending|approved|rejected",
          "decision_owner": "str", "decision_date": "date", "remarks": "text"},
         ["customer_feedback"], ["sort_order"], None, None, None, "approval_status"),
]}
BY_TYPE = {s.type_name: s for s in SPECS.values()}


def spec_or_404(kind: str) -> Spec:
    s = SPECS.get(kind)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown record type")
    return s


def _row(o: Any) -> dict:
    return jsonable_encoder({c.key: getattr(o, c.key) for c in inspect(o).mapper.column_attrs if c.key not in HIDE})


def _out(spec: Spec, o: Any, as_of: date, grace: int) -> dict:
    d = _row(o)
    d["title"] = spec.title(o)
    if spec.extras:
        d.update(jsonable_encoder(spec.extras(o, as_of, grace)))
    return d


def _get(db: Session, spec: Spec, pid: uuid.UUID, rid: uuid.UUID, state: str = "active") -> Any:
    o = db.get(spec.model, rid, execution_options={"lifecycle": state})
    if o is None or o.project_id != pid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found")
    return o


def _coerce(db: Session, spec: Spec, name: str, typ: str, value: Any) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    col = getattr(spec.model, name).property.columns[0]
    if typ in ("str", "text"):
        v = str(value).strip()
        limit = getattr(col.type, "length", None)
        if limit and len(v) > limit:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{name} is longer than {limit} characters")
        return v
    if typ == "date":
        d = parse_date(str(value))
        if d is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{name} needs a valid date (YYYY-MM-DD)")
        return d
    if typ == "uuid":
        try:
            u = uuid.UUID(str(value))
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{name} is not a valid id")
        for field, model, label in (("product_id", Product, "product"), ("department_id", Department, "department"), ("location_id", Location, "location")):
            if name == field and db.get(model, u) is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown {label}")
        return u
    if typ.startswith("int"):
        parts = typ.split(":")
        lo = int(parts[1]) if len(parts) > 1 else None
        hi = int(parts[2]) if len(parts) > 2 else None
        try:
            n = int(str(value).strip())
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{name} must be a whole number")
        if (lo is not None and n < lo) or (hi is not None and n > hi):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{name} must be between {lo} and {hi}" if hi is not None else f"{name} must be at least {lo}")
        return n
    if typ.startswith("choice:"):
        opts = typ[7:].split("|")
        if value not in opts:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{name} must be one of {', '.join(opts)}")
        return value
    return value


def _gate_rules(db: Session, o: ApprovalGate, code: str | None, was_closed: bool, old_signoff: date | None, user: User) -> None:
    """Sign-off rules. Approving needs plan:approve, a submission date and an approval date; a blocked state needs a reason in Comments."""
    if o.submission_date and o.signoff_date and o.signoff_date < o.submission_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The approval date is before the submission date")
    if old_signoff != o.signoff_date and was_closed and "plan:approve" not in user.permission_codes:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: plan:approve (changing the date of an approved gate)")
    if not code:
        return
    sc = db.scalar(select(StatusConfig).where(StatusConfig.entity_type == "approval_gate", StatusConfig.code == code))
    if sc is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown approval state '{code}'")
    if sc.category == "done":
        if "plan:approve" not in user.permission_codes:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: plan:approve (approving a gate)")
        if not o.submission_date:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Record the submission date before approving")
        if not o.signoff_date:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter the approval date; it is not assumed")
    else:
        if sc.category == "blocked" and not (o.comments or "").strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Say why in Comments before setting '{sc.label}'")
        if was_closed and "plan:approve" not in user.permission_codes:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: plan:approve (reopening an approved gate)")
        if was_closed:
            o.signoff_date = None  # reopened: the old approval stays in the audit log
    o.approval_status, o.approval_category = sc.label, sc.category


def _apply(db: Session, spec: Spec, o: Any, data: dict, user: User) -> None:
    gate_status = None
    if spec.type_name == "approval_gate":
        data = dict(data)
        gate_status = data.pop("status", None)
        was_closed, old_signoff = (gate_closed(o), o.signoff_date) if o.id and o.created_at else (False, None)
    if spec.type_name == "action_item":
        if "status" in data and o.status == "resolved":
            raise HTTPException(status.HTTP_409_CONFLICT, "This action is resolved: reopen it (with a reason) instead of changing its status")
        if data.get("status") == "open" and o.status == "escalated":
            data = {**data, "status": "in_progress"}  # an escalated action never silently drops back to open
    for k, v in data.items():
        if k == "status" and spec.status_entity:
            if v:
                _apply_status_generic(db, o, spec.status_entity, str(v))
            continue
        if k not in spec.fields:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"'{k}' cannot be edited here" + (
                "; change the delivery date with a date revision" if k in ("delivery_target_date", "target_date") else ""))
        new = _coerce(db, spec, k, spec.fields[k], v)
        if spec.approval_field == k and new in ("approved", "rejected") and getattr(o, k) != new and "plan:approve" not in user.permission_codes:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing permission: plan:approve (approving or rejecting a scope request)")
        setattr(o, k, new)
    if spec.type_name == "approval_gate":
        if not o.gate_type:
            o.gate_type = "manual"
        _gate_rules(db, o, gate_status, was_closed, old_signoff, user)
    if spec.type_name == "uat_scenario":
        if o.result in ("passed", "failed"):
            if not (o.tester or "").strip():
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Say who tested it (Tester) before marking the scenario {o.result.title()}")
            if o.executed_date is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter the date it was executed; it is not assumed")
            if o.executed_date > date.today():
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The executed date is in the future")
            if o.result == "failed" and not (o.actual_result or "").strip():
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Record the actual result (what went wrong) when a scenario fails")
        if o.result == "passed" and o.id:
            n = db.scalar(select(func.count()).select_from(UatDefect).where(UatDefect.scenario_id == o.id, UatDefect.status.in_(DEFECT_OPEN))) or 0
            if n:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{n} open defect(s) are linked to this scenario. Close them before marking it Passed")
    if spec.type_name == "uat_defect":
        sc = None
        if o.scenario_id:
            sc = db.get(UatScenario, o.scenario_id)
            if sc is None or sc.project_id != o.project_id:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That scenario does not belong to this project")
        if o.raised_on and o.closed_on and o.closed_on < o.raised_on:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The closed date is before the raised date")
        if o.status == "closed" and (o.closed_on is None or not (o.resolution or "").strip()):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "To close a defect enter the closed date and how it was resolved")
        if o.status == "rejected" and not (o.resolution or "").strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Say why the defect is rejected (Resolution)")
        if o.status != "closed" and o.closed_on is not None:
            o.closed_on = None  # reopened: the earlier close stays in the audit log
        if o.status in DEFECT_OPEN and sc is not None and sc.result == "passed":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Scenario '{sc.title[:60]}' is marked Passed. Mark it Failed or Retest before raising an open defect against it")
    if spec.type_name == "coverage_activity":
        o.planned_count = 1 if o.planned_count is None else o.planned_count
        o.completed_count = 0 if o.completed_count is None else o.completed_count
        if o.completed_count > o.planned_count:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Completed ({o.completed_count}) cannot be more than planned ({o.planned_count})")
    if spec.type_name == "week_plan_item":
        if o.week_start is None and o.target_date is not None:
            o.week_start = monday_of(o.target_date)
        if o.week_start is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pick the week (a Monday) or a target date")
        if o.week_start.weekday() != 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Weeks run Monday to Sunday: the week must start on a Monday")
        if o.target_date is not None and not (o.week_start <= o.target_date <= o.week_start + timedelta(days=6)):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The target date is outside that week. Use Move to change the week")
    if spec.type_name == "action_item":
        if o.linked_work_item_id:
            w = db.get(WorkItem, o.linked_work_item_id)
            if w is None or w.project_id != o.project_id:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Linked task does not belong to this project")
        o.last_action, o.last_action_by, o.last_action_at = "Edited: " + ", ".join(sorted(data)), user.email, utcnow()
    if spec.type_name == "scope_decision" and o.approval_status in ("approved", "rejected") and (not o.decision_owner or not o.decision_date):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Record who decided and on what date before approving or rejecting")


# ------------------------------------------------------------------ list / facets / detail
@router.get("/{project_id}/records/{kind}")
def list_records(project_id: uuid.UUID, kind: str, request: Request, q: str | None = None, overdue: bool | None = None, as_of: date | None = None,
                 state: str = Query("active", pattern="^(active|archived|deleted)$"),
                 page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
                 db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    spec = spec_or_404(kind)
    project = project_or_404(db, user, project_id)
    as_of, grace = as_of or date.today(), project.delay_grace_days or 0
    stmt = select(spec.model).where(spec.model.project_id == project_id).execution_options(lifecycle=state)
    if q:
        stmt = stmt.where(or_(*[getattr(spec.model, c).ilike(f"%{q}%") for c in spec.search]))
    for f in spec.filters:
        v = request.query_params.get(f)
        if v is not None and v != "":
            col = getattr(spec.model, f)
            if v != "__none__" and isinstance(col.property.columns[0].type, Uuid):
                try:
                    v = uuid.UUID(v)
                except ValueError:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{f} is not a valid id")
            stmt = stmt.where(col.is_(None) if v == "__none__" else col == v)
    order = [getattr(spec.model, c) for c in spec.order] + [spec.model.id]
    if overdue is not None and spec.extras:
        rows = [o for o in db.scalars(stmt.order_by(*order)) if bool(spec.extras(o, as_of, grace).get("is_overdue") or spec.extras(o, as_of, grace).get("is_start_delayed")) == overdue]
        total, page_rows = len(rows), rows[(page - 1) * size : page * size]
    else:
        total = db.scalar(select(func.count()).select_from(stmt.subquery()).execution_options(lifecycle=state)) or 0
        page_rows = db.scalars(stmt.order_by(*order).offset((page - 1) * size).limit(size)).all()
    return {"items": [_out(spec, o, as_of, grace) for o in page_rows], "total": total, "page": page, "size": size, "as_of": as_of.isoformat(), "grace_days": grace}


@router.get("/{project_id}/records/{kind}/facets")
def facets(project_id: uuid.UUID, kind: str, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    spec = spec_or_404(kind)
    project_or_404(db, user, project_id)
    out = {}
    for f in spec.filters:
        col = getattr(spec.model, f)
        rows = db.execute(select(col, func.count()).where(spec.model.project_id == project_id).group_by(col).order_by(func.count().desc()).limit(60)).all()
        out[f] = [{"value": v, "count": n} for v, n in rows]
    return out


def links_of(db: Session, spec: Spec, rid: uuid.UUID) -> list[dict]:
    rows = db.scalars(select(RequirementLink).where(
        or_((RequirementLink.source_type == spec.type_name) & (RequirementLink.source_id == rid),
            (RequirementLink.target_type == spec.type_name) & (RequirementLink.target_id == rid)))).all()
    out = []
    for l in rows:
        other_type, other_id = (l.target_type, l.target_id) if l.source_id == rid and l.source_type == spec.type_name else (l.source_type, l.source_id)
        other_spec = BY_TYPE.get(other_type)
        o = db.get(other_spec.model, other_id) if other_spec else None
        if other_spec and o is None:
            continue  # archived or in the trash: the link is kept (restorable) but not shown
        out.append({"id": l.id, "link_type": l.link_type, "basis": l.basis, "direction": "out" if other_id == l.target_id else "in", "kind": other_spec.slug if other_spec else other_type,
                    "type": other_type, "record_id": other_id, "title": other_spec.title(o) if o is not None else "(deleted)"})
    return out


@router.get("/{project_id}/records/{kind}/{rid}")
def get_record(project_id: uuid.UUID, kind: str, rid: uuid.UUID, as_of: date | None = None, state: str = Query("active", pattern="^(active|archived|deleted)$"), db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    spec = spec_or_404(kind)
    project = project_or_404(db, user, project_id)
    o = _get(db, spec, project_id, rid, state)
    out = _out(spec, o, as_of or date.today(), project.delay_grace_days or 0)
    out["links"] = links_of(db, spec, rid)
    if spec.revision:
        out["revisions"] = revisions_out(db, spec.type_name, rid)
    return out


# ------------------------------------------------------------------ create / edit / delete / revise
@router.post("/{project_id}/records/{kind}", status_code=status.HTTP_201_CREATED)
def create_record(project_id: uuid.UUID, kind: str, body: dict, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    spec = spec_or_404(kind)
    project = project_or_404(db, user, project_id)
    missing = [f for f in spec.required_on_create if not str(body.get(f) or "").strip()]
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Required: {', '.join(missing)}")
    last = db.scalar(select(func.max(spec.model.sort_order)).where(spec.model.project_id == project_id)) or 0
    base: dict[str, Any] = {"project_id": project_id, "match_key": "", "sort_order": last + 1}
    if spec.type_name == "helpdesk_item":
        base["kind"] = "open_point"
    o = spec.model(**base)
    body = dict(body)
    if spec.revision and spec.revision[1] in body:  # the baseline date can be set when the record is created; afterwards only a revision moves it
        setattr(o, spec.revision[1], _coerce(db, spec, spec.revision[1], "date", body.pop(spec.revision[1])))
    if spec.type_name == "delivery_item":
        o.sources = ["manual"]
    _apply(db, spec, o, {k: v for k, v in body.items()}, user)
    if spec.type_name == "delivery_item":
        derive_delivery_target(o)
    db.add(o)
    db.flush()
    if spec.type_name == "action_item":
        o.last_action, o.last_action_by, o.last_action_at = "Created", user.email, utcnow()
    write_audit(db, user, "create", spec.type_name, o.id, after=row_to_dict(o))
    db.commit()
    return _out(spec, o, date.today(), project.delay_grace_days or 0)


@router.patch("/{project_id}/records/{kind}/{rid}")
def patch_record(project_id: uuid.UUID, kind: str, rid: uuid.UUID, body: dict, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    spec = spec_or_404(kind)
    project = project_or_404(db, user, project_id)
    o = _get(db, spec, project_id, rid)
    before = row_to_dict(o)
    try:
        _apply(db, spec, o, body, user)
    except HTTPException:
        db.rollback()
        raise
    write_audit(db, user, "update", spec.type_name, o.id, before=before, after=row_to_dict(o))
    db.commit()
    return _out(spec, o, date.today(), project.delay_grace_days or 0)


def delete_links_and_revisions(db: Session, rid: uuid.UUID) -> None:
    db.query(RequirementLink).filter((RequirementLink.source_id == rid) | (RequirementLink.target_id == rid)).delete(synchronize_session=False)
    db.query(DateRevision).filter(DateRevision.entity_id == rid).delete(synchronize_session=False)


@router.delete("/{project_id}/records/{kind}/{rid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_record(project_id: uuid.UUID, kind: str, rid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    spec = spec_or_404(kind)
    project_or_404(db, user, project_id)
    o = _get(db, spec, project_id, rid)
    move(db, user, spec.type_name, o, "delete")  # to the trash; links and revision history stay so it can be restored
    db.commit()


@router.post("/{project_id}/records/{kind}/{rid}/revisions", status_code=status.HTTP_201_CREATED)
def add_record_revision(project_id: uuid.UUID, kind: str, rid: uuid.UUID, body: RevisionIn, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    spec = spec_or_404(kind)
    if spec.revision is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "This record type has no revisable date")
    project = project_or_404(db, user, project_id)
    o = _get(db, spec, project_id, rid)
    body.field = spec.revision[0]
    create_revision(db, user, project, spec.type_name, o, body)
    db.commit()
    return revisions_out(db, spec.type_name, rid)


# ------------------------------------------------------------------ links (many-to-many)
class LinkIn(BaseModel):
    source_type: str
    source_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    link_type: str = Field("related", pattern="^(related|same_ticket|parent_child|brd_discussion)$")
    basis: str | None = Field(None, max_length=300)


def _make_link(db: Session, user: User, project_id: uuid.UUID, b: LinkIn) -> RequirementLink:
    for t, i in ((b.source_type, b.source_id), (b.target_type, b.target_id)):
        s = BY_TYPE.get(t)
        o = db.get(s.model, i) if s else None
        if o is None or o.project_id != project_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown {t} in this project")
    if (b.source_type, b.source_id) == (b.target_type, b.target_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A record cannot be linked to itself")
    exists = db.scalar(select(RequirementLink.id).where(
        or_((RequirementLink.source_type == b.source_type) & (RequirementLink.source_id == b.source_id) & (RequirementLink.target_type == b.target_type) & (RequirementLink.target_id == b.target_id),
            (RequirementLink.source_type == b.target_type) & (RequirementLink.source_id == b.target_id) & (RequirementLink.target_type == b.source_type) & (RequirementLink.target_id == b.source_id))))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "These records are already linked")
    l = RequirementLink(project_id=project_id, created_by=user.id, **b.model_dump())
    db.add(l)
    db.flush()
    write_audit(db, user, "create", "requirement_link", l.id, after=row_to_dict(l))
    return l


@router.post("/{project_id}/links", status_code=status.HTTP_201_CREATED)
def create_link(project_id: uuid.UUID, body: LinkIn, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project_or_404(db, user, project_id)
    l = _make_link(db, user, project_id, body)
    db.commit()
    return {"id": l.id}


@router.delete("/{project_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_link(project_id: uuid.UUID, link_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project_or_404(db, user, project_id)
    l = db.get(RequirementLink, link_id)
    if l is None or l.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    write_audit(db, user, "delete", "requirement_link", l.id, before=row_to_dict(l))
    db.delete(l)
    db.commit()


@router.get("/{project_id}/link-suggestions")
def link_suggestions(project_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require("projects:read"))):
    """Links the data itself supports, each with its evidence. Suggestions only: nothing is linked until a person confirms."""
    project_or_404(db, user, project_id)
    deliveries = db.scalars(select(DeliveryItem).where(DeliveryItem.project_id == project_id)).all()
    helpdesk = db.scalars(select(HelpdeskItem).where(HelpdeskItem.project_id == project_id)).all()
    reqs = db.scalars(select(BrdRequirement).where(BrdRequirement.project_id == project_id)).all()
    discs = db.scalars(select(DiscussionItem).where(DiscussionItem.project_id == project_id)).all()
    have = set()
    for l in db.scalars(select(RequirementLink).where(RequirementLink.project_id == project_id)):
        have.add((l.source_type, l.source_id, l.target_type, l.target_id))
        have.add((l.target_type, l.target_id, l.source_type, l.source_id))
    by_ext: dict[str, list[DeliveryItem]] = {}
    for d in deliveries:
        if d.external_id:
            by_ext.setdefault(d.external_id.strip(), []).append(d)
    out: list[dict] = []

    def add(rule, st, sid, tt, tid, lt, basis, src_title, tgt_title, ambiguous=False):
        if (st, sid, tt, tid) in have:
            return
        have.add((st, sid, tt, tid)); have.add((tt, tid, st, sid))
        out.append({"rule": rule, "source_type": st, "source_id": str(sid), "target_type": tt, "target_id": str(tid), "link_type": lt, "basis": basis,
                    "source_title": src_title, "target_title": tgt_title, "ambiguous": ambiguous})

    for h in helpdesk:  # same ticket number in the helpdesk list and the delivery list
        for d in by_ext.get((h.external_id or "").strip(), []):
            add("helpdesk_id", "helpdesk_item", h.id, "delivery_item", d.id, "same_ticket", f"helpdesk ID {h.external_id} = delivery ID {d.external_id}", _t(h.external_id, h.description, n=70), _t(d.external_id, d.description, n=70), len(by_ext[h.external_id.strip()]) > 1)
    for d in deliveries:  # "440679 : Party Configuration" is a child ticket of 440679
        if d.parent_external_id:
            parents = by_ext.get(d.parent_external_id, [])
            for p in parents[:1]:
                add("parent_ticket", "delivery_item", p.id, "delivery_item", d.id, "parent_child", f"description names parent ticket {d.parent_external_id}", _t(p.external_id, p.description, n=70), _t(d.external_id, d.description, n=70))
            for h in helpdesk:
                if (h.external_id or "").strip() == d.parent_external_id:
                    add("parent_ticket_helpdesk", "helpdesk_item", h.id, "delivery_item", d.id, "parent_child", f"helpdesk requirement {d.parent_external_id} generates this development ticket", _t(h.external_id, h.description, n=70), _t(d.external_id, d.description, n=70))
    serials: dict[str, list[BrdRequirement]] = {}
    for r in reqs:
        if r.brd_serial and r.brd_serial.strip().lower() not in ("not received", "na", "n/a", "none"):
            serials.setdefault(r.brd_serial.strip(), []).append(r)
    for dsc in discs:
        for r in serials.get((dsc.brd_serial or "").strip(), []):
            add("brd_serial", "brd_requirement", r.id, "discussion_item", dsc.id, "brd_discussion", f"BRD serial {dsc.brd_serial} appears on both", _t("BRD", r.brd_serial, r.description, n=70), _t(dsc.name, n=70), len(serials[dsc.brd_serial.strip()]) > 1)
    return {"suggestions": out, "unmatched": {"helpdesk_without_delivery": sum(1 for h in helpdesk if h.external_id and (h.external_id.strip() not in by_ext)),
                                              "discussions_without_requirement": sum(1 for x in discs if x.brd_serial and x.brd_serial.strip() not in serials)}}


class BulkLinks(BaseModel):
    links: list[LinkIn]


@router.post("/{project_id}/links/bulk")
def bulk_links(project_id: uuid.UUID, body: BulkLinks, db: Session = Depends(get_db), user: User = Depends(require("projects:write"))):
    project_or_404(db, user, project_id)
    created, skipped = 0, []
    for l in body.links:
        try:
            with db.begin_nested():
                _make_link(db, user, project_id, l)
            created += 1
        except HTTPException as e:
            skipped.append({"source_id": str(l.source_id), "target_id": str(l.target_id), "reason": e.detail})
    db.commit()
    return {"created": created, "skipped": skipped}
