"""Delivery lifecycle: when is a ticket closed, late, or past its start? Pure functions, shared by the records API and the dashboards.

Stage dates in the Shahi sheets are PLANNED dates (only the customer spec closure also has an actual). So a stage is never marked
done just because its date passed; it is shown as 'done' only when the ticket itself is closed (status, helpdesk status, an actual
completion), or, for the first two stages, when there is evidence (actual spec closure; work started).

  closed        = status done/cancelled, or helpdesk status done/cancelled, or an actual completion.
                  ('Completed' under the SPECS target date means the specs are done, not the delivery, so it does not close a ticket.)
  delivery date = latest APPROVED revision, otherwise the baseline derived once from the stage dates
                  (customer UAT release, else UAT release, else QA release, else dev completion)
  overdue       = not closed and delivery date + grace < as-of date
  start delayed = not closed, not overdue, work not started (no in-progress status) and dev initiation + grace < as-of date
"""
from datetime import date, timedelta
from typing import Any

from app.modules.planning.delays import CLOSED, assess

STAGES = (  # (key, label, date attribute)
    ("spec_closure", "Customer spec closure", "spec_closure_date"),
    ("dev_initiation", "Dev initiation", "dev_initiation"),
    ("dev_completion", "Handover to QA", "dev_completion"),
    ("qa_release", "QA release", "qa_release"),
    ("uat_release", "Release to UAT server", "uat_release"),
    ("customer_release", "Customer UAT release", "customer_release"),
    ("customer_uat_closure", "Customer UAT closure", "customer_uat_closure"),
)


def is_closed(d: Any) -> bool:
    return (d.status_category in CLOSED) or (d.helpdesk_status_category in CLOSED) or d.actual_completion is not None


def has_started(d: Any) -> bool:
    return d.status_category in ("in_progress", "done") or d.helpdesk_status_category in ("in_progress", "done")


def combined_category(d: Any) -> str | None:
    if is_closed(d):
        return "done"
    if has_started(d):
        return "in_progress"
    return d.status_category or d.helpdesk_status_category


def assess_delivery(d: Any, as_of: date, grace: int = 0):
    return assess(d.dev_initiation, d.delivery_target_date, None, d.revised_target_date, combined_category(d), None, d.actual_completion, as_of, grace)


def stages(d: Any, as_of: date, grace: int = 0) -> list[dict]:
    closed, started = is_closed(d), has_started(d)
    out = []
    for key, label, attr in STAGES:
        when = getattr(d, attr)
        if closed:
            state = "done"
        elif key == "spec_closure" and d.spec_closure_actual:
            state, when = "done", d.spec_closure_actual
        elif key == "dev_initiation" and started:
            state = "done"
        elif when and when + timedelta(days=grace) < as_of:
            state = "late"
        else:
            state = "upcoming" if when else "none"
        out.append({"key": key, "label": label, "date": when.isoformat() if when else None, "state": state})
    return out


def delivery_extras(d: Any, as_of: date, grace: int = 0) -> dict:
    a = assess_delivery(d, as_of, grace)
    return {"is_closed": a.closed, "is_overdue": a.overdue, "is_start_delayed": a.start_delayed, "days_late": a.days_late,
            "slippage_days": a.slippage_days, "effective_target_date": a.effective_finish.isoformat() if a.effective_finish else None,
            "stages": stages(d, as_of, grace)}
