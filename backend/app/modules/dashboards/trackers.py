"""UAT, defects, integrations and reports/prints: shared rules and the summaries behind their dashboards.

  UAT scenario   to do = not run, in progress, blocked or to be retested; overdue = to do and its planned date (+ grace) has passed.
                 pass rate = passed ÷ all scenarios (executed % = (passed + failed) ÷ all).  A scenario cannot be Passed while it has an open defect.
  UAT defect     open = open, in fix or retest; overdue = open and its target date (+ grace) has passed.
  Deliverable    (integration, report or print) closed = status done / cancelled or an actual date; overdue = not closed and the current
                 target date (the latest approved revision, else the baseline) + grace has passed.
"""
import uuid
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Product, Project
from app.models.workspace import IntegrationItem, ReportItem, UatDefect, UatScenario
from app.modules.planning.delays import assess

UAT_NOT_DONE = ("not_run", "in_progress", "blocked", "retest")
DEFECT_OPEN = ("open", "in_fix", "retest")
RESULTS = ("passed", "failed", "blocked", "retest", "in_progress", "not_run")
RESULT_LABEL = {"passed": "Passed", "failed": "Failed", "blocked": "Blocked", "retest": "Retest", "in_progress": "In progress", "not_run": "Not run"}
RESULT_COLOR = {"passed": "#16a34a", "failed": "#dc2626", "blocked": "#7c3aed", "retest": "#d97706", "in_progress": "#2563eb", "not_run": "#94a3b8"}
SEVERITY_ORDER = ("critical", "high", "medium", "low")
UAT_FORMULA = "Pass rate = passed ÷ all scenarios. Executed = (passed + failed) ÷ all scenarios. A scenario is overdue when it still has to be run (not run, in progress, blocked or retest) and its planned date has passed."


def scenario_overdue(u: UatScenario, as_of: date, grace: int = 0) -> bool:
    return u.result in UAT_NOT_DONE and u.planned_date is not None and u.planned_date + timedelta(days=grace) < as_of


def defect_overdue(d: UatDefect, as_of: date, grace: int = 0) -> bool:
    return d.status in DEFECT_OPEN and d.target_date is not None and d.target_date + timedelta(days=grace) < as_of


def deliverable_state(o: Any, as_of: date, grace: int = 0):
    """(closed, assessment) for an integration or report item."""
    closed = o.status_category in ("done", "cancelled") or o.actual_date is not None
    return closed, assess(None, o.target_date, None, o.revised_target_date, "done" if closed else None, None, o.actual_date, as_of, grace)


def _pct(n: int, d: int) -> float | None:
    return round(n / d * 100, 1) if d else None


def uat_summary(db: Session, project: Project, as_of: date, product_id: uuid.UUID | None = None) -> dict:
    grace = project.delay_grace_days or 0
    sq = select(UatScenario).where(UatScenario.project_id == project.id)
    dq = select(UatDefect).where(UatDefect.project_id == project.id)
    if product_id:
        sq, dq = sq.where(UatScenario.product_id == product_id), dq.where(UatDefect.product_id == product_id)
    scenarios, defects = list(db.scalars(sq)), list(db.scalars(dq))
    by_result = Counter(u.result for u in scenarios)
    total = len(scenarios)

    def group(key) -> list[dict]:
        g: dict[str, Counter] = defaultdict(Counter)
        for u in scenarios:
            g[key(u) or "(none)"][u.result] += 1
        return sorted(({"name": k, "total": sum(c.values()), **{r: c[r] for r in RESULTS}, "pass_rate": _pct(c["passed"], sum(c.values()))} for k, c in g.items()), key=lambda r: (-r["total"], r["name"]))

    open_def = [d for d in defects if d.status in DEFECT_OPEN]
    sev = Counter(d.severity for d in open_def)
    return {
        "available": bool(scenarios or defects), "as_of": as_of.isoformat(), "formula": UAT_FORMULA,
        "scenarios": {"total": total, "by_result": {r: by_result[r] for r in RESULTS}, "pass_rate": _pct(by_result["passed"], total),
                      "executed_pct": _pct(by_result["passed"] + by_result["failed"], total), "to_do": sum(by_result[r] for r in UAT_NOT_DONE),
                      "overdue": sum(1 for u in scenarios if scenario_overdue(u, as_of, grace)), "by_module": group(lambda u: u.module), "by_cycle": group(lambda u: u.cycle)},
        "defects": {"total": len(defects), "open": len(open_def), "closed": sum(1 for d in defects if d.status == "closed"), "rejected": sum(1 for d in defects if d.status == "rejected"),
                    "open_by_severity": {s: sev[s] for s in SEVERITY_ORDER}, "by_status": {k: sum(1 for d in defects if d.status == k) for k in ("open", "in_fix", "retest", "closed", "rejected")},
                    "overdue": sum(1 for d in defects if defect_overdue(d, as_of, grace)),
                    "oldest_open_days": max([(as_of - d.raised_on).days for d in open_def if d.raised_on], default=None)},
    }


def deliverables_summary(db: Session, project: Project, as_of: date, product_id: uuid.UUID | None = None) -> dict:
    grace = project.delay_grace_days or 0
    prods = {p.id: p.code for p in db.scalars(select(Product))}
    out: dict[str, Any] = {"as_of": as_of.isoformat(), "available": False,
                           "formula": "Overdue = not closed and the current target date (latest approved revision, else the baseline) + grace days has passed. Closed = status done or cancelled, or an actual date."}
    for key, model in (("integrations", IntegrationItem), ("reports", ReportItem)):
        q = select(model).where(model.project_id == project.id)
        if product_id:
            q = q.where(model.product_id == product_id)
        rows = list(db.scalars(q))
        cats = Counter(o.status_category or "unclassified" for o in rows)
        st = [deliverable_state(o, as_of, grace) for o in rows]
        due_soon = sum(1 for o, (c, a) in zip(rows, st) if not c and a.effective_finish and as_of <= a.effective_finish <= as_of + timedelta(days=14))
        out[key] = {"total": len(rows), "by_status": {k: cats[k] for k in ("not_started", "in_progress", "done", "blocked", "cancelled", "unclassified")},
                    "overdue": sum(1 for c, a in st if a.overdue), "due_in_14_days": due_soon, "closed": sum(1 for c, _ in st if c),
                    "done_pct": _pct(sum(1 for c, _ in st if c), len(rows)), "by_product": dict(Counter(prods.get(o.product_id, "Project-wide") for o in rows)),
                    **({"reports_count": sum(o.reports_count or 0 for o in rows)} if key == "reports" else {})}
        out["available"] = out["available"] or bool(rows)
    return out
