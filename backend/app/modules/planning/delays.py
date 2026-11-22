"""The one place that decides whether a plan item is late. Pure functions, no database.

Rule (grace days are a per-project setting, default 0 until the business decides):
  closed        = status category done/cancelled, or an actual finish exists
  overdue       = not closed and effective finish + grace < as-of date
  start_delayed = not overdue, nothing started, and effective start + grace < as-of date
  effective date = latest APPROVED revision, otherwise the baseline
Slippage is always measured against the BASELINE so revising a date never hides a delay.
"""
from dataclasses import dataclass
from datetime import date, timedelta

CLOSED = ("done", "cancelled")


@dataclass
class DelayInfo:
    effective_start: date | None
    effective_finish: date | None
    closed: bool
    overdue: bool
    start_delayed: bool
    days_late: int  # vs effective finish, after grace; 0 if not overdue
    slippage_days: int  # effective finish minus baseline finish (>0 = pushed out)


def assess(
    planned_start: date | None, planned_finish: date | None, revised_start: date | None, revised_finish: date | None,
    status_category: str | None, actual_start: date | None, actual_finish: date | None, as_of: date, grace: int = 0,
) -> DelayInfo:
    es, ef = revised_start or planned_start, revised_finish or planned_finish
    closed = status_category in CLOSED or actual_finish is not None
    overdue = (not closed) and ef is not None and ef + timedelta(days=grace) < as_of
    started = actual_start is not None or status_category in ("in_progress", "done")
    start_delayed = (not closed) and (not overdue) and (not started) and es is not None and es + timedelta(days=grace) < as_of
    days_late = (as_of - ef).days - grace if overdue and ef else 0
    slip = (ef - planned_finish).days if ef and planned_finish else 0
    return DelayInfo(es, ef, closed, overdue, start_delayed, max(days_late, 0), slip)
