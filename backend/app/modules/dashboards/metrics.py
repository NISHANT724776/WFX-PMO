"""Deterministic dashboard metrics. Every number comes from imported/entered records and a named formula; nothing is
typed in or estimated. A metric whose source data is missing is reported as unavailable, never as zero.

Formulas (named, shown on every dashboard):
  completion  = (Done + 1/2 * In Progress) / (plan tasks + tracker events)        [the status slides' legacy formula]
  phase state = done (all items closed) | overdue (any open item is overdue or start delayed) | in_progress (some work done /
                started) | upcoming (nothing started, no start date passed)
  gate state  = done (actual date) | overdue (planned + grace < as-of) | due (within 14 days) | planned
"""
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer, Product, Project, ProjectPhase, ProjectProduct
from app.models.canonical import (
    ApprovalGate, DateRevision, DeliveryItem, DependencyItem, GapSpecification, TrackerEvent, WorkItem, WorkItemDependency,
)
from app.modules.delivery.lifecycle import delivery_extras
from app.models import Department, Location
from app.models.workspace import ActionItem, CoverageActivity, IntegrationItem, ReportItem, UatDefect, UatScenario, WeekPlanItem
from app.modules.dashboards.trackers import UAT_NOT_DONE, defect_overdue, deliverable_state, scenario_overdue
from app.modules.planning.delays import assess
from app.modules.planning.gates import gate_closed, gate_overdue

GATE_RE = re.compile(r"sign[\s-]?off|approval|acceptance|go[\s-]?live", re.I)
DUE_SOON_DAYS = 14
FORMULA_COMPLETION = "(Done + ½ In Progress) ÷ (plan tasks + tracker events)"
GATE_RULE = "Gates = tracker events whose name contains Sign-off, Approval or Acceptance, plus Go-Live"


def is_gate_text(s: str | None) -> bool:
    return bool(s and GATE_RE.search(s))


def d_iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def rnd(x: float) -> int:
    return int(x + 0.5)


@dataclass
class Snapshot:
    project: Project
    customer: Customer | None
    products: dict[uuid.UUID, Product]
    go_live: dict[uuid.UUID, date | None]
    phases: dict[uuid.UUID, ProjectPhase]
    tasks: list[WorkItem]
    events: list[TrackerEvent]
    gates: list[ApprovalGate]
    gaps: list[GapSpecification]
    pending: list[DependencyItem]
    deps: list[WorkItemDependency]
    deliveries: list[DeliveryItem]
    proposed: list[DateRevision]
    as_of: date
    grace: int = 0
    actions: list[ActionItem] = field(default_factory=list)
    week_items: list[WeekPlanItem] = field(default_factory=list)
    uat: list[UatScenario] = field(default_factory=list)
    defects: list[UatDefect] = field(default_factory=list)
    integrations: list[IntegrationItem] = field(default_factory=list)
    reports: list[ReportItem] = field(default_factory=list)


def load(db: Session, project: Project, as_of: date) -> Snapshot:
    pid = project.id
    q = lambda m: list(db.scalars(select(m).where(m.project_id == pid)))  # noqa: E731
    pp = list(db.scalars(select(ProjectProduct).where(ProjectProduct.project_id == pid)))
    prods = {p.id: p for p in db.scalars(select(Product))}
    tasks = list(db.scalars(select(WorkItem).where(WorkItem.project_id == pid).order_by(WorkItem.sort_order)))
    live = {t.id for t in tasks}
    return Snapshot(
        project=project, customer=db.get(Customer, project.customer_id), products=prods,
        go_live={x.product_id: x.go_live_date for x in pp},
        phases={p.id: p for p in db.scalars(select(ProjectPhase).where(ProjectPhase.project_id == pid).order_by(ProjectPhase.sort_order))},
        tasks=tasks,
        events=list(db.scalars(select(TrackerEvent).where(TrackerEvent.project_id == pid).order_by(TrackerEvent.sort_order))),
        gates=q(ApprovalGate), gaps=q(GapSpecification), pending=q(DependencyItem), deps=[d for d in q(WorkItemDependency) if d.predecessor_id in live and d.successor_id in live], deliveries=q(DeliveryItem),
        proposed=list(db.scalars(select(DateRevision).where(DateRevision.project_id == pid, DateRevision.status == "proposed"))),
        as_of=as_of, grace=project.delay_grace_days or 0,
        actions=q(ActionItem), week_items=q(WeekPlanItem), uat=q(UatScenario), defects=q(UatDefect), integrations=q(IntegrationItem), reports=q(ReportItem),
    )


def gap_due(g: GapSpecification) -> date | None:
    return g.revised_target_date or g.target_date


def party(snap: Snapshot, value: str | None) -> str:
    """customer | wfx | joint | other | unassigned, from a responsibility text."""
    v = (value or "").strip().lower()
    if not v:
        return "unassigned"
    if v == "wfx":
        return "wfx"
    if v == "joint":
        return "joint"
    c = snap.customer
    if c and (v == c.name.lower() or v == c.code.lower() or c.name.lower() in v):
        return "customer"
    return "other"


# ------------------------------------------------------------------ item normalisation
def task_info(snap: Snapshot, w: WorkItem):
    return assess(w.planned_start, w.planned_finish, w.revised_start, w.revised_finish, w.status_category, w.actual_start, w.actual_finish, snap.as_of, snap.grace)


def task_item(snap: Snapshot, w: WorkItem) -> dict:
    a = task_info(snap, w)
    return {"type": "task", "id": str(w.id), "title": w.title, "phase_id": w.phase_id, "product_id": w.product_id, "kind": w.kind,
            "start": a.effective_start, "finish": a.effective_finish, "closed": a.closed, "overdue": a.overdue, "start_delayed": a.start_delayed,
            "days_late": a.days_late, "slippage": a.slippage_days, "in_progress": (w.status_category == "in_progress") and not a.closed,
            "started": w.actual_start is not None or w.status_category in ("in_progress", "done") or a.closed,
            "responsible": w.responsible_party, "owner": w.owner_name, "baseline_finish": w.planned_finish, "actual_finish": w.actual_finish,
            "status": w.status_raw, "revised_finish": w.revised_finish, "revised_start": w.revised_start, "baseline_start": w.planned_start}


def event_item(snap: Snapshot, e: TrackerEvent) -> dict:
    closed = e.actual_date is not None
    overdue = (not closed) and e.planned_date is not None and e.planned_date + timedelta(days=snap.grace) < snap.as_of
    return {"type": "event", "id": str(e.id), "title": e.event_name, "product_id": e.product_id, "start": e.planned_date, "finish": e.planned_date,
            "closed": closed, "overdue": overdue, "start_delayed": False, "in_progress": False, "started": closed, "slippage": 0,
            "days_late": (snap.as_of - e.planned_date).days - snap.grace if overdue else 0, "responsible": e.responsibility, "owner": e.spoc,
            "baseline_finish": e.planned_date, "actual_finish": e.actual_date, "status": "Done" if closed else ("Overdue" if overdue else "Open"),
            "revised_finish": None, "revised_start": None, "baseline_start": e.planned_date}


def completion(items: list[dict]) -> dict:
    n = len(items)
    done = sum(1 for i in items if i["closed"])
    ip = sum(1 for i in items if i["in_progress"] and not i["closed"])
    pct = (done + 0.5 * ip) / n * 100 if n else None
    return {"total": n, "done": done, "in_progress": ip, "pct": None if pct is None else round(pct, 1), "pct_display": None if pct is None else rnd(pct),
            "overdue": sum(1 for i in items if i["overdue"]), "start_delayed": sum(1 for i in items if i["start_delayed"])}


# ------------------------------------------------------------------ KPI drill-down: the SAME predicates produce the tile number and the list behind it
def _is_milestone(i: dict) -> bool:
    return i.get("kind") == "milestone" or is_gate_text(i["title"])


# metric -> (label, plain-language rule, predicate(item, snap))
ACTIVITY_METRICS: dict[str, tuple[str, str, Any]] = {
    "all": ("All activities", "Every plan task and tracker event in scope", lambda i, s: True),
    "completed": ("Completed activities", "Closed: status done, or an actual finish date", lambda i, s: i["closed"]),
    "in_progress": ("In-progress activities", "Work has started and the activity is not closed", lambda i, s: i["in_progress"] and not i["closed"]),
    "overdue": ("Overdue activities", "Not closed and the current finish date (+ grace days) has passed", lambda i, s: i["overdue"]),
    "start_delayed": ("Start delayed", "Not closed, not yet overdue, not started although the current start date (+ grace) has passed", lambda i, s: i["start_delayed"]),
    "not_started": ("Upcoming activities", "Not closed, not in progress, not overdue", lambda i, s: not i["closed"] and not i["in_progress"] and not i["overdue"]),
    "upcoming_milestones": ("Upcoming milestones", "Open milestones and sign-offs whose current date is on or after the report date",
                            lambda i, s: not i["closed"] and _is_milestone(i) and i["finish"] is not None and i["finish"] >= s.as_of),
}


def activity_items(snap: Snapshot, product_id: uuid.UUID | None = None) -> list[dict]:
    """Plan tasks + tracker events in scope. With a product: tasks tagged to it or project-wide, and its tracker events (as the product view does)."""
    if product_id is None:
        return [task_item(snap, w) for w in snap.tasks] + [event_item(snap, e) for e in snap.events]
    return [task_item(snap, w) for w in snap.tasks if w.product_id in (None, product_id)] + [event_item(snap, e) for e in snap.events if e.product_id == product_id]


def activity_kpis(snap: Snapshot, product_id: uuid.UUID | None = None) -> dict[str, int]:
    items = activity_items(snap, product_id)
    return {m: sum(1 for i in items if pred(i, snap)) for m, (_, _, pred) in ACTIVITY_METRICS.items()}


def drilldown_rows(snap: Snapshot, metric: str, product_id: uuid.UUID | None = None) -> list[dict]:
    pred = ACTIVITY_METRICS[metric][2]
    out = []
    for i in activity_items(snap, product_id):
        if not pred(i, snap):
            continue
        prod = snap.products.get(i["product_id"]) if i.get("product_id") else None
        ph = snap.phases.get(i["phase_id"]) if i.get("phase_id") else None
        out.append({"id": i["id"], "type": i["type"], "title": i["title"], "is_milestone": _is_milestone(i), "phase_id": i.get("phase_id"), "phase": ph.name if ph else None,
                    "product_id": i.get("product_id"), "product": prod.code if prod else None, "owner": i["owner"], "responsible": i["responsible"],
                    "original_finish": i["baseline_finish"], "revised_finish": i["revised_finish"], "current_finish": i["finish"], "actual_finish": i["actual_finish"],
                    "days_late": i["days_late"], "slippage_days": i["slippage"], "status": i["status"], "is_overdue": i["overdue"], "is_closed": i["closed"],
                    "editable": i["type"] == "task"})
    return out


def row_state(items: list[dict], snap: Snapshot) -> dict:
    """State of a phase / group of items, per the status slides' legend."""
    if not items:
        return {"state": "upcoming", "pct": 0, "start": None, "end": None, "late_items": 0, "n": 0, "done": 0}
    c = completion(items)
    starts = [i["start"] for i in items if i["start"]]
    ends = [i["finish"] for i in items if i["finish"]]
    start, end = (min(starts) if starts else None), (max(ends) if ends else None)
    all_done = c["done"] == c["total"]
    started = any(i["started"] for i in items)
    if all_done:
        state = "done"
    elif any(i["overdue"] or i["start_delayed"] for i in items):
        state = "overdue"  # any open item past its date, or not started although its start has passed
    elif started:
        state = "in_progress"
    else:
        state = "upcoming"
    return {"state": state, "pct": c["pct_display"] or 0, "start": start, "end": end, "late_items": c["overdue"] + c["start_delayed"], "n": c["total"], "done": c["done"]}


def row_out(label: str, area: str, items: list[dict], snap: Snapshot, extra: dict | None = None) -> dict:
    r = row_state(items, snap)
    stars = [{"date": d_iso(i["finish"]), "title": i["title"], "id": i["id"], "type": i["type"]} for i in items
             if i["finish"] and (i.get("kind") == "milestone" or is_gate_text(i["title"]))]
    return {"label": label, "area": area, "state": r["state"], "pct": r["pct"], "start": d_iso(r["start"]), "end": d_iso(r["end"]), "items": r["n"],
            "done": r["done"], "late_items": r["late_items"], "stars": stars[:12], "refs": [{"type": i["type"], "id": i["id"]} for i in items][:300], **(extra or {})}


def status_text(r: dict) -> str:
    return {"done": "100% Done", "upcoming": "Planned"}.get(r["state"]) or f"{r['pct']}% · {'Overdue' if r['state'] == 'overdue' else 'In-Progress'}"


def _meta(snap: Snapshot, kind: str, extra: dict | None = None) -> dict:
    return {"kind": kind, "project": {"id": str(snap.project.id), "code": snap.project.code, "name": snap.project.name,
                                       "customer": snap.customer.name if snap.customer else None, "go_live": d_iso(snap.project.target_go_live)},
            "as_of": snap.as_of.isoformat(), "grace_days": snap.grace, "generated_at": datetime.now(timezone.utc).isoformat(),
            "formulas": {"completion": FORMULA_COMPLETION, "gates": GATE_RULE,
                         "phase_state": "Done = all items closed · Overdue = any open item is past its date (+grace) or has not started although its start has passed · In progress = some work started · Planned = not started"},
            "sources": {"plan_tasks": len(snap.tasks), "tracker_events": len(snap.events), "approval_gates": len(snap.gates), "gap_specifications": len(snap.gaps), "pending_items": len(snap.pending), "delivery_items": len(snap.deliveries)},
            **(extra or {})}


# ------------------------------------------------------------------ A. overall project status
def overall(snap: Snapshot) -> dict:
    tasks = [task_item(snap, w) for w in snap.tasks]
    events = [event_item(snap, e) for e in snap.events]
    allitems = tasks + events
    rows: list[dict] = []
    by_phase: dict[uuid.UUID | None, list[dict]] = defaultdict(list)
    for t in tasks:
        by_phase[t["phase_id"]].append(t)
    for ph in snap.phases.values():
        items = by_phase.get(ph.id, [])
        prods = {i["product_id"] for i in items if i["product_id"]}
        area = "Project-wide" if not prods else (snap.products[next(iter(prods))].code if len(prods) == 1 else "Mixed")
        rows.append(row_out(ph.name, area, items, snap, {"kind": "phase", "phase_id": str(ph.id)}))
    if by_phase.get(None):
        rows.append(row_out("(no phase)", "Project-wide", by_phase[None], snap, {"kind": "phase", "phase_id": None}))
    ev_by_prod: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for e in events:
        ev_by_prod[e["product_id"]].append(e)
    for pid_, items in sorted(ev_by_prod.items(), key=lambda kv: snap.products[kv[0]].code):
        rows.append(row_out("Tracker milestones", snap.products[pid_].code, items, snap, {"kind": "events", "product_id": str(pid_)}))
    order = {"Project-wide": 0, "Mixed": 1}
    rows.sort(key=lambda r: (order.get(r["area"], 2), r["area"]))  # stable: keeps plan order inside an area
    states = Counter(r["state"] for r in rows)
    c = completion(allitems)
    refs = lambda st: [{"type": "row", "label": r["label"], "area": r["area"]} for r in rows if r["state"] == st]  # noqa: E731
    return {
        **_meta(snap, "overall"),
        "kpis": {"overall": {**c, "formula": FORMULA_COMPLETION, "numerator": c["done"] + 0.5 * c["in_progress"], "denominator": c["total"]},
                 "completed": {"value": states["done"], "label": "Completed phases", "refs": refs("done")},
                 "in_progress": {"value": states["in_progress"], "label": "In progress", "refs": refs("in_progress")},
                 "overdue": {"value": states["overdue"], "label": "Overdue phases", "refs": refs("overdue")},
                 "upcoming": {"value": states["upcoming"], "label": "Upcoming", "refs": refs("upcoming")},
                 "activities": {**activity_kpis(snap), "phases": len(rows)}},
        "rows": rows,
        "available": bool(rows),
        "notes": ["Phases come from the imported plan; tracker milestones are grouped per product. 'Area' is the product a phase was tagged with, or Project-wide."],
    }


# ------------------------------------------------------------------ B. product coverage and status
def gate_state(planned: date | None, actual: date | None, snap: Snapshot) -> str:
    if actual:
        return "done"
    if planned and planned + timedelta(days=snap.grace) < snap.as_of:
        return "overdue"
    if planned and planned <= snap.as_of + timedelta(days=DUE_SOON_DAYS):
        return "due"
    return "planned"


def product_view(snap: Snapshot, product_id: uuid.UUID) -> dict:
    prod = snap.products[product_id]
    scope_tasks = [w for w in snap.tasks if w.product_id in (None, product_id)]
    tasks = [task_item(snap, w) for w in scope_tasks]
    events = [event_item(snap, e) for e in snap.events if e.product_id == product_id]
    items = tasks + events
    c = completion(items)
    by_phase: dict[Any, list[dict]] = defaultdict(list)
    for t in tasks:
        by_phase[t["phase_id"]].append(t)
    rows = [row_out(ph.name, prod.code, by_phase[ph.id], snap, {"kind": "phase", "phase_id": str(ph.id)}) for ph in snap.phases.values() if by_phase.get(ph.id)]
    if events:
        rows.append(row_out("Tracker milestones", prod.code, events, snap, {"kind": "events", "product_id": str(product_id)}))
    # sign-off gate tracker
    gates = []
    for e in snap.events:
        if e.product_id == product_id and is_gate_text(e.event_name):
            gates.append({"type": "event", "id": str(e.id), "name": e.event_name, "planned": d_iso(e.planned_date), "actual": d_iso(e.actual_date),
                          "state": gate_state(e.planned_date, e.actual_date, snap), "owner": e.spoc, "responsibility": e.responsibility})
    go_live = snap.go_live.get(product_id) or snap.project.target_go_live
    if go_live:
        gates.append({"type": "go_live", "id": None, "name": "GO-LIVE", "planned": d_iso(go_live), "actual": None, "state": gate_state(go_live, None, snap), "owner": None, "responsibility": None})
    gates.sort(key=lambda g: (g["planned"] is None, g["planned"] or ""))
    upcoming = [g for g in gates if g["state"] in ("due", "planned") and g["planned"] and g["planned"] >= snap.as_of.isoformat() and g["type"] != "go_live"]
    next_gate = upcoming[0] if upcoming else None
    # department blueprint sign-off (approval gates that are not tied to another product)
    bp = [g for g in snap.gates if g.product_id in (None, product_id)]
    approvals = [{"id": str(g.id), "set": g.gate_type, "name": g.name, "planned": d_iso(g.planned_date), "submission": d_iso(g.submission_date),
                  "signoff": d_iso(g.signoff_date), "status": g.approval_status, "approver": g.approver_name, "state": ("done" if gate_closed(g) else gate_state(g.planned_date, None, snap) if g.planned_date else "planned")}
                 for g in bp]
    late_items = sum(1 for i in items if i["overdue"] or i["start_delayed"])
    return {
        **_meta(snap, "product", {"product": {"id": str(prod.id), "code": prod.code, "name": prod.name}}),
        "kpis": {"overall": {**c, "formula": FORMULA_COMPLETION, "numerator": c["done"] + 0.5 * c["in_progress"], "denominator": c["total"]},
                 "items": {"done": c["done"], "total": c["total"], "label": "Plan tasks + tracker events done"},
                 "late": {"value": late_items, "label": "Items overdue / start delayed", "refs": [{"type": i["type"], "id": i["id"], "title": i["title"]} for i in items if i["overdue"] or i["start_delayed"]][:200]},
                 "next_gate": next_gate, "go_live": d_iso(go_live)},
        "rows": rows, "gates": gates, "approvals": approvals,
        "approval_summary": {k: {"approved": sum(1 for a in approvals if a["set"] == k and a["state"] == "done"), "total": sum(1 for a in approvals if a["set"] == k)}
                             for k in sorted({a["set"] for a in approvals})},
        "needs_attention": needs_attention(snap, product_id, tasks, events, gates),
        "available": bool(items),
        "notes": ["Department × location coverage is on its own tab, calculated from the activities you add (the imported blueprint sheet has no location dimension)." if approvals else "No blueprint sign-off data imported."],
    }


def needs_attention(snap: Snapshot, product_id: uuid.UUID | None, tasks: list[dict], events: list[dict], gates: list[dict]) -> list[dict]:
    out: list[dict] = []
    for g in gates:
        if g["state"] == "overdue":
            late = (snap.as_of - date.fromisoformat(g["planned"])).days
            out.append({"severity": "high", "kind": "gate", "text": f"{g['name']} overdue since {date.fromisoformat(g['planned']).strftime('%d-%b-%y')} ({late} d)" + (f" · {g['owner']}" if g["owner"] else ""), "refs": [{"type": g["type"], "id": g["id"]}], "days": late})
    late_tasks = sorted([t for t in tasks if t["overdue"]], key=lambda t: -t["days_late"])
    for t in late_tasks[:5]:
        out.append({"severity": "high", "kind": "task", "text": f"{t['title']} — {t['days_late']} d late" + (f" ({t['responsible']})" if t["responsible"] else ""), "refs": [{"type": "task", "id": t["id"]}], "days": t["days_late"]})
    if len(late_tasks) > 5:
        out.append({"severity": "medium", "kind": "task", "text": f"{len(late_tasks) - 5} more plan items are overdue", "refs": [{"type": "task", "id": t["id"]} for t in late_tasks[5:30]], "days": 0})
    pend = [p for p in snap.pending if (product_id is None or p.product_id in (None, product_id))]
    for who, label in (("customer", "Customer"), ("wfx", "WFX"), ("external", "an external partner"), ("internal", "an internal team")):
        late = [p for p in pend if p.pending_with == who and not (p.status_category in ("done", "cancelled") or p.actual_closure_date)
                and (p.revised_target_date or p.original_target_date) and (p.revised_target_date or p.original_target_date) + timedelta(days=snap.grace) < snap.as_of]
        if late:
            old = min(late, key=lambda p: p.revised_target_date or p.original_target_date)
            od = old.revised_target_date or old.original_target_date
            out.append({"severity": "high" if who == "customer" else "medium", "kind": "pending", "text": f"{len(late)} item(s) pending with {label} are overdue; oldest: {old.description[:70]} (due {od.strftime('%d-%b-%y')})",
                        "refs": [{"type": "pending", "id": str(p.id)} for p in late][:50], "days": (snap.as_of - od).days})
    if snap.proposed:
        old = min(snap.proposed, key=lambda r: r.requested_at)
        out.append({"severity": "medium", "kind": "approval", "text": f"{len(snap.proposed)} date revision(s) await approval (oldest requested {old.requested_at.strftime('%d-%b-%y')})", "refs": [{"type": "revision", "id": str(r.id)} for r in snap.proposed][:50], "days": 0})
    specs = [g for g in snap.gaps if gap_due(g) and gap_due(g) + timedelta(days=snap.grace) < snap.as_of and not g.signoff_date and not (g.approval_status or "").lower().startswith("approved")]
    late_deliv = [(d, ex) for d in snap.deliveries for ex in [delivery_extras(d, snap.as_of, snap.grace)] if ex["is_overdue"]]
    if late_deliv:
        oldest = max(late_deliv, key=lambda t: t[1]["days_late"])
        out.append({"severity": "medium", "kind": "delivery", "text": f"{len(late_deliv)} development delivery item(s) are past their release date; longest: {oldest[0].external_id or ''} {oldest[0].description[:60]} ({oldest[1]['days_late']} d)",
                    "refs": [{"type": "delivery_item", "id": str(d.id)} for d, _ in late_deliv][:50], "days": oldest[1]["days_late"]})
    if specs:
        out.append({"severity": "medium", "kind": "spec", "text": f"{len(specs)} gap specification(s) are past their target date without sign-off", "refs": [{"type": "gap", "id": str(g.id)} for g in specs][:50], "days": 0})
    in_scope = lambda o: product_id is None or o.product_id in (None, product_id)  # noqa: E731
    late_uat = [u for u in snap.uat if in_scope(u) and scenario_overdue(u, snap.as_of, snap.grace)]
    if late_uat:
        out.append({"severity": "medium", "kind": "uat", "text": f"{len(late_uat)} UAT scenario(s) have not been run and are past their planned date", "refs": [{"type": "uat_scenario", "id": str(u.id)} for u in late_uat][:50],
                    "days": max((snap.as_of - u.planned_date).days for u in late_uat)})
    hot = [d for d in snap.defects if in_scope(d) and d.status in ("open", "in_fix", "retest") and d.severity in ("critical", "high")]
    if hot:
        out.append({"severity": "high", "kind": "defect", "text": f"{len(hot)} open critical / high UAT defect(s); oldest open {max(((snap.as_of - d.raised_on).days for d in hot if d.raised_on), default=0)} d",
                    "refs": [{"type": "uat_defect", "id": str(d.id)} for d in hot][:50], "days": max(((snap.as_of - d.raised_on).days for d in hot if d.raised_on), default=0)})
    for label, items, typ in (("integration(s)", snap.integrations, "integration_item"), ("report / print(s)", snap.reports, "report_item")):
        late = [o for o in items if in_scope(o) and deliverable_state(o, snap.as_of, snap.grace)[1].overdue]
        if late:
            worst = max(deliverable_state(o, snap.as_of, snap.grace)[1].days_late for o in late)
            out.append({"severity": "medium", "kind": "deliverable", "text": f"{len(late)} {label} are past their target date; longest {worst} d", "refs": [{"type": typ, "id": str(o.id)} for o in late][:50], "days": worst})
    blockers = defaultdict(int)
    late_ids = {t["id"] for t in late_tasks}
    for d in snap.deps:
        if str(d.predecessor_id) in late_ids:
            blockers[str(d.predecessor_id)] += 1
    for tid, n in sorted(blockers.items(), key=lambda kv: -kv[1])[:3]:
        t = next(x for x in late_tasks if x["id"] == tid)
        out.append({"severity": "high", "kind": "dependency", "text": f"{t['title']} is overdue and blocks {n} dependent task(s)", "refs": [{"type": "task", "id": tid}], "days": t["days_late"]})
    late_gates = [g for g in snap.gates if g.product_id in (None, product_id) and gate_overdue(g, snap.as_of, snap.grace)]
    if late_gates:
        oldest = min(late_gates, key=lambda g: g.planned_date)
        out.append({"severity": "high", "kind": "approval_gate", "text": f"{len(late_gates)} sign-off approval(s) overdue; oldest: {oldest.name[:70]} (planned {oldest.planned_date.strftime('%d-%b-%y')})" + (f" · {oldest.approver_name}" if oldest.approver_name else ""),
                    "refs": [{"type": "approval_gate", "id": str(g.id)} for g in late_gates][:50], "days": (snap.as_of - oldest.planned_date).days})
    # actions already raised: attach the open one to the item it came from; surface escalated or overdue ones that have no item of their own
    scoped = [a for a in snap.actions if a.status != "resolved" and a.product_id in (None, product_id)]
    by_source = {(a.source_type, str(a.source_id)): a for a in sorted(scoped, key=lambda a: a.created_at, reverse=True) if a.source_id}
    attached: set = set()
    for item in out:
        for r in item["refs"]:
            a = by_source.get((r["type"], str(r["id"])))
            if a:
                item["action"] = action_summary(a, snap)
                attached.add(a.id)
                break
        else:
            item["action"] = None
    for a in scoped:
        late = a.due_date is not None and a.due_date < snap.as_of
        if a.id in attached or not (a.status == "escalated" or late):
            continue
        out.append({"severity": "high" if a.status == "escalated" or a.priority in ("high", "critical") else "medium", "kind": "action",
                    "text": f"Action {'escalated' if a.status == 'escalated' else 'overdue'}: {a.title[:90]}" + (f" · {a.owner_name}" if a.owner_name else "") + (f" (due {a.due_date.strftime('%d-%b-%y')})" if a.due_date else ""),
                    "refs": [{"type": "action", "id": str(a.id)}], "days": (snap.as_of - a.due_date).days if late else 0, "action": action_summary(a, snap)})
    out.sort(key=lambda x: (x["severity"] != "high", -x["days"]))
    return out


def action_summary(a: ActionItem, snap: Snapshot) -> dict:
    late = a.status != "resolved" and a.due_date is not None and a.due_date < snap.as_of
    return {"id": str(a.id), "title": a.title, "owner": a.owner_name, "priority": a.priority, "status": a.status, "due": d_iso(a.due_date), "overdue": late,
            "last_action": a.last_action, "last_action_by": a.last_action_by, "last_action_at": a.last_action_at.isoformat() if a.last_action_at else None}


# ------------------------------------------------------------------ department x location coverage
def coverage(db: Session, project: Project, product_id: uuid.UUID | None = None, location_id: uuid.UUID | None = None) -> dict:
    """Coverage % = completed / planned, summed over the activities. Nothing here is typed in; a cell with nothing planned has no % (n/a)."""
    stmt = select(CoverageActivity).where(CoverageActivity.project_id == project.id)
    if product_id:
        stmt = stmt.where(CoverageActivity.product_id == product_id)
    if location_id:
        stmt = stmt.where(CoverageActivity.location_id == location_id)
    acts = list(db.scalars(stmt))
    depts = {d.id: d for d in db.scalars(select(Department))}
    locs = {l.id: l for l in db.scalars(select(Location))}

    def tot(rows: list) -> dict:
        p, c = sum(r.planned_count for r in rows), sum(r.completed_count for r in rows)
        return {"planned": p, "completed": c, "pct": round(c / p * 100, 1) if p else None, "activities": len(rows)}

    by_cell: dict = defaultdict(list)
    by_dept: dict = defaultdict(list)
    by_loc: dict = defaultdict(list)
    for a in acts:
        by_cell[(a.department_id, a.location_id)].append(a)
        by_dept[a.department_id].append(a)
        by_loc[a.location_id].append(a)
    dl = lambda m, k: {"id": str(k), "code": m[k].code, "name": m[k].name}  # noqa: E731
    return {
        "available": bool(acts),
        "formula": "Coverage % = completed ÷ planned, summed over the activities of the department / location. A cell with nothing planned shows n/a, not 0%.",
        "departments": sorted([{**dl(depts, k), **tot(v)} for k, v in by_dept.items()], key=lambda r: r["name"]),
        "locations": sorted([{**dl(locs, k), **tot(v)} for k, v in by_loc.items()], key=lambda r: (r["pct"] is None, -(r["pct"] or 0), r["name"])),
        "cells": [{"department_id": str(d), "location_id": str(l), **tot(v)} for (d, l), v in by_cell.items()],
        "total": tot(acts),
        "as_of": date.today().isoformat(),
    }


# ------------------------------------------------------------------ C. this / next week plan
def week_bounds(as_of: date, period: str) -> tuple[date, date, str]:
    monday = as_of - timedelta(days=as_of.weekday())
    if period == "this_week":
        s, e, lab = monday, monday + timedelta(days=6), "This week"
    elif period == "next_month":
        first = date(as_of.year + (as_of.month == 12), (as_of.month % 12) + 1, 1)
        nxt = date(first.year + (first.month == 12), (first.month % 12) + 1, 1)
        s, e, lab = first, nxt - timedelta(days=1), "Next month"
    else:
        s, e, lab = monday + timedelta(days=7), monday + timedelta(days=13), "Next week"
    return s, e, lab


def next_week(snap: Snapshot, period: str = "next_week", include_overdue: bool = True) -> dict:
    s, e, label = week_bounds(snap.as_of, period)
    groups: dict[str, list[dict]] = defaultdict(list)
    carry: dict[str, int] = Counter()
    pname = lambda pid: snap.products[pid].code if pid else "Project-wide"  # noqa: E731

    def add(group: str, card: dict, carry_over: bool = False) -> None:
        if carry_over:
            carry[group] += 1
            if sum(1 for c in groups[group] if c["tag"] == "carry_over") >= 5:
                return
        groups[group].append(card)

    for w in snap.tasks:
        t = task_item(snap, w)
        if t["closed"]:
            continue
        fin, st = t["finish"], t["start"]
        phase = snap.phases[w.phase_id].name if w.phase_id in snap.phases else None
        base = {"title": t["title"], "description": " · ".join(x for x in (phase, w.location_label, w.delivery_mode) if x), "owner": w.owner_name,
                "responsibility": w.responsible_party, "source": {"type": "task", "id": t["id"]}}
        grp = pname(w.product_id)
        if fin and s <= fin <= e:
            add(grp, {**base, "due": d_iso(fin), "tag": "due", "days_late": 0})
        elif st and s <= st <= e and not t["started"]:
            add(grp, {**base, "due": d_iso(st), "tag": "starts", "days_late": 0})
        elif include_overdue and t["overdue"]:
            add(grp, {**base, "due": d_iso(fin), "tag": "carry_over", "days_late": t["days_late"]}, True)
    for ev in snap.events:
        i = event_item(snap, ev)
        if i["closed"] or not ev.planned_date:
            continue
        base = {"title": ev.event_name, "description": f"Tracker milestone · {pname(ev.product_id)}", "owner": ev.spoc, "responsibility": ev.responsibility, "source": {"type": "event", "id": i["id"]}}
        if s <= ev.planned_date <= e:
            add(pname(ev.product_id), {**base, "due": d_iso(ev.planned_date), "tag": "due", "days_late": 0})
        elif include_overdue and i["overdue"] and is_gate_text(ev.event_name):
            add(pname(ev.product_id), {**base, "due": d_iso(ev.planned_date), "tag": "carry_over", "days_late": i["days_late"]}, True)
    for p in snap.pending:
        if p.status_category in ("done", "cancelled") or p.actual_closure_date:
            continue
        due = p.revised_target_date or p.original_target_date
        grp = "Customer inputs" if p.pending_with == "customer" else "WFX commitments" if p.pending_with == "wfx" else f"Pending with {p.pending_with}"
        base = {"title": p.description, "description": " · ".join(x for x in (p.category, p.remarks) if x)[:160], "owner": p.owner_name, "responsibility": p.pending_with, "source": {"type": "pending", "id": str(p.id)}}
        if due and s <= due <= e:
            add(grp, {**base, "due": d_iso(due), "tag": "due", "days_late": 0})
        elif include_overdue and due and due + timedelta(days=snap.grace) < snap.as_of:
            add(grp, {**base, "due": d_iso(due), "tag": "carry_over", "days_late": (snap.as_of - due).days - snap.grace}, True)
    specs = [g for g in snap.gaps if gap_due(g) and s <= gap_due(g) <= e and not g.signoff_date]
    by_team: dict[str, list[GapSpecification]] = defaultdict(list)
    for g in specs:
        by_team[g.team or g.module or "Specifications"].append(g)
    for team, lst in by_team.items():
        owners = Counter((g.responsibility or "Unassigned") for g in lst)
        add("Gap specifications", {"title": f"Gap specs due — {team} ({len(lst)})", "description": " · ".join(f"{k} {v}" for k, v in owners.most_common(4)),
                                   "owner": owners.most_common(1)[0][0], "responsibility": "WFX", "due": d_iso(min(gap_due(g) for g in lst)), "tag": "due", "days_late": 0,
                                   "source": {"type": "gap_group", "id": None, "ids": [str(g.id) for g in lst][:200]}})
    by_stream: dict[str, list[tuple[DeliveryItem, dict]]] = defaultdict(list)
    overdue_stream: dict[str, list[tuple[DeliveryItem, dict]]] = defaultdict(list)
    for d in snap.deliveries:
        ex = delivery_extras(d, snap.as_of, snap.grace)
        if ex["is_closed"] or not ex["effective_target_date"]:
            continue
        due = date.fromisoformat(ex["effective_target_date"])
        if s <= due <= e:
            by_stream[d.stream or "Delivery"].append((d, ex))
        elif include_overdue and ex["is_overdue"]:
            overdue_stream[d.stream or "Delivery"].append((d, ex))
    for stream, lst in by_stream.items():
        owners = Counter((d.tech_owner or d.functional_owner or "Unassigned") for d, _ in lst)
        add("Development delivery", {"title": f"Deliveries due — {stream} ({len(lst)})", "description": " · ".join(f"{k} {v}" for k, v in owners.most_common(4)), "owner": owners.most_common(1)[0][0],
                                      "responsibility": "WFX", "due": min(ex["effective_target_date"] for _, ex in lst), "tag": "due", "days_late": 0,
                                      "source": {"type": "delivery_group", "id": None, "ids": [str(d.id) for d, _ in lst][:200]}})
    for stream, lst in overdue_stream.items():
        worst = max(ex["days_late"] for _, ex in lst)
        add("Development delivery", {"title": f"Overdue deliveries — {stream} ({len(lst)})", "description": f"longest {worst} d late", "owner": None, "responsibility": "WFX",
                                      "due": min(ex["effective_target_date"] for _, ex in lst), "tag": "carry_over", "days_late": worst,
                                      "source": {"type": "delivery_group", "id": None, "ids": [str(d.id) for d, _ in lst][:200]}}, True)
    by_module: dict[str, list] = defaultdict(list)
    late_module: dict[str, list] = defaultdict(list)
    for u in snap.uat:
        if u.result in UAT_NOT_DONE and u.planned_date:
            if s <= u.planned_date <= e:
                by_module[u.module or "General"].append(u)
            elif include_overdue and scenario_overdue(u, snap.as_of, snap.grace):
                late_module[u.module or "General"].append(u)
    for mod, lst in by_module.items():
        owners = Counter((u.tester or "Unassigned") for u in lst)
        add("UAT", {"title": f"UAT scenarios to run: {mod} ({len(lst)})", "description": " · ".join(f"{k} {v}" for k, v in owners.most_common(4)), "owner": owners.most_common(1)[0][0], "responsibility": None,
                    "due": d_iso(min(u.planned_date for u in lst)), "tag": "due", "days_late": 0, "source": {"type": "uat_group", "id": None, "ids": [str(u.id) for u in lst][:200]}})
    for mod, lst in late_module.items():
        worst = max((snap.as_of - u.planned_date).days - snap.grace for u in lst)
        add("UAT", {"title": f"Overdue UAT scenarios: {mod} ({len(lst)})", "description": f"longest {worst} d late", "owner": None, "responsibility": None, "due": d_iso(min(u.planned_date for u in lst)),
                    "tag": "carry_over", "days_late": worst, "source": {"type": "uat_group", "id": None, "ids": [str(u.id) for u in lst][:200]}}, True)
    for d in snap.defects:
        if d.status in ("open", "in_fix", "retest") and d.target_date:
            base = {"title": f"Defect {d.defect_ref or ''} {d.title[:80]}".replace("  ", " ").strip(), "description": f"{d.severity} severity", "owner": d.owner_name, "responsibility": None, "source": {"type": "uat_defect", "id": str(d.id)}}
            if s <= d.target_date <= e:
                add("UAT", {**base, "due": d_iso(d.target_date), "tag": "due", "days_late": 0})
            elif include_overdue and defect_overdue(d, snap.as_of, snap.grace):
                add("UAT", {**base, "due": d_iso(d.target_date), "tag": "carry_over", "days_late": (snap.as_of - d.target_date).days - snap.grace}, True)
    for grp, src, items in (("Integrations", "integration_item", snap.integrations), ("Reports + prints", "report_item", snap.reports)):
        for o in items:
            closed, a = deliverable_state(o, snap.as_of, snap.grace)
            if closed or a.effective_finish is None:
                continue
            base = {"title": o.name[:100], "description": " · ".join(x for x in (getattr(o, "partner", None) or getattr(o, "module", None), o.status_raw) if x), "owner": o.owner_name, "responsibility": None, "source": {"type": src, "id": str(o.id)}}
            if s <= a.effective_finish <= e:
                add(grp, {**base, "due": d_iso(a.effective_finish), "tag": "due", "days_late": 0})
            elif include_overdue and a.overdue:
                add(grp, {**base, "due": d_iso(a.effective_finish), "tag": "carry_over", "days_late": a.days_late}, True)
    # activities people put on the plan (Monday-Sunday weeks): shown with the derived cards, editable
    in_plan = {(w.source_type, str(w.source_id)) for w in snap.week_items if w.source_id and w.week_start + timedelta(days=6) >= s and w.week_start <= e}
    for w in snap.week_items:
        w_end = w.week_start + timedelta(days=6)
        grp = w.workstream or (snap.products[w.product_id].code if w.product_id in snap.products else "Planned activities")
        base = {"id": str(w.id), "title": w.title, "description": " · ".join(x for x in (w.module, w.remarks) if x)[:160], "owner": w.owner_name, "responsibility": None,
                "source": {"type": "week_plan_item", "id": str(w.id)}, "percent_complete": w.percent_complete, "plan_status": w.status, "week_start": d_iso(w.week_start)}
        due = w.target_date or w_end
        if w_end >= s and w.week_start <= e:
            add(grp, {**base, "due": d_iso(due), "tag": "planned", "days_late": 0})
        elif include_overdue and w_end < s and w.status != "done":
            add(grp, {**base, "due": d_iso(due), "tag": "carry_over", "days_late": (snap.as_of - due).days}, True)
    for g in groups.values():
        for c in g:
            c["in_plan"] = (c["source"]["type"], c["source"]["id"]) in in_plan if c["source"].get("id") and c["source"]["type"] != "week_plan_item" else False
    order = ["Project-wide"] + sorted(k for k in groups if k not in ("Project-wide", "Gap specifications", "Development delivery", "Customer inputs", "WFX commitments")) + ["Gap specifications", "Development delivery", "Customer inputs", "WFX commitments"]
    out_groups, n = [], 0
    for g in order:
        cards = sorted(groups.get(g, []), key=lambda c: (c["tag"] == "carry_over", c["due"] or "9999"))
        if not cards:
            continue
        for c in cards:
            n += 1
            c["seq"] = n
        out_groups.append({"name": g, "count": len(cards), "carry_over_hidden": max(0, carry[g] - sum(1 for c in cards if c["tag"] == "carry_over")), "cards": cards})
    return {**_meta(snap, "next_week", {"period": period}), "week": {"start": s.isoformat(), "end": e.isoformat(), "label": label}, "groups": out_groups,
            "total_cards": n, "available": n > 0,
            "notes": ["Cards are sorted by due date; overdue carry-overs are labelled and capped at 5 per group."]}


# ------------------------------------------------------------------ F. delay dashboard
def delays(snap: Snapshot) -> dict:
    rows: list[dict] = []
    pname = lambda pid: snap.products[pid].code if pid else "Project-wide"  # noqa: E731

    def row(source, rid, title, product, owner, resp, due, base, days, kind):
        rows.append({"source": source, "id": rid, "title": title, "product": product, "owner": owner, "responsibility": resp, "party": party(snap, resp),
                     "due": d_iso(due), "baseline": d_iso(base), "days_late": days, "slippage": (due - base).days if due and base else 0, "kind": kind})

    for w in snap.tasks:
        t = task_item(snap, w)
        if t["overdue"] or t["start_delayed"]:
            row("plan_task", t["id"], t["title"], pname(w.product_id), w.owner_name, w.responsible_party, t["finish"], w.planned_finish, t["days_late"] if t["overdue"] else (snap.as_of - t["start"]).days - snap.grace, "overdue" if t["overdue"] else "start_delayed")
    for ev in snap.events:
        i = event_item(snap, ev)
        if i["overdue"]:
            row("tracker_event", i["id"], f"{ev.event_name} ({pname(ev.product_id)})", pname(ev.product_id), ev.spoc, ev.responsibility, ev.planned_date, ev.planned_date, i["days_late"], "overdue")
    for p in snap.pending:
        due = p.revised_target_date or p.original_target_date
        closed = p.status_category in ("done", "cancelled") or p.actual_closure_date
        if not closed and due and due + timedelta(days=snap.grace) < snap.as_of:
            row("pending_item", str(p.id), p.description, pname(p.product_id), p.owner_name, p.pending_with if p.pending_with != "customer" else (snap.customer.name if snap.customer else "customer"),
                due, p.original_target_date, (snap.as_of - due).days - snap.grace, "overdue")
            rows[-1]["party"] = {"customer": "customer", "wfx": "wfx"}.get(p.pending_with, "other")
    for g in snap.gaps:
        due = gap_due(g)
        if due and due + timedelta(days=snap.grace) < snap.as_of and not g.signoff_date and not (g.approval_status or "").lower().startswith("approved"):
            row("gap_specification", str(g.id), f"{g.external_issue_id or ''} {g.description[:80]}".strip(), g.product_name or "Project-wide", g.responsibility, "WFX" if g.responsibility else None, due, g.target_date, (snap.as_of - due).days - snap.grace, "overdue")
    for d in snap.deliveries:
        ex = delivery_extras(d, snap.as_of, snap.grace)
        if ex["is_overdue"] or ex["is_start_delayed"]:
            due = date.fromisoformat(ex["effective_target_date"]) if ex["is_overdue"] else d.dev_initiation
            late = ex["days_late"] if ex["is_overdue"] else (snap.as_of - d.dev_initiation).days - snap.grace
            row("delivery_item", str(d.id), f"{d.external_id or ''} {d.description[:80]}".strip(), d.stream or "Project-wide", d.tech_owner or d.functional_owner,
                snap.customer.name if (d.status_raw or "").lower().startswith("pending with") and snap.customer else "WFX", due,
                d.delivery_target_date if ex["is_overdue"] else d.dev_initiation, late, "overdue" if ex["is_overdue"] else "start_delayed")
    for g in snap.gates:
        if gate_overdue(g, snap.as_of, snap.grace):
            row("approval_gate", str(g.id), g.name, "Project-wide", None, None, g.planned_date, g.planned_date, (snap.as_of - g.planned_date).days - snap.grace, "overdue")
    for u in snap.uat:
        if scenario_overdue(u, snap.as_of, snap.grace):
            row("uat_scenario", str(u.id), f"{u.scenario_id or ''} {u.title[:80]}".strip(), pname(u.product_id), u.tester, None, u.planned_date, u.planned_date, (snap.as_of - u.planned_date).days - snap.grace, "overdue")
    for d in snap.defects:
        if defect_overdue(d, snap.as_of, snap.grace):
            row("uat_defect", str(d.id), f"{d.defect_ref or ''} {d.title[:80]}".strip(), pname(d.product_id), d.owner_name, None, d.target_date, d.target_date, (snap.as_of - d.target_date).days - snap.grace, "overdue")
    for src, items in (("integration_item", snap.integrations), ("report_item", snap.reports)):
        for o in items:
            closed, a = deliverable_state(o, snap.as_of, snap.grace)
            if a.overdue:
                row(src, str(o.id), o.name[:100], pname(o.product_id), o.owner_name, None, a.effective_finish, o.target_date, a.days_late, "overdue")
    avail = {"plan_task": bool(snap.tasks), "tracker_event": bool(snap.events), "pending_item": bool(snap.pending), "gap_specification": bool(snap.gaps), "approval_gate": bool(snap.gates), "delivery_item": bool(snap.deliveries),
             "uat_scenario": bool(snap.uat), "uat_defect": bool(snap.defects), "integration_item": bool(snap.integrations), "report_item": bool(snap.reports)}
    labels = {"plan_task": "Project plan", "tracker_event": "Tracker events", "pending_item": "Pending activities", "gap_specification": "Gap specifications", "approval_gate": "Sign-off gates", "delivery_item": "Development delivery",
              "uat_scenario": "UAT scenarios", "uat_defect": "UAT defects", "integration_item": "Integrations", "report_item": "Reports + prints"}
    sources = [{"key": k, "label": labels[k], "available": avail[k], "count": sum(1 for r in rows if r["source"] == k) if avail[k] else None,
                "refs": [r["id"] for r in rows if r["source"] == k][:300]} for k in labels]

    def bucket(d: int) -> str:
        return "1-7" if d <= 7 else "8-14" if d <= 14 else "15-30" if d <= 30 else "31-60" if d <= 60 else "60+"
    ageing = Counter(bucket(r["days_late"]) for r in rows if r["days_late"] > 0)
    by_product = Counter(r["product"] for r in rows)
    by_party = Counter(r["party"] for r in rows)
    by_owner = Counter(r["owner"] or "Unassigned" for r in rows)
    slipped = sorted([r for r in rows if r["slippage"] > 0], key=lambda r: -r["slippage"])
    rows.sort(key=lambda r: -r["days_late"])
    return {**_meta(snap, "delays"), "sources": sources, "total": len(rows), "rows": rows[:500], "truncated": len(rows) > 500,
            "ageing": [{"bucket": b, "count": ageing.get(b, 0)} for b in ("1-7", "8-14", "15-30", "31-60", "60+")],
            "by_product": [{"name": k, "count": v} for k, v in by_product.most_common()],
            "by_party": [{"party": k, "count": v} for k, v in by_party.most_common()],
            "by_owner": [{"name": k, "count": v} for k, v in by_owner.most_common(10)],
            "slippage": slipped[:25], "available": any(avail.values()),
            "notes": ["Slippage = current date minus original (baseline) date, so revised dates never hide a delay.", "Development delivery appears once a delivery tracker has been imported or entered."]}
