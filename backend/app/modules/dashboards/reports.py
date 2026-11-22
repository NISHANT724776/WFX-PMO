"""The eight management reports, built once from the same calculation service as the dashboards (metrics.py).

A report is a neutral structure (headline numbers + tables + notes). The renderers (Excel, PDF, PowerPoint) only lay it out, so a number
can never differ between the screen and an export.
"""
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project
from app.modules.dashboards import metrics, trackers
from app.modules.dashboards.widgets import _products_with_data
from app.modules.planning.gates import gate_closed, gate_days_late, gate_overdue


@dataclass
class Table:
    title: str
    columns: list[str]
    rows: list[list[Any]]  # str | int | float | date | None
    note: str | None = None


@dataclass
class Report:
    key: str
    title: str
    subtitle: str
    project: dict
    as_of: str
    kpis: list[tuple[str, str]] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    gantt: list[dict] | None = None  # phase rows to draw as bars (PDF, PowerPoint)
    payload: dict | None = None  # the dashboard payload when a ready-made PowerPoint layout exists
    pptx_kind: str | None = None


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:g}%"


CATALOGUE: dict[str, dict] = {}


def report(key: str, label: str, description: str, needs_product: bool = False, takes_period: bool = False):
    def deco(fn: Callable):
        CATALOGUE[key] = {"key": key, "label": label, "description": description, "needs_product": needs_product, "takes_period": takes_period, "fn": fn}
        return fn

    return deco


def _base(snap: metrics.Snapshot, key: str, title: str, extra_sub: str = "") -> dict:
    p = snap.project
    return {"key": key, "title": title, "subtitle": f"{snap.customer.name + ' · ' if snap.customer else ''}{p.name} · status as of {snap.as_of.strftime('%d-%b-%Y')}{extra_sub}",
            "project": {"id": str(p.id), "code": p.code, "name": p.name, "customer": snap.customer.name if snap.customer else None}, "as_of": snap.as_of.isoformat()}


def _phase_rows(rows: list[dict]) -> list[list[Any]]:
    return [[r["area"], r["label"], {"done": "Done", "in_progress": "In progress", "overdue": "Overdue", "upcoming": "Upcoming"}[r["state"]], r["pct"], _d(r["start"]), _d(r["end"]), r["items"], r["done"], r["late_items"]] for r in rows]


PHASE_COLS = ["Area", "Phase", "State", "% done", "Start", "End", "Items", "Done", "Late items"]
FORMULAS = ["% complete = (Done + ½ In progress) ÷ (plan tasks + tracker events).",
            "Phase state: Done = all items closed; Overdue = any open item is past its date (+ grace days) or has not started although its start has passed; In progress = some work started; Upcoming = not started."]


# ------------------------------------------------------------------ 1. overall project status
@report("overall", "Overall project status", "Headline numbers and every phase with its state, % done and dates (the status-report page).")
def overall(db: Session, project: Project, snap: metrics.Snapshot, **_) -> Report:
    p = metrics.overall(snap)
    act, ov = p["kpis"]["activities"], p["kpis"]["overall"]
    return Report(**_base(snap, "overall", "Project status"), payload=p, pptx_kind="overall", gantt=p["rows"], notes=FORMULAS,
                  kpis=[("Overall completion", _pct(ov["pct_display"])), ("Total phases", str(act["phases"])), ("Completed activities", str(act["completed"])), ("In-progress activities", str(act["in_progress"])),
                        ("Overdue activities", str(act["overdue"])), ("Upcoming milestones", str(act["upcoming_milestones"]))],
                  tables=[Table("Phases", PHASE_COLS, _phase_rows(p["rows"]))])


# ------------------------------------------------------------------ 2. product-wise status
@report("product", "Product-wise status", "Coverage and status of one product: phases, sign-off gates, blueprint approvals and what needs attention.", needs_product=True)
def product(db: Session, project: Project, snap: metrics.Snapshot, product_id: uuid.UUID | None = None, **_) -> Report:
    if product_id is None or product_id not in snap.products:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a product for this report")
    p = metrics.product_view(snap, product_id)
    prod = snap.products[product_id]
    k = p["kpis"]
    ng = k["next_gate"]
    gates = [[g["name"], _d(g["planned"]), _d(g["actual"]), g["state"], g.get("owner"), g.get("responsibility")] for g in p["gates"]]
    appr = [[a["set"], a["name"], a.get("approver"), _d(a["planned"]), _d(a["submission"]), _d(a["signoff"]), a["status"], a["state"]] for a in p["approvals"]]
    na = [[i["severity"], i["text"], (i.get("action") or {}).get("owner"), (i.get("action") or {}).get("status"), (i.get("action") or {}).get("last_action")] for i in p["needs_attention"]]
    return Report(**_base(snap, "product", f"{prod.code}: Coverage and status", f" · {prod.name}"), payload=p, pptx_kind="product", gantt=p["rows"], notes=FORMULAS + p["notes"],
                  kpis=[("Overall completion", _pct(k["overall"]["pct_display"])), ("Items done", f"{k['items']['done']} / {k['items']['total']}"), ("Overdue / start delayed", str(k["late"]["value"])),
                        ("Next gate", f"{ng['name']} {ng['planned']}" if ng else "none upcoming"), ("Go-live", k["go_live"] or "–")],
                  tables=[Table("Phases", PHASE_COLS, _phase_rows(p["rows"])),
                          Table("Sign-off gate tracker", ["Gate", "Planned", "Actual", "State", "Owner", "Responsibility"], gates),
                          Table("Blueprint approvals", ["Set", "Gate", "Approver", "Planned", "Submitted", "Approved", "Status", "State"], appr),
                          Table("Needs attention", ["Severity", "Item", "Action owner", "Action status", "Latest action"], na)])


# ------------------------------------------------------------------ 3. project timeline
@report("timeline", "Project timeline", "Every task and milestone with baseline, current and actual dates, plus the phase bars.")
def timeline(db: Session, project: Project, snap: metrics.Snapshot, **_) -> Report:
    p = metrics.overall(snap)
    rows = []
    for w in snap.tasks:
        t = metrics.task_item(snap, w)
        ph = snap.phases.get(w.phase_id)
        rows.append([ph.name if ph else "(no phase)", w.title, "Milestone" if w.kind == "milestone" else "Task", w.owner_name or w.responsible_party,
                     snap.products[w.product_id].code if w.product_id in snap.products else "Project-wide", w.planned_start, w.planned_finish, t["start"], t["finish"], w.actual_start, w.actual_finish,
                     w.status_raw, t["days_late"] or None, t["slippage"] or None])
    events = [[snap.products[e.product_id].code if e.product_id in snap.products else "", e.event_name, e.planned_date, e.actual_date, e.responsibility, e.spoc] for e in snap.events]
    return Report(**_base(snap, "timeline", "Project timeline"), payload=p, pptx_kind="overall", gantt=p["rows"], notes=FORMULAS + ["Baseline dates are never overwritten; current dates follow the latest approved revision."],
                  kpis=[("Phases", str(len(p["rows"]))), ("Tasks and milestones", str(len(snap.tasks))), ("Tracker events", str(len(snap.events)))],
                  tables=[Table("Phases", PHASE_COLS, _phase_rows(p["rows"])),
                          Table("Tasks and milestones", ["Phase", "Task", "Type", "Owner", "Product", "Baseline start", "Baseline finish", "Current start", "Current finish", "Actual start", "Actual finish", "Status", "Days late", "Slipped (days)"], rows),
                          Table("Tracker milestones", ["Product", "Event", "Planned", "Actual", "Responsibility", "SPOC"], events)])


# ------------------------------------------------------------------ 4. sign-off gate tracker
@report("gates", "Sign-off gate tracker", "Every sign-off gate and go-live with planned and actual dates, and each blueprint approval with its approver and status.")
def gates(db: Session, project: Project, snap: metrics.Snapshot, **_) -> Report:
    tracker = []
    for pid in _products_with_data(snap):
        for g in metrics.product_view(snap, pid)["gates"]:
            tracker.append([snap.products[pid].code, g["name"], _d(g["planned"]), _d(g["actual"]), g["state"], g.get("owner"), g.get("responsibility")])
    tracker.sort(key=lambda r: (r[2] is None, r[2] or date.max))
    appr = []
    for g in sorted(snap.gates, key=lambda g: (g.gate_type, g.sort_order)):
        state = "approved" if gate_closed(g) else "overdue" if gate_overdue(g, snap.as_of, snap.grace) else "open"
        appr.append([g.gate_type, g.name, snap.products[g.product_id].code if g.product_id in snap.products else "All", g.approver_name, g.planned_date, g.submission_date, g.signoff_date, g.approval_status, state, gate_days_late(g, snap.as_of, snap.grace) or None])
    n_done = sum(1 for r in tracker if r[4] == "done")
    a_done = sum(1 for r in appr if r[8] == "approved")
    return Report(**_base(snap, "gates", "Sign-off gate tracker"), notes=[metrics.GATE_RULE + ".", "A blueprint approval is overdue when it is not approved and its planned date (+ grace days) has passed."],
                  kpis=[("Tracker gates", str(len(tracker))), ("Gates done", str(n_done)), ("Gates overdue", str(sum(1 for r in tracker if r[4] == "overdue"))),
                        ("Blueprint approvals", str(len(appr))), ("Approved", str(a_done)), ("Approvals overdue", str(sum(1 for r in appr if r[8] == "overdue")))],
                  tables=[Table("Sign-off gates and go-live", ["Product", "Gate", "Planned", "Actual", "State", "Owner", "Responsibility"], tracker),
                          Table("Blueprint approvals", ["Set", "Gate", "Product", "Approver", "Planned", "Submitted", "Approved", "Status", "State", "Days late"], appr)])


# ------------------------------------------------------------------ 5. department and location coverage
@report("coverage", "Department and location coverage", "Completed ÷ planned activities for each department and location, with the activities behind it.", needs_product=False)
def coverage(db: Session, project: Project, snap: metrics.Snapshot, product_id: uuid.UUID | None = None, **_) -> Report:
    from app.models import Department, Location  # noqa: PLC0415
    from app.models.workspace import CoverageActivity  # noqa: PLC0415

    cov = metrics.coverage(db, project, product_id)
    depts, locs = {d.id: d.name for d in db.scalars(select(Department))}, {l.id: l.name for l in db.scalars(select(Location))}
    stmt = select(CoverageActivity).where(CoverageActivity.project_id == project.id)
    if product_id:
        stmt = stmt.where(CoverageActivity.product_id == product_id)
    acts = list(db.scalars(stmt.order_by(CoverageActivity.sort_order)))
    cell = {(c["department_id"], c["location_id"]): c for c in cov["cells"]}
    fmt = lambda t: "n/a" if t["pct"] is None else f"{t['pct']:g}% ({t['completed']}/{t['planned']})"  # noqa: E731
    matrix = [[d["name"], *[fmt(cell[(d["id"], l["id"])]) if (d["id"], l["id"]) in cell else "" for l in cov["locations"]], fmt(d)] for d in cov["departments"]]
    if cov["available"]:
        matrix.append(["All departments", *[fmt(l) for l in cov["locations"]], fmt(cov["total"])])
    t = cov["total"]
    return Report(**_base(snap, "coverage", "Department and location coverage", f" · {snap.products[product_id].code}" if product_id in snap.products else ""), notes=[cov["formula"]] if cov["available"] else ["No coverage activities have been added yet."],
                  kpis=[("Coverage", _pct(t["pct"])), ("Planned", str(t["planned"])), ("Completed", str(t["completed"])), ("Activities", str(t["activities"]))],
                  tables=[Table("Dept x location coverage", ["Department", *[l["name"] for l in cov["locations"]], "All locations"], matrix),
                          Table("Locations compared", ["Location", "Planned", "Completed", "Coverage %"], [[l["name"], l["planned"], l["completed"], l["pct"]] for l in cov["locations"]]),
                          Table("Activities", ["Activity", "Department", "Location", "Responsible", "Planned", "Completed", "%"],
                                [[a.title, depts.get(a.department_id), locs.get(a.location_id), a.responsible_name, a.planned_count, a.completed_count,
                                  round(a.completed_count / a.planned_count * 100, 1) if a.planned_count else None] for a in acts])])


# ------------------------------------------------------------------ 6. needs attention
@report("attention", "Needs attention", "What is overdue or waiting, with the action, owner and latest step where one has been raised.", needs_product=False)
def attention(db: Session, project: Project, snap: metrics.Snapshot, product_id: uuid.UUID | None = None, **_) -> Report:
    if product_id and product_id in snap.products:
        items = metrics.product_view(snap, product_id)["needs_attention"]
    else:
        gs = [g for pid in _products_with_data(snap) for g in metrics.product_view(snap, pid)["gates"]]
        items = metrics.needs_attention(snap, None, [metrics.task_item(snap, w) for w in snap.tasks], [metrics.event_item(snap, e) for e in snap.events], gs)
    rows = [[i["severity"], i["kind"], i["text"], (i.get("action") or {}).get("owner"), (i.get("action") or {}).get("status"), _d((i.get("action") or {}).get("due")), (i.get("action") or {}).get("last_action"),
             (i.get("action") or {}).get("last_action_by")] for i in items]
    return Report(**_base(snap, "attention", "Needs attention", f" · {snap.products[product_id].code}" if product_id in snap.products else ""),
                  kpis=[("Items", str(len(items))), ("High severity", str(sum(1 for i in items if i["severity"] == "high"))), ("With an action", str(sum(1 for i in items if i.get("action")))),
                        ("Without an action", str(sum(1 for i in items if not i.get("action"))))],
                  notes=["High severity first, then by how long the item has been late."], tables=[Table("Needs attention", ["Severity", "Kind", "Item", "Action owner", "Action status", "Action due", "Latest step", "By"], rows)])


# ------------------------------------------------------------------ 7. next week plan
@report("next_week", "Next week plan", "What is due or planned in the week (Monday to Sunday), grouped by workstream.", takes_period=True)
def next_week(db: Session, project: Project, snap: metrics.Snapshot, period: str = "next_week", **_) -> Report:
    p = metrics.next_week(snap, period)
    tag = {"due": "Due", "starts": "Starts", "planned": "Planned", "carry_over": "Overdue carry-over"}
    rows = [[g["name"], c["title"], c["description"], c["owner"] or c["responsibility"], tag.get(c["tag"], c["tag"]), _d(c["due"]), c["days_late"] or None, c.get("plan_status"), c.get("percent_complete")]
            for g in p["groups"] for c in g["cards"]]
    w = p["week"]
    return Report(**_base(snap, "next_week", f"{w['label']}: plan", f" · {w['start']} to {w['end']}"), payload=p, pptx_kind="next_week", notes=p["notes"] + ["Weeks run Monday to Sunday."],
                  kpis=[("Activities", str(p["total_cards"])), ("Workstreams", str(len(p["groups"]))), ("Overdue carry-overs", str(sum(1 for r in rows if r[4] == "Overdue carry-over")))],
                  tables=[Table("Activities", ["Workstream", "Activity", "Detail", "Owner", "Type", "Due / target", "Days late", "Status", "% complete"], rows)])


# ------------------------------------------------------------------ 8. overdue activities
@report("overdue", "Overdue activity list", "Every overdue activity with owner, original and revised dates and days late, then all delayed items across every source.", needs_product=False)
def overdue(db: Session, project: Project, snap: metrics.Snapshot, product_id: uuid.UUID | None = None, **_) -> Report:
    pid = product_id if product_id in snap.products else None
    cols = ["Activity", "Phase", "Product", "Owner", "Original", "Revised", "Current", "Days late", "Status"]
    mk = lambda metric: [[r["title"], r["phase"], r["product"], r["owner"] or r["responsible"], r["original_finish"], r["revised_finish"], r["current_finish"], r["days_late"] or None, r["status"]]  # noqa: E731
                         for r in sorted(metrics.drilldown_rows(snap, metric, pid), key=lambda r: -r["days_late"])]
    late, start_late = mk("overdue"), mk("start_delayed")
    tables = [Table("Overdue activities", cols, late), Table("Start delayed", cols, start_late)]
    kpis = [("Overdue activities", str(len(late))), ("Start delayed", str(len(start_late)))]
    if pid is None:
        d = metrics.delays(snap)
        tables.append(Table("Delayed items, all sources", ["Source", "Item", "Product", "Owner", "Party", "Due", "Baseline", "Days late", "Slipped (days)"],
                            [[r["source"].replace("_", " "), r["title"], r["product"], r["owner"], r["party"], _d(r["due"]), _d(r["baseline"]), r["days_late"], r["slippage"] or None] for r in d["rows"]]))
        kpis.append(("Delayed items, all sources", str(d["total"])))
    return Report(**_base(snap, "overdue", "Overdue activities", f" · {snap.products[pid].code}" if pid else ""), kpis=kpis, tables=tables,
                  notes=["Overdue = not closed and the current finish date (+ grace days) has passed. Days late are counted from the current date; the original date is shown beside it."])


# ------------------------------------------------------------------ 9. UAT status
@report("uat", "UAT status", "Every UAT scenario with its result, results by module and cycle, and the UAT defects.", needs_product=False)
def uat(db: Session, project: Project, snap: metrics.Snapshot, product_id: uuid.UUID | None = None, **_) -> Report:
    from app.models.workspace import UatDefect, UatScenario  # noqa: PLC0415

    pid = product_id if product_id in snap.products else None
    u = trackers.uat_summary(db, project, snap.as_of, pid)
    sq, dq = select(UatScenario).where(UatScenario.project_id == project.id), select(UatDefect).where(UatDefect.project_id == project.id)
    if pid:
        sq, dq = sq.where(UatScenario.product_id == pid), dq.where(UatDefect.product_id == pid)
    sc, df = list(db.scalars(sq.order_by(UatScenario.sort_order))), list(db.scalars(dq.order_by(UatDefect.sort_order)))
    scn = {s.id: (s.scenario_id or s.title[:40]) for s in sc}
    S, D = u["scenarios"], u["defects"]
    mod = lambda rows: [[r["name"], r["total"], r["passed"], r["failed"], r["blocked"], r["retest"], r["in_progress"], r["not_run"], r["pass_rate"]] for r in rows]  # noqa: E731
    cols = ["Name", "Total", "Passed", "Failed", "Blocked", "Retest", "In progress", "Not run", "Pass rate %"]
    return Report(**_base(snap, "uat", "UAT status", f" · {snap.products[pid].code}" if pid else ""), notes=[trackers.UAT_FORMULA, "A scenario marked Passed or Failed has a tester and an execution date; Failed has an actual result; Passed has no open defect."],
                  kpis=[("Scenarios", str(S["total"])), ("Pass rate", _pct(S["pass_rate"])), ("Executed", _pct(S["executed_pct"])), ("Failed", str(S["by_result"]["failed"])), ("Blocked", str(S["by_result"]["blocked"])),
                        ("Overdue to run", str(S["overdue"])), ("Open defects", str(D["open"]))],
                  tables=[Table("Results by module", cols, mod(S["by_module"])), Table("Results by cycle", cols, mod(S["by_cycle"])),
                          Table("Scenarios", ["ID", "Scenario", "Module", "Cycle", "Tester", "Planned", "Executed", "Result", "Defect ref"],
                                [[x.scenario_id, x.title, x.module, x.cycle, x.tester, x.planned_date, x.executed_date, trackers.RESULT_LABEL[x.result], x.defect_ref] for x in sc]),
                          Table("Defects", ["Ref", "Defect", "Scenario", "Severity", "Status", "Raised", "Owner", "Target", "Closed", "Resolution"],
                                [[x.defect_ref, x.title, scn.get(x.scenario_id), x.severity, x.status, x.raised_on, x.owner_name, x.target_date, x.closed_on, x.resolution] for x in df])])


# ------------------------------------------------------------------ 10. reports, prints and integrations
@report("deliverables", "Reports, prints and integrations", "The integration register and the reports + prints inventory with status, target and revised dates, and what is overdue.", needs_product=False)
def deliverables(db: Session, project: Project, snap: metrics.Snapshot, product_id: uuid.UUID | None = None, **_) -> Report:
    pid = product_id if product_id in snap.products else None
    d = trackers.deliverables_summary(db, project, snap.as_of, pid)
    keep = lambda o: pid is None or o.product_id == pid  # noqa: E731

    def line(o, extra):
        closed, a = trackers.deliverable_state(o, snap.as_of, snap.grace)
        return [o.name, *extra, snap.products[o.product_id].code if o.product_id in snap.products else "Project-wide", o.owner_name, o.status_raw, o.target_date, o.revised_target_date, o.actual_date, o.uat_status, a.days_late or None]

    I, R = d["integrations"], d["reports"]
    return Report(**_base(snap, "deliverables", "Reports, prints and integrations", f" · {snap.products[pid].code}" if pid else ""), notes=[d["formula"]],
                  kpis=[("Integrations", str(I["total"])), ("Integrations overdue", str(I["overdue"])), ("Integrations done", _pct(I["done_pct"])), ("Reports + prints", str(R["total"])), ("Reports overdue", str(R["overdue"])), ("Reports done", _pct(R["done_pct"]))],
                  tables=[Table("Integrations", ["Integration", "Partner", "Direction", "Technology", "Product", "Owner", "Status", "Target", "Revised", "Actual", "UAT status", "Days late"],
                                [line(o, [o.partner, o.direction, o.technology]) for o in snap.integrations if keep(o)]),
                          Table("Reports + prints", ["Name", "Type", "Module", "Folder", "Product", "Owner", "Status", "Target", "Revised", "Actual", "UAT status", "Days late"],
                                [line(o, [o.report_type, o.module, o.folder]) for o in snap.reports if keep(o)])])


def build(db: Session, project: Project, key: str, as_of: date, product_id: uuid.UUID | None, period: str) -> Report:
    entry = CATALOGUE.get(key)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown report")
    snap = metrics.load(db, project, as_of)
    r = entry["fn"](db, project, snap, product_id=product_id, period=period)
    r.notes = [*r.notes, f"Grace days: {snap.grace}. Generated from the project database on {date.today().strftime('%d-%b-%Y')}; nothing in this report is typed in."]
    return r


def catalogue() -> list[dict]:
    return [{k: v for k, v in e.items() if k != "fn"} | {"formats": ["xlsx", "pdf", "pptx"]} for e in CATALOGUE.values()]
