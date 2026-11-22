"""Approval (sign-off) gate rules, in one place.

A gate is CLOSED (approved) when its approval category is 'done'. Gates imported from a workbook carry only the status text, so until a person
changes them (approval_category is empty) the old rule applies: a sign-off date, or a status starting with 'approved'.
A gate is OVERDUE when it is not closed and its planned date + grace days has passed.
"""
from datetime import date, timedelta
from typing import Any


def gate_closed(g: Any) -> bool:
    if g.approval_category:
        return g.approval_category == "done"
    return bool(g.signoff_date) or (g.approval_status or "").lower().startswith("approved")


def gate_overdue(g: Any, as_of: date, grace: int = 0) -> bool:
    return (not gate_closed(g)) and g.planned_date is not None and g.planned_date + timedelta(days=grace) < as_of


def gate_days_late(g: Any, as_of: date, grace: int = 0) -> int:
    return max(0, (as_of - g.planned_date).days - grace) if gate_overdue(g, as_of, grace) else 0
