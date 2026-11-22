"""Dashboard widget registry.

A widget type is ONE entry here: its title, its settings (name, kind, options), its default size and a function that returns its data.
The dashboard engine (layout storage, validation, the data endpoint, the grid editor) never changes when a type is added.

Every number comes from the same calculation service as the fixed dashboards (metrics.py); a widget only chooses and shapes it.
A widget's data is one of a few shapes the front end already knows how to draw, so a new type that returns one of them needs no front-end work:
  kpis      {items:[{key,label,value,sub,color,drill}]}
  series    {series:[{label,value,color}], total, unit}       drawn as bar | donut | table (the widget's chart_type setting)
  table     {columns:[{key,label}], rows:[{...}]}
  timeline  {rows:[phase rows], as_of}
  attention {items:[needs-attention items]}
  gates     {gates:[...], approval_summary, open_approvals}
  week      {week, groups, total_cards}
  matrix    {coverage payload}
  text      {text, size}
  empty     {message}
"""
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import cached_property
from typing import Any, Callable

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Location, Product, Project
from app.modules.dashboards import metrics, trackers
from app.modules.delivery.lifecycle import combined_category
from app.modules.planning.gates import gate_closed, gate_overdue

GRID_COLS = 12
MAX_WIDGETS = 40
MAX_ROWS = 24
GREEN, AMBER, RED, SLATE, NAVY, BLUE = "#16a34a", "#d97706", "#dc2626", "#94a3b8", "#0b1f4b", "#2563eb"
CHART_TYPES = [("bar", "Bars"), ("donut", "Donut"), ("table", "Table")]


@dataclass
class Setting:
    key: str
    label: str
    kind: str  # select | multiselect | product | location | number | text | longtext
    options: list[tuple[str, str]] = field(default_factory=list)
    default: Any = None
    minimum: int | None = None
    maximum: int | None = None


@dataclass
class WidgetType:
    type: str
    title: str
    description: str
    shape: str
    size: tuple[int, int]  # default (w, h) in grid units
    min_size: tuple[int, int]
    settings: list[Setting]
    fn: Callable[["Ctx", dict], dict]
    sources: list[str]  # where the data comes from, shown in the palette


REGISTRY: dict[str, WidgetType] = {}


def widget(**kw):
    def deco(fn):
        REGISTRY[kw["type"]] = WidgetType(fn=fn, **kw)
        return fn

    return deco


class Ctx:
    def __init__(self, db: Session, project: Project, as_of: date, filters: dict | None = None):
        self.db, self.project, self.as_of, self.filters = db, project, as_of, filters or {}

    @cached_property
    def snap(self) -> metrics.Snapshot:
        return metrics.load(self.db, self.project, self.as_of)

    def _uuid(self, cfg: dict, key: str) -> uuid.UUID | None:
        v = cfg.get(key) or self.filters.get(key)  # the widget's own choice wins over the dashboard-wide filter
        return uuid.UUID(str(v)) if v else None

    def product(self, cfg: dict) -> uuid.UUID | None:
        return self._uuid(cfg, "product_id")

    def location(self, cfg: dict) -> uuid.UUID | None:
        return self._uuid(cfg, "location_id")


TITLE = Setting("title", "Heading (optional)", "text")  # every widget may carry its own heading
PRODUCT = Setting("product_id", "Product (empty = dashboard filter / all)", "product")
CHART = Setting("chart_type", "Chart type", "select", CHART_TYPES, "bar")


def _series(items: list[tuple[str, float | int | None, str | None]], unit: str | None = None, total: float | None = None, detail: dict | None = None) -> dict:
    series = [{"label": l, "value": v, "color": c, **({"detail": detail[l]} if detail and l in detail else {})} for l, v, c in items]
    return {"shape": "series", "series": series, "unit": unit, "total": total if total is not None else sum(v or 0 for _, v, _ in items)}


# ------------------------------------------------------------------ KPI strip
KPI_CHOICES = [("overall_pct", "Overall completion"), ("phases", "Total phases"), ("completed", "Completed activities"), ("in_progress", "In-progress activities"),
               ("overdue", "Overdue activities"), ("start_delayed", "Start delayed"), ("not_started", "Upcoming activities"), ("upcoming_milestones", "Upcoming milestones")]


@widget(type="kpi_strip", title="KPI strip", description="Headline numbers: completion, phases, activities by state, milestones. Click a number for the records behind it.", shape="kpis",
        size=(12, 2), min_size=(3, 2), sources=["plan tasks", "tracker events"],
        settings=[Setting("kpis", "Numbers to show", "multiselect", KPI_CHOICES, ["overall_pct", "phases", "completed", "in_progress", "overdue", "upcoming_milestones"]), PRODUCT])
def kpi_strip(ctx: Ctx, cfg: dict) -> dict:
    pid, snap = ctx.product(cfg), ctx.snap
    items = metrics.activity_items(snap, pid)
    comp, act = metrics.completion(items), metrics.activity_kpis(snap, pid)
    phases = len(metrics.product_view(snap, pid)["rows"]) if pid else len(metrics.overall(snap)["rows"])
    out = {
        "overall_pct": ("Overall completion", "n/a" if comp["pct_display"] is None else f"{comp['pct_display']}%", f"{comp['done']}/{comp['total']} items", NAVY, None),
        "phases": ("Total phases", phases, None, NAVY, "phases" if not pid else None),
        "completed": ("Completed activities", act["completed"], f"of {act['all']}", GREEN, "completed"),
        "in_progress": ("In-progress activities", act["in_progress"], None, AMBER, "in_progress"),
        "overdue": ("Overdue activities", act["overdue"], None, RED if act["overdue"] else GREEN, "overdue"),
        "start_delayed": ("Start delayed", act["start_delayed"], None, AMBER, "start_delayed"),
        "not_started": ("Upcoming activities", act["not_started"], None, SLATE, "not_started"),
        "upcoming_milestones": ("Upcoming milestones", act["upcoming_milestones"], None, "#b45309", "upcoming_milestones"),
    }
    chosen = cfg.get("kpis") or [k for k, _ in KPI_CHOICES]
    return {"shape": "kpis", "items": [{"key": k, "label": out[k][0], "value": out[k][1], "sub": out[k][2], "color": out[k][3], "drill": out[k][4]} for k in chosen if k in out],
            "product_id": str(pid) if pid else None}


# ------------------------------------------------------------------ breakdown by data source
SOURCES = [("activities", "Plan activities (by state)"), ("pending", "Pending items (by who holds them)"), ("delivery", "Delivery items (by status)"),
           ("gates", "Sign-off gates (by state)"), ("actions", "Actions (by status)"), ("uat", "UAT scenarios (by result)"), ("defects", "UAT defects (by status)"),
           ("integrations", "Integrations (by status)"), ("reports", "Reports + prints (by status)")]


@widget(type="breakdown", title="Status breakdown", description="How many records are in each state, for the data source you pick, as bars, a donut or a table.", shape="series",
        size=(4, 5), min_size=(3, 3), sources=["plan tasks", "tracker events", "pending items", "delivery items", "sign-off gates", "actions"],
        settings=[Setting("source", "Data source", "select", SOURCES, "activities"), CHART, PRODUCT])
def breakdown(ctx: Ctx, cfg: dict) -> dict:
    snap, src = ctx.snap, cfg.get("source") or "activities"
    if src == "activities":
        items = metrics.activity_items(snap, ctx.product(cfg))
        c = Counter("done" if i["closed"] else "overdue" if i["overdue"] else "in_progress" if i["in_progress"] else "upcoming" for i in items)
        return _series([("Completed", c["done"], GREEN), ("In progress", c["in_progress"], AMBER), ("Overdue", c["overdue"], RED), ("Upcoming", c["upcoming"], SLATE)])
    if src == "pending":
        open_ = [p for p in snap.pending if not (p.status_category in ("done", "cancelled") or p.actual_closure_date)]
        c = Counter(p.pending_with for p in open_)
        return _series([("Customer", c["customer"], RED), ("WFX", c["wfx"], NAVY), ("External partner", c["external"], AMBER), ("Internal team", c["internal"], SLATE)])
    if src == "delivery":
        c = Counter(combined_category(d) or "unclassified" for d in snap.deliveries)
        order = [("done", "Done", GREEN), ("in_progress", "In progress", AMBER), ("not_started", "Not started", SLATE), ("blocked", "Blocked", RED), ("cancelled", "Cancelled", "#cbd5e1"), ("unclassified", "Unclassified", "#e2e8f0")]
        return _series([(l, c[k], col) for k, l, col in order])
    if src == "gates":
        st = Counter("done" if gate_closed(g) else "overdue" if gate_overdue(g, snap.as_of, snap.grace) else "open" for g in snap.gates)
        return _series([("Approved", st["done"], GREEN), ("Overdue", st["overdue"], RED), ("Open", st["open"], SLATE)])
    if src == "uat":
        c = Counter(u.result for u in snap.uat if ctx.product(cfg) in (None, u.product_id))
        return _series([(trackers.RESULT_LABEL[r], c[r], trackers.RESULT_COLOR[r]) for r in trackers.RESULTS])
    if src == "defects":
        c = Counter(d.status for d in snap.defects if ctx.product(cfg) in (None, d.product_id))
        return _series([("Open", c["open"], RED), ("In fix", c["in_fix"], AMBER), ("Retest", c["retest"], "#2563eb"), ("Closed", c["closed"], GREEN), ("Rejected", c["rejected"], SLATE)])
    if src in ("integrations", "reports"):
        c = Counter(o.status_category or "unclassified" for o in (snap.integrations if src == "integrations" else snap.reports) if ctx.product(cfg) in (None, o.product_id))
        return _series([("Done", c["done"], GREEN), ("In progress", c["in_progress"], AMBER), ("Not started", c["not_started"], SLATE), ("Blocked", c["blocked"], RED), ("Cancelled", c["cancelled"], "#cbd5e1"), ("Unclassified", c["unclassified"], "#e2e8f0")])
    c = Counter(a.status for a in snap.actions)  # actions
    return _series([("Open", c["open"], SLATE), ("In progress", c["in_progress"], AMBER), ("Escalated", c["escalated"], RED), ("Resolved", c["resolved"], GREEN)])


# ------------------------------------------------------------------ delays
DIMENSIONS = [("source", "By source"), ("product", "By product"), ("party", "By party"), ("ageing", "By age"), ("owner", "By owner")]
PARTY = {"wfx": "WFX", "customer": "Customer", "joint": "Joint", "other": "Other", "unassigned": "Unassigned"}


@widget(type="delays", title="Delays", description="Everything past its date across plan, trackers, pending items, gates and development delivery, split by the dimension you pick.", shape="series",
        size=(4, 5), min_size=(3, 3), sources=["plan tasks", "tracker events", "pending items", "sign-off gates", "delivery items"],
        settings=[Setting("dimension", "Split by", "select", DIMENSIONS, "source"), CHART, Setting("limit", "Show at most", "number", default=8, minimum=1, maximum=25)])
def delays_widget(ctx: Ctx, cfg: dict) -> dict:
    d, dim, limit = metrics.delays(ctx.snap), cfg.get("dimension") or "source", int(cfg.get("limit") or 8)
    if dim == "source":
        items = [(s["label"], s["count"], RED) for s in d["sources"] if s["available"]]
    elif dim == "product":
        items = [(x["name"], x["count"], RED) for x in d["by_product"]]
    elif dim == "party":
        items = [(PARTY.get(x["party"], x["party"].title()), x["count"], RED) for x in d["by_party"]]
    elif dim == "ageing":
        items = [(f"{x['bucket']} d", x["count"], AMBER if i < 3 else RED) for i, x in enumerate(d["ageing"])]
    else:
        items = [(x["name"], x["count"], RED) for x in d["by_owner"]]
    out = _series(items[:limit])
    out["total"] = d["total"]
    return out


# ------------------------------------------------------------------ phase timeline
STATES = [("", "All"), ("overdue", "Overdue"), ("in_progress", "In progress"), ("done", "Done"), ("upcoming", "Upcoming")]


@widget(type="phase_timeline", title="Phase timeline", description="The PPT-style phase bars with month and quarter labels, today marker and milestones.", shape="timeline",
        size=(8, 8), min_size=(4, 4), sources=["plan tasks", "tracker events"],
        settings=[PRODUCT, Setting("state", "Show phases that are", "select", STATES, ""), Setting("limit", "Show at most", "number", default=25, minimum=1, maximum=60)])
def phase_timeline(ctx: Ctx, cfg: dict) -> dict:
    pid = ctx.product(cfg)
    rows = metrics.product_view(ctx.snap, pid)["rows"] if pid else metrics.overall(ctx.snap)["rows"]
    if cfg.get("state"):
        rows = [r for r in rows if r["state"] == cfg["state"]]
    return {"shape": "timeline", "rows": rows[: int(cfg.get("limit") or 25)], "as_of": ctx.as_of.isoformat(), "total": len(rows)}


# ------------------------------------------------------------------ sign-off gate tracker
def _products_with_data(snap: metrics.Snapshot) -> list[uuid.UUID]:
    ids = {e.product_id for e in snap.events} | set(snap.go_live) | {w.product_id for w in snap.tasks if w.product_id}
    return sorted((i for i in ids if i in snap.products), key=lambda i: snap.products[i].code)


@widget(type="gate_tracker", title="Sign-off gate tracker", description="Sign-off gates and go-live with planned and actual dates, plus how many blueprint approvals are in.", shape="gates",
        size=(4, 6), min_size=(3, 3), sources=["tracker events", "sign-off gates"], settings=[PRODUCT, Setting("limit", "Show at most", "number", default=12, minimum=1, maximum=40)])
def gate_tracker(ctx: Ctx, cfg: dict) -> dict:
    snap, pid = ctx.snap, ctx.product(cfg)
    gates, approvals, summary = [], {}, {}
    for p in ([pid] if pid else _products_with_data(snap)):
        pv = metrics.product_view(snap, p)
        gates += [{**g, "product": snap.products[p].code} for g in pv["gates"]]
        for a in pv["approvals"]:
            approvals[a["id"]] = a
        summary = pv["approval_summary"] if pid else {}
    if not pid:
        for k in {a["set"] for a in approvals.values()}:
            summary[k] = {"approved": sum(1 for a in approvals.values() if a["set"] == k and a["state"] == "done"), "total": sum(1 for a in approvals.values() if a["set"] == k)}
    gates.sort(key=lambda g: (g["planned"] is None, g["planned"] or ""))
    open_ = [a for a in approvals.values() if a["state"] != "done"]
    return {"shape": "gates", "gates": gates[: int(cfg.get("limit") or 12)], "approval_summary": summary, "open_approvals": open_[:10]}


# ------------------------------------------------------------------ needs attention
@widget(type="needs_attention", title="Needs attention", description="What is overdue or waiting, with the action and owner where one has been raised.", shape="attention",
        size=(4, 5), min_size=(3, 3), sources=["plan tasks", "pending items", "sign-off gates", "delivery items", "actions"],
        settings=[PRODUCT, Setting("severity", "Show", "select", [("", "All"), ("high", "High severity only")], ""), Setting("limit", "Show at most", "number", default=8, minimum=1, maximum=30)])
def needs_attention(ctx: Ctx, cfg: dict) -> dict:
    snap, pid = ctx.snap, ctx.product(cfg)
    if pid:
        items = metrics.product_view(snap, pid)["needs_attention"]
    else:
        gates = [g for p in _products_with_data(snap) for g in metrics.product_view(snap, p)["gates"]]
        items = metrics.needs_attention(snap, None, [metrics.task_item(snap, w) for w in snap.tasks], [metrics.event_item(snap, e) for e in snap.events], gates)
    if cfg.get("severity"):
        items = [i for i in items if i["severity"] == cfg["severity"]]
    return {"shape": "attention", "items": items[: int(cfg.get("limit") or 8)], "total": len(items), "product_id": str(pid) if pid else None}


# ------------------------------------------------------------------ week plan
PERIODS = [("this_week", "This week"), ("next_week", "Next week"), ("next_month", "Next month")]


@widget(type="week_plan", title="Week plan", description="What is due or planned in the period, grouped by workstream (weeks run Monday to Sunday).", shape="week",
        size=(8, 6), min_size=(4, 3), sources=["plan tasks", "tracker events", "pending items", "week plan activities"],
        settings=[Setting("period", "Period", "select", PERIODS, "next_week"), Setting("workstream", "Workstream (empty = all)", "text"), Setting("limit", "Cards per workstream", "number", default=6, minimum=1, maximum=30)])
def week_plan(ctx: Ctx, cfg: dict) -> dict:
    w = metrics.next_week(ctx.snap, cfg.get("period") or "next_week")
    groups = [g for g in w["groups"] if not cfg.get("workstream") or g["name"].lower() == str(cfg["workstream"]).strip().lower()]
    lim = int(cfg.get("limit") or 6)
    groups = [{**g, "hidden": max(0, len(g["cards"]) - lim), "cards": g["cards"][:lim]} for g in groups]
    return {"shape": "week", "week": w["week"], "groups": groups, "total_cards": sum(g["count"] for g in groups)}


# ------------------------------------------------------------------ coverage
COVERAGE_VIEWS = [("matrix", "Department × location table"), ("locations", "Compare locations"), ("departments", "Compare departments")]


@widget(type="coverage", title="Department and location coverage", description="Completed ÷ planned activities per department and location, calculated from the coverage activities.", shape="matrix",
        size=(6, 6), min_size=(3, 3), sources=["coverage activities"],
        settings=[Setting("view", "View", "select", COVERAGE_VIEWS, "matrix"), CHART, PRODUCT, Setting("location_id", "Location (empty = all)", "location")])
def coverage_widget(ctx: Ctx, cfg: dict) -> dict:
    cov = metrics.coverage(ctx.db, ctx.project, ctx.product(cfg), ctx.location(cfg))
    if not cov["available"]:
        return {"shape": "empty", "message": "No coverage activities yet. Add them under Dashboards → Dept × location."}
    view = cfg.get("view") or "matrix"
    if view == "matrix":
        return {"shape": "matrix", **cov}
    rows = cov["locations"] if view == "locations" else cov["departments"]
    return _series([(r["name"], r["pct"], GREEN if (r["pct"] or 0) >= 80 else AMBER if (r["pct"] or 0) >= 40 else RED) for r in rows], unit="%", total=cov["total"]["pct"],
                   detail={r["name"]: f"{r['completed']}/{r['planned']}" for r in rows})


# ------------------------------------------------------------------ product completion
@widget(type="product_completion", title="Product-wise completion", description="Completion % for each product, by the same formula as the status slides.", shape="series",
        size=(4, 5), min_size=(3, 3), sources=["plan tasks", "tracker events"], settings=[CHART])
def product_completion(ctx: Ctx, cfg: dict) -> dict:
    snap = ctx.snap
    rows = []
    for p in _products_with_data(snap):
        c = metrics.completion(metrics.activity_items(snap, p))
        if c["total"]:
            rows.append((snap.products[p].code, c["pct_display"], c, p))
    return _series([(code, pct, GREEN if (pct or 0) >= 80 else AMBER if (pct or 0) >= 40 else RED) for code, pct, _, _ in rows], unit="%",
                   detail={code: f"{c['done']}/{c['total']}" for code, _, c, _ in rows})


# ------------------------------------------------------------------ upcoming milestones
@widget(type="upcoming_milestones", title="Upcoming milestones", description="Open milestones and sign-offs dated on or after the report date, soonest first.", shape="table",
        size=(4, 5), min_size=(3, 3), sources=["plan tasks", "tracker events"],
        settings=[PRODUCT, Setting("days", "Within the next (days)", "number", default=90, minimum=1, maximum=730), Setting("limit", "Show at most", "number", default=8, minimum=1, maximum=30)])
def upcoming_milestones(ctx: Ctx, cfg: dict) -> dict:
    snap = ctx.snap
    horizon = snap.as_of + timedelta(days=int(cfg.get("days") or 90))
    rows = [r for r in metrics.drilldown_rows(snap, "upcoming_milestones", ctx.product(cfg)) if r["current_finish"] and r["current_finish"] <= horizon]
    rows.sort(key=lambda r: r["current_finish"])
    return {"shape": "table", "columns": [{"key": "title", "label": "Milestone"}, {"key": "product", "label": "Product"}, {"key": "owner", "label": "Owner"}, {"key": "date", "label": "Date", "kind": "date"}],
            "rows": [{"title": r["title"], "product": r["product"], "owner": r["owner"] or r["responsible"], "date": r["current_finish"].isoformat()} for r in rows[: int(cfg.get("limit") or 8)]], "total": len(rows)}


# ------------------------------------------------------------------ UAT
UAT_VIEWS = [("result", "Scenarios by result"), ("module", "Pass rate by module"), ("cycle", "Pass rate by UAT cycle"), ("defects", "Open defects by severity")]


@widget(type="uat_status", title="UAT status", description="How the UAT scenarios stand: results, pass rate by module or cycle, and open defects by severity.", shape="series",
        size=(4, 5), min_size=(3, 3), sources=["UAT scenarios", "UAT defects"], settings=[Setting("view", "View", "select", UAT_VIEWS, "result"), CHART, PRODUCT])
def uat_status(ctx: Ctx, cfg: dict) -> dict:
    u = trackers.uat_summary(ctx.db, ctx.project, ctx.as_of, ctx.product(cfg))
    if not u["available"]:
        return {"shape": "empty", "message": "No UAT scenarios yet. Add them under the UAT tab or import the UAT sheet."}
    view = cfg.get("view") or "result"
    if view == "result":
        return _series([(trackers.RESULT_LABEL[r], u["scenarios"]["by_result"][r], trackers.RESULT_COLOR[r]) for r in trackers.RESULTS])
    if view == "defects":
        col = {"critical": RED, "high": "#ea580c", "medium": AMBER, "low": SLATE}
        return _series([(k.title(), v, col[k]) for k, v in u["defects"]["open_by_severity"].items()])
    rows = u["scenarios"]["by_module" if view == "module" else "by_cycle"]
    return _series([(r["name"], r["pass_rate"], GREEN if (r["pass_rate"] or 0) >= 80 else AMBER if (r["pass_rate"] or 0) >= 40 else RED) for r in rows], unit="%", total=u["scenarios"]["pass_rate"],
                   detail={r["name"]: f"{r['passed']}/{r['total']}" for r in rows})


# ------------------------------------------------------------------ text
@widget(type="text_note", title="Text", description="A heading or a note: a title for a section, or a reading guide. Not data.", shape="text", size=(4, 2), min_size=(2, 1), sources=[],
        settings=[Setting("text", "Text", "longtext", default="Section title"), Setting("size", "Style", "select", [("heading", "Heading"), ("body", "Body text")], "heading")])
def text_note(ctx: Ctx, cfg: dict) -> dict:
    return {"shape": "text", "text": cfg.get("text") or "", "size": cfg.get("size") or "heading"}


# ------------------------------------------------------------------ default templates (read-only; duplicate to change)
def _w(i: int, type_: str, x: int, y: int, w: int, h: int, **config) -> dict:
    return {"id": f"w{i}", "type": type_, "x": x, "y": y, "w": w, "h": h, "config": config}


TEMPLATES: dict[str, dict] = {
    "status": {
        "name": "Project status (default)",
        "description": "The status-report layout: headline numbers, phase timeline, status mix, sign-offs, needs attention, next week and coverage.",
        "config": {"version": 1, "filters": {}, "widgets": [
            _w(1, "kpi_strip", 0, 0, 12, 2),
            _w(2, "phase_timeline", 0, 2, 8, 8),
            _w(3, "breakdown", 8, 2, 4, 5, source="activities", chart_type="donut"),
            _w(4, "gate_tracker", 8, 7, 4, 6),
            _w(5, "needs_attention", 0, 10, 8, 5),
            _w(6, "week_plan", 0, 15, 8, 6),
            _w(7, "coverage", 8, 13, 4, 8, view="locations", chart_type="bar"),
        ]},
    },
}


# ------------------------------------------------------------------ validation
def describe(wt: WidgetType) -> dict:
    return {"type": wt.type, "title": wt.title, "description": wt.description, "shape": wt.shape, "default_size": {"w": wt.size[0], "h": wt.size[1]},
            "min_size": {"w": wt.min_size[0], "h": wt.min_size[1]}, "sources": wt.sources,
            "settings": [{"key": s.key, "label": s.label, "kind": s.kind, "options": [{"value": v, "label": l} for v, l in s.options], "default": s.default, "min": s.minimum, "max": s.maximum} for s in [TITLE, *wt.settings]]}


def _bad(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


def validate_settings(db: Session, wt: WidgetType, cfg: Any) -> dict:
    """Checks a widget's settings against its declared settings: unknown keys, option values, numbers, text length, product and location ids."""
    if cfg is None:
        cfg = {}
    if not isinstance(cfg, dict):
        raise _bad(f"{wt.title}: settings must be an object")
    known = {s.key: s for s in [TITLE, *wt.settings]}
    out: dict = {}
    for k, v in cfg.items():
        s = known.get(k)
        if s is None:
            raise _bad(f"{wt.title}: unknown setting '{k}'")
        if v in (None, ""):
            continue
        if s.kind == "select":
            if v not in [o for o, _ in s.options]:
                raise _bad(f"{wt.title}: '{s.label}' must be one of {', '.join(o or '(any)' for o, _ in s.options)}")
        elif s.kind == "multiselect":
            allowed = {o for o, _ in s.options}
            if not isinstance(v, list) or not v or any(x not in allowed for x in v) or len(set(v)) != len(v):
                raise _bad(f"{wt.title}: '{s.label}' must be a list of distinct values from {', '.join(sorted(allowed))}")
        elif s.kind == "number":
            if isinstance(v, bool) or not isinstance(v, int) or (s.minimum is not None and v < s.minimum) or (s.maximum is not None and v > s.maximum):
                raise _bad(f"{wt.title}: '{s.label}' must be a whole number between {s.minimum} and {s.maximum}")
        elif s.kind in ("text", "longtext"):
            if not isinstance(v, str) or len(v) > (2000 if s.kind == "longtext" else 120):
                raise _bad(f"{wt.title}: '{s.label}' is too long")
        elif s.kind in ("product", "location"):
            model = Product if s.kind == "product" else Location
            try:
                ok = db.get(model, uuid.UUID(str(v))) is not None
            except ValueError:
                ok = False
            if not ok:
                raise _bad(f"{wt.title}: unknown {s.kind}")
        out[k] = v
    return out


def validate_layout(db: Session, cfg: Any) -> dict:
    """A stored layout must be well formed: known widget types, valid settings, inside the 12-column grid, no overlaps, at most 40 widgets."""
    if not isinstance(cfg, dict) or not isinstance(cfg.get("widgets"), list):
        raise _bad("A layout needs a list of widgets")
    if len(cfg["widgets"]) > MAX_WIDGETS:
        raise _bad(f"A dashboard can hold at most {MAX_WIDGETS} widgets")
    extra = set(cfg) - {"version", "filters", "widgets"}
    if extra:
        raise _bad(f"Unknown layout keys: {', '.join(sorted(extra))}")
    filters = cfg.get("filters") or {}
    if not isinstance(filters, dict) or set(filters) - {"product_id", "location_id"}:
        raise _bad("Filters may only contain product_id and location_id")
    clean_filters = {}
    for k, model in (("product_id", Product), ("location_id", Location)):
        if filters.get(k):
            try:
                ok = db.get(model, uuid.UUID(str(filters[k]))) is not None
            except ValueError:
                ok = False
            if not ok:
                raise _bad(f"Unknown {k.replace('_id', '')} in the dashboard filter")
            clean_filters[k] = str(filters[k])
    seen, boxes, widgets = set(), [], []
    for w in cfg["widgets"]:
        if not isinstance(w, dict) or set(w) - {"id", "type", "x", "y", "w", "h", "config"}:
            raise _bad("Each widget needs id, type, x, y, w, h and config")
        wt = REGISTRY.get(w.get("type"))
        if wt is None:
            raise _bad(f"Unknown widget type '{w.get('type')}'")
        wid = w.get("id")
        if not isinstance(wid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", wid) or wid in seen:
            raise _bad("Widget ids must be unique and 1-40 letters, digits, - or _")
        seen.add(wid)
        x, y, ww, hh = (w.get(k) for k in ("x", "y", "w", "h"))
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (x, y, ww, hh)):
            raise _bad(f"{wt.title}: position and size must be whole numbers")
        if x < 0 or y < 0 or ww < wt.min_size[0] or hh < wt.min_size[1] or x + ww > GRID_COLS or hh > MAX_ROWS:
            raise _bad(f"{wt.title}: outside the grid (12 columns, at least {wt.min_size[0]} × {wt.min_size[1]})")
        for bx, by, bw, bh, other in boxes:
            if x < bx + bw and bx < x + ww and y < by + bh and by < y + hh:
                raise _bad(f"{wt.title} overlaps {other}")
        boxes.append((x, y, ww, hh, wt.title))
        widgets.append({"id": wid, "type": wt.type, "x": x, "y": y, "w": ww, "h": hh, "config": validate_settings(db, wt, w.get("config"))})
    return {"version": 1, "filters": clean_filters, "widgets": widgets}


def widget_data(db: Session, project: Project, wtype: str, settings: Any, filters: Any, as_of: date) -> dict:
    wt = REGISTRY.get(wtype)
    if wt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown widget type")
    cfg = validate_settings(db, wt, settings)
    f = validate_layout(db, {"widgets": [], "filters": filters or {}})["filters"]
    return {"type": wt.type, **wt.fn(Ctx(db, project, as_of, f), cfg), "as_of": as_of.isoformat()}
