"""Dependency analysis for the plan: how much room each link has, which links are violated, and which milestones are critical.

Dependencies are finish-to-start with an optional lag:  successor start >= predecessor finish + lag.
All dates are the CURRENT dates (latest approved revision, else baseline), as everywhere else.

  slack_days  = successor start - (predecessor finish + lag), in days; negative = the successor starts too early (violated)
  violated    = slack < 0
  critical    = the predecessor is still open and slack <= 0 (the successor cannot slip without the predecessor finishing on time)
  blocked_by_late = some predecessor is open and overdue
  critical milestone = an open milestone that is overdue, or has a critical incoming link, or is blocked by a late predecessor
"""
from datetime import date
from typing import Any, Iterable

from app.modules.planning.delays import assess


def current_range(w: Any) -> tuple[date | None, date | None]:
    return (w.revised_start or w.planned_start, w.revised_finish or w.planned_finish)


def analyse(items: Iterable[Any], deps: Iterable[Any], as_of: date, grace: int = 0) -> tuple[dict, dict]:
    """Returns (links, nodes): links[dep.id] -> {slack_days, violated, critical}; nodes[item.id] -> {critical_milestone, blocked_by_late}."""
    by = {w.id: w for w in items}
    state = {}
    for w in by.values():
        a = assess(w.planned_start, w.planned_finish, w.revised_start, w.revised_finish, w.status_category, w.actual_start, w.actual_finish, as_of, grace)
        state[w.id] = (a.closed, a.overdue)
    links: dict = {}
    nodes = {i: {"critical_milestone": False, "blocked_by_late": False} for i in by}
    critical_in: set = set()
    for d in deps:
        p, s = by.get(d.predecessor_id), by.get(d.successor_id)
        if p is None or s is None:
            continue
        pf, ss = current_range(p)[1], current_range(s)[0]
        slack = None if pf is None or ss is None else (ss - pf).days - (d.lag_days or 0)
        p_closed, p_over = state[p.id]
        crit = (not p_closed) and slack is not None and slack <= 0
        links[d.id] = {"slack_days": slack, "violated": slack is not None and slack < 0, "critical": crit}
        if crit:
            critical_in.add(s.id)
        if (not p_closed) and p_over:
            nodes[s.id]["blocked_by_late"] = True
    for i, w in by.items():
        closed, over = state[i]
        if w.kind == "milestone" and not closed and (over or i in critical_in or nodes[i]["blocked_by_late"]):
            nodes[i]["critical_milestone"] = True
    return links, nodes
