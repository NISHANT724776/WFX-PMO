"""Suggests which dashboard templates the mapped data can support. No numbers are computed here: it only reports
whether the *fields* a template needs exist. Metrics are calculated later by the deterministic dashboard engine."""
from app.modules.excel_intel.catalog import ENTITIES

TEMPLATES = [
    {
        "key": "overall_status", "label": "Overall Project Status",
        "needs": {"plan_task": ["phase", "planned_start", "planned_finish", "status"]},
        "mode": "all", "reference": "Tegra PPT slide 3",
    },
    {
        "key": "product_coverage", "label": "Product Coverage and Status",
        "needs": {"plan_task": ["phase", "planned_start", "planned_finish", "status"], "tracker_event": ["event_name", "planned_date"]},
        "mode": "any", "reference": "Tegra PPT slides 4-8",
    },
    {
        "key": "signoff_gates", "label": "Sign-Off Gate Tracker panel",
        "needs": {"approval_gate": ["name", "approval_status"]},
        "mode": "all", "reference": "Right panel of PPT slides 4-8",
    },
    {
        "key": "next_week_plan", "label": "Next Week / This Week Plan",
        "needs": {"plan_task": ["title", "planned_finish"], "gap_specification": ["description", "target_date"], "tracker_event": ["event_name", "planned_date"], "dependency_item": ["description", "original_target_date"], "delivery_schedule": ["description", "qa_release"], "tech_tracker": ["description", "qa_release"]},
        "mode": "any", "reference": "Tegra PPT slide 9",
    },
    {
        "key": "delay_dashboard", "label": "Delay Dashboard",
        "needs": {"plan_task": ["planned_finish", "status"], "tracker_event": ["planned_date", "actual_date"], "gap_specification": ["target_date", "spec_status"], "approval_gate": ["planned_date", "approval_status"], "dependency_item": ["original_target_date"], "delivery_schedule": ["description", "qa_release"], "tech_tracker": ["description", "qa_release"]},  # status is derived from the closure date when there is no status column
        "mode": "any", "reference": "Brief item 7",
    },
]


def _label(entity: str, field: str) -> str:
    f = ENTITIES[entity].field(field)
    return f.label if f else field


def suggest(mapped: dict[str, set[str]]) -> list[dict]:
    """mapped: entity -> set of mapped field keys (from sheets that are enabled)."""
    out = []
    for t in TEMPLATES:
        sources, missing = [], {}
        for entity, fields in t["needs"].items():
            have = mapped.get(entity)
            if have is None:
                continue
            miss = [f for f in fields if f not in have]
            if not miss:
                sources.append(entity)
            else:
                missing[entity] = [_label(entity, f) for f in miss]
        available = (len(sources) == len(t["needs"])) if t["mode"] == "all" else bool(sources)
        note = None
        if t["key"] == "product_coverage" and "plan_task" in sources:
            note = "Plan tasks carry no product column, so they appear project-wide; tracker events and gates are per product."
        if not available and not sources and not any(e in mapped for e in t["needs"]):
            note = "None of the data this template needs was found in the workbook."
        out.append({"key": t["key"], "label": t["label"], "reference": t["reference"], "available": available,
                    "sources": sources, "missing": missing, "note": note})
    return out
