"""Phase 4: dashboards. Every number is checked against counts computed straight from the raw Tegra workbooks."""
import io
import re
import warnings
from collections import Counter
from datetime import date, timedelta

import openpyxl
from pptx import Presentation

from test_phase2 import PLAN, V3, get, import_tracker, setup_project, upload  # noqa: E402
from test_phase3 import import_plan, new_item  # noqa: E402

warnings.filterwarnings("ignore")
API = "/api/v1"
AS_OF = "2026-11-17"
AO = date.fromisoformat(AS_OF)
GATE = re.compile(r"sign[\s-]?off|approval|acceptance|go[\s-]?live", re.I)
PAIRS = {"PLM": (4, 5), "ERP": (6, 7), "PLAN": (8, 9), "WMS": (10, 11), "MES": (12, 13), "FINANCE": (14, 15)}


def dt(v):
    return v.date() if hasattr(v, "date") else None


def raw_events():
    """[(product_code, name, planned, actual, responsibility)] straight from the Master Sheet."""
    ws = openpyxl.load_workbook(V3, data_only=True)["Master Sheet"]
    out = []
    for r in range(3, ws.max_row + 1):
        name = ws.cell(r, 1).value
        if not name:
            continue
        for code, (p, a) in PAIRS.items():
            pd_, ad = dt(ws.cell(r, p).value), dt(ws.cell(r, a).value)
            if pd_ or ad:
                out.append((code, name, pd_, ad, ws.cell(r, 2).value))
    return out


def raw_tasks():
    ws = openpyxl.load_workbook(PLAN, data_only=True).active
    out = []
    for row in ws.iter_rows(min_row=3, values_only=True):
        if not row[1]:
            continue
        status, start, end, a_start, a_end = row[10], dt(row[4]), dt(row[5]), dt(row[7]), dt(row[8])
        closed = status == "Done" or a_end is not None
        out.append({"phase": row[0], "status": status, "start": start, "end": end, "closed": closed, "ip": status == "In-Progress" and not closed,
                    "started": a_start is not None or status in ("In-Progress", "Done") or closed,
                    "over": (not closed) and end < AO, "responsible": row[2], "title": row[1]})
    return out


def row_state(items, as_of=AO):
    """items: dicts with closed/started/start/end. Independent re-statement of the legend in the status slides:
    overdue = some open item is past its end date, or has not started although its start date has passed."""
    if all(i["closed"] for i in items):
        return "done"
    if any(not i["closed"] and (i["end"] < as_of or (not i["started"] and i["start"] < as_of)) for i in items):
        return "overdue"
    return "in_progress" if any(i["started"] for i in items) else "upcoming"


def full_setup(client, admin):
    pid, prods = setup_project(client, admin)
    import_plan(client, admin, pid)
    _, r = import_tracker(client, admin, prods, pid)
    assert r.status_code == 200, r.text
    return pid, prods


def dash(client, hdr, pid, path, **params):
    q = "&".join([f"as_of={params.pop('as_of', AS_OF)}"] + [f"{k}={v}" for k, v in params.items()])
    return get(client, hdr, f"/projects/{pid}/dashboards/{path}?{q}")


# ======================================================================= A. overall status
def test_overall_matches_independent_oracle(client, admin):
    pid, prods = full_setup(client, admin)
    tasks, events = raw_tasks(), raw_events()
    p = dash(client, admin, pid, "overall")
    ov = p["kpis"]["overall"]
    done = sum(t["closed"] for t in tasks) + sum(1 for e in events if e[3])
    ip = sum(t["ip"] for t in tasks)
    total = len(tasks) + len(events)
    assert (ov["total"], ov["done"], ov["in_progress"]) == (total, done, ip)
    assert ov["pct"] == round((done + 0.5 * ip) / total * 100, 1) and ov["pct_display"] == int((done + 0.5 * ip) / total * 100 + 0.5)
    assert ov["numerator"] == done + 0.5 * ip and ov["denominator"] == total and "½ In Progress" in ov["formula"]
    # phase rows: 16 plan phases + one tracker row per product that has events
    by_phase = {}
    for t in tasks:
        by_phase.setdefault(t["phase"], []).append(t)
    by_prod = {}
    for e in events:
        by_prod.setdefault(e[0], []).append({"closed": bool(e[3]), "started": bool(e[3]), "start": e[2] or e[3], "end": e[2] or e[3]})
    expected = Counter([row_state(v) for v in by_phase.values()] + [row_state(v) for v in by_prod.values()])
    k = p["kpis"]
    assert (k["completed"]["value"], k["in_progress"]["value"], k["overdue"]["value"], k["upcoming"]["value"]) == (expected["done"], expected["in_progress"], expected["overdue"], expected["upcoming"])
    assert len(p["rows"]) == len(by_phase) + len(by_prod) == 16 + 6
    assert sum(k[x]["value"] for x in ("completed", "in_progress", "overdue", "upcoming")) == len(p["rows"])
    # a phase row matches its own tasks
    kick = next(r for r in p["rows"] if r["label"] == "Project Kick Off")
    assert (kick["state"], kick["pct"], kick["items"], kick["start"], kick["end"]) == ("done", 100, 4, "2026-02-02", "2026-02-02")
    bbp = next(r for r in p["rows"] if r["label"] == "Blueprint Submission & Scope Conclusion")
    mine = by_phase["Blueprint Submission & Scope Conclusion"]
    assert bbp["state"] == row_state(mine) and bbp["items"] == len(mine) and bbp["done"] == sum(t["closed"] for t in mine)
    assert {r["area"] for r in p["rows"] if r["kind"] == "phase"} == {"Project-wide"}  # nothing is tagged to a product yet
    assert {r["area"] for r in p["rows"] if r["kind"] == "events"} == {"PLM", "ERP", "PLAN", "WMS", "MES", "FINANCE"}
    assert p["as_of"] == AS_OF and p["meta"]["formulas"]["completion"] if "meta" in p else p["formulas"]["completion"]


def test_changing_the_report_date_recalculates(client, admin):
    pid, _ = full_setup(client, admin)
    late_now = dash(client, admin, pid, "overall")["kpis"]["overdue"]["value"]
    early = dash(client, admin, pid, "overall", as_of="2026-03-01")
    assert early["kpis"]["overdue"]["value"] < late_now  # almost nothing was due by March
    assert early["as_of"] == "2026-03-01"


def test_phase_tagging_changes_area_and_product_scope(client, admin):
    pid, prods = full_setup(client, admin)
    phases = get(client, admin, f"/projects/{pid}/phases")
    mes = next(p for p in phases if p["name"].startswith("MES – Current State"))
    n = len([t for t in raw_tasks() if t["phase"] == mes["name"]])
    before_plm = dash(client, admin, pid, f"product/{prods['PLM']}")["kpis"]["overall"]["total"]
    client.post(f"{API}/projects/{pid}/phases/{mes['id']}/assign-product", json={"product_id": prods["MES"]}, headers=admin)
    assert dash(client, admin, pid, f"product/{prods['PLM']}")["kpis"]["overall"]["total"] == before_plm - n  # PLM no longer shows MES-only tasks
    mes_total = dash(client, admin, pid, f"product/{prods['MES']}")["kpis"]["overall"]["total"]
    assert mes_total == len(raw_tasks()) + len([e for e in raw_events() if e[0] == "MES"])
    row = next(r for r in dash(client, admin, pid, "overall")["rows"] if r["label"] == mes["name"])
    assert row["area"] == "MES"


# ======================================================================= B. product coverage and status
def test_product_view_matches_oracle_and_the_status_slide_facts(client, admin):
    pid, prods = full_setup(client, admin)
    client.patch(f"{API}/projects/{pid}", json={"target_go_live": "2027-06-01"}, headers=admin)
    tasks, events = raw_tasks(), raw_events()
    plm = [e for e in events if e[0] == "PLM"]
    p = dash(client, admin, pid, f"product/{prods['PLM']}")
    k = p["kpis"]
    done = sum(t["closed"] for t in tasks) + sum(1 for e in plm if e[3])
    total = len(tasks) + len(plm)
    assert (k["items"]["done"], k["items"]["total"]) == (done, total)
    late_tasks = sum(1 for t in tasks if t["over"]) + sum(1 for t in tasks if not t["closed"] and not t["over"] and not t["started"] and t["start"] < AO)
    late_events = sum(1 for e in plm if not e[3] and e[2] and e[2] < AO)
    assert k["late"]["value"] == late_tasks + late_events and len(k["late"]["refs"]) == late_tasks + late_events
    # sign-off gates for PLM, straight from the Master Sheet's gate-like events
    exp_gates = [e for e in plm if GATE.search(e[1])]
    names = [g["name"] for g in p["gates"] if g["type"] == "event"]
    assert sorted(names) == sorted(e[1] for e in exp_gates)
    sign = next(g for g in p["gates"] if g["name"] == "Business Blueprint Sign off")
    assert (sign["planned"], sign["actual"], sign["state"]) == ("2026-05-21", "2026-08-14", "done")  # slide 4: "14-Aug-26 (plan 21-May)"
    # next gate = nearest not-done gate on/after the report date
    exp_next = min((e for e in exp_gates if not e[3] and e[2] and e[2] >= AO), key=lambda e: e[2])
    assert (k["next_gate"]["name"], k["next_gate"]["planned"]) == (exp_next[1], exp_next[2].isoformat())
    assert k["go_live"] == "2027-06-01" and p["gates"][-1]["name"] == "GO-LIVE" and p["gates"][-1]["state"] == "planned"
    # the ERP page has the same gate overdue (slide 4/5: BBP Sign-Off ERP overdue since 21-May)
    erp = dash(client, admin, pid, f"product/{prods['ERP']}")
    g = next(x for x in erp["gates"] if x["name"] == "Business Blueprint Sign off")
    assert g["state"] == "overdue" and g["actual"] is None
    assert any("Business Blueprint Sign off overdue since 21-May-26" in a["text"] for a in erp["needs_attention"])
    # blueprint approvals by department come from the imported sheet (no invented site matrix)
    ws = openpyxl.load_workbook(V3, data_only=True)["Blue Printing Signoff"]
    rows = [r for r in ws.iter_rows(min_row=5, values_only=True) if r[0]]
    assert p["approval_summary"]["blue_printing_signoff"] == {"approved": sum(1 for r in rows if str(r[4]).startswith("Approved")), "total": len(rows)}
    assert p["approval_summary"]["e2e"] == {"approved": 0, "total": 4}  # reported separately, not blended into the blueprint figure
    assert any("location dimension" in n for n in p["notes"])


def test_needs_attention_covers_every_kind_with_valid_references(client, admin):
    pid, prods = full_setup(client, admin)
    late = next(i for i in get(client, admin, f"/projects/{pid}/work-items?size=500&as_of={AS_OF}")["items"] if i["is_overdue"])
    other = new_item(client, admin, pid, title="Waits for the late sign-off")
    client.post(f"{API}/projects/{pid}/work-items/{other['id']}/dependencies", json={"predecessor_id": late["id"]}, headers=admin)
    client.post(f"{API}/projects/{pid}/work-items/{late['id']}/revisions", json={"field": "planned_finish", "new_date": "2027-01-15", "reason": "Customer delay"}, headers=admin)  # proposed only
    client.post(f"{API}/projects/{pid}/pending-items", json={"pending_with": "customer", "description": "Tegra to confirm scope", "original_target_date": "2026-11-01"}, headers=admin)
    na = dash(client, admin, pid, f"product/{prods['ERP']}")["needs_attention"]  # ERP: its blueprint sign-off is overdue
    kinds = {a["kind"] for a in na}
    assert {"gate", "task", "pending", "approval", "spec", "dependency"} <= kinds
    assert [a["severity"] for a in na] == sorted((a["severity"] for a in na), key=lambda s: s != "high")  # high first
    dep = next(a for a in na if a["kind"] == "dependency")
    assert late["title"] in dep["text"] and "blocks 1 dependent" in dep["text"]
    pend = next(a for a in na if a["kind"] == "pending")
    assert "pending with Customer" in pend["text"] and "Tegra to confirm scope" in pend["text"]
    task_ref = next(a for a in na if a["kind"] == "task")["refs"][0]
    assert client.get(f"{API}/projects/{pid}/work-items/{task_ref['id']}", headers=admin).status_code == 200  # drill-down target exists


def test_edit_a_task_and_the_dashboard_follows(client, admin):
    """Steps 15-18 of the first slice: open the source records behind a number, update one, see the dashboard change."""
    pid, prods = full_setup(client, admin)
    before = dash(client, admin, pid, f"product/{prods['PLM']}")["kpis"]
    ref = next(r for r in before["late"]["refs"] if r["type"] == "task")
    task = get(client, admin, f"/projects/{pid}/work-items/{ref['id']}?as_of={AS_OF}")
    assert task["is_overdue"] or task["is_start_delayed"]
    r = client.patch(f"{API}/projects/{pid}/work-items/{ref['id']}", json={"status": "done", "actual_finish": "2026-11-16"}, headers=admin)
    assert r.status_code == 200
    after = dash(client, admin, pid, f"product/{prods['PLM']}")["kpis"]
    assert after["items"]["done"] == before["items"]["done"] + 1 and after["late"]["value"] == before["late"]["value"] - 1
    assert after["overall"]["pct"] > before["overall"]["pct"]
    assert after["overall"]["pct"] == round((after["overall"]["done"] + 0.5 * after["overall"]["in_progress"]) / after["overall"]["total"] * 100, 1)


# ======================================================================= C. next week plan
def test_week_bounds_are_monday_to_sunday(client, admin):
    pid, _ = setup_project(client, admin)
    for period, (s, e) in {"this_week": ("2026-11-16", "2026-11-22"), "next_week": ("2026-11-23", "2026-11-29"), "next_month": ("2026-12-01", "2026-12-31")}.items():
        w = dash(client, admin, pid, "next-week", period=period)["week"]
        assert (w["start"], w["end"]) == (s, e)
        if period != "next_month":
            assert date.fromisoformat(w["start"]).weekday() == 0 and date.fromisoformat(w["end"]).weekday() == 6
    assert client.get(f"{API}/projects/{pid}/dashboards/next-week?period=forever", headers=admin).status_code == 422


def test_next_week_cards_match_independent_counts(client, admin):
    pid, prods = full_setup(client, admin)
    s, e = date(2026, 11, 23), date(2026, 11, 29)
    p = dash(client, admin, pid, "next-week", period="next_week")
    cards = [c for g in p["groups"] for c in g["cards"]]
    # tracker milestones due in the week and not done
    exp_events = [x for x in raw_events() if x[2] and s <= x[2] <= e and not x[3]]
    assert len([c for c in cards if c["source"]["type"] == "event" and c["tag"] == "due"]) == len(exp_events)
    # plan tasks due in the week, or starting in it and not started, not closed
    due = [t for t in raw_tasks() if not t["closed"] and s <= t["end"] <= e]
    starts = [t for t in raw_tasks() if not t["closed"] and not (s <= t["end"] <= e) and s <= t["start"] <= e and not t["started"]]
    assert len([c for c in cards if c["source"]["type"] == "task" and c["tag"] == "due"]) == len(due)
    assert len([c for c in cards if c["source"]["type"] == "task" and c["tag"] == "starts"]) == len(starts)
    # gap specs are aggregated per team; the counts inside add up to the rows due that week
    ws = openpyxl.load_workbook(V3, data_only=True)["Gap Tracker"]
    exp_gaps = sum(1 for r in range(3, ws.max_row + 1) if dt(ws.cell(r, 14).value) and s <= dt(ws.cell(r, 14).value) <= e and not dt(ws.cell(r, 17).value))
    gap_cards = [c for c in cards if c["source"]["type"] == "gap_group"]
    assert exp_gaps > 0 and sum(len(c["source"]["ids"]) for c in gap_cards) == exp_gaps
    assert all(re.search(r"\(\d+\)$", c["title"]) for c in gap_cards)
    # structure: numbered 1..n in order, overdue carry-overs labelled and capped
    assert [c["seq"] for g in p["groups"] for c in g["cards"]] == list(range(1, len(cards) + 1)) and p["total_cards"] == len(cards)
    for g in p["groups"]:
        co = [c for c in g["cards"] if c["tag"] == "carry_over"]
        assert len(co) <= 5 and all(c["days_late"] > 0 for c in co)
        assert [c["tag"] == "carry_over" for c in g["cards"]] == sorted(c["tag"] == "carry_over" for c in g["cards"])  # carry-overs come last
        due_dates = [c["due"] for c in g["cards"] if c["tag"] != "carry_over"]
        assert due_dates == sorted(due_dates)
    # without carry-overs the same period has no overdue cards
    assert p["groups"] and any(c["tag"] == "carry_over" for c in cards)


# ======================================================================= F. delays
def test_delay_dashboard_matches_independent_counts_by_source(client, admin):
    pid, prods = full_setup(client, admin)
    p = dash(client, admin, pid, "delays")
    src = {x["key"]: x for x in p["sources"]}
    tasks, events = raw_tasks(), raw_events()
    exp_tasks = sum(1 for t in tasks if t["over"]) + sum(1 for t in tasks if not t["closed"] and not t["over"] and not t["started"] and t["start"] < AO)
    exp_events = sum(1 for e in events if not e[3] and e[2] and e[2] < AO)
    wsg = openpyxl.load_workbook(V3, data_only=True)["Gap Tracker"]
    exp_gaps = sum(1 for r in range(3, wsg.max_row + 1) if dt(wsg.cell(r, 14).value) and dt(wsg.cell(r, 14).value) < AO and not dt(wsg.cell(r, 17).value)
                   and not str(wsg.cell(r, 18).value or "").lower().startswith("approved"))
    assert src["plan_task"]["count"] == exp_tasks and src["tracker_event"]["count"] == exp_events and src["gap_specification"]["count"] == exp_gaps
    assert src["pending_item"]["available"] is False and src["pending_item"]["count"] is None  # nothing imported: greyed, not zero
    dev = src["delivery_item"]
    assert dev["available"] is False and dev["count"] is None  # no delivery tracker imported: greyed, not zero
    assert p["total"] == sum(x["count"] or 0 for x in p["sources"]) == len(p["rows"])
    assert sum(a["count"] for a in p["ageing"]) == sum(1 for r in p["rows"] if r["days_late"] > 0)
    assert [r["days_late"] for r in p["rows"]] == sorted((r["days_late"] for r in p["rows"]), reverse=True)
    assert sum(b["count"] for b in p["by_product"]) == p["total"] and sum(b["count"] for b in p["by_party"]) == p["total"]
    # Customer vs WFX: plan tasks owned by Tegra are the customer's
    t = next(r for r in p["rows"] if r["source"] == "plan_task" and r["responsibility"] == "Tegra")
    assert t["party"] == "customer"
    assert any(b["party"] == "wfx" for b in p["by_party"])


def test_delays_never_hide_slippage_and_pending_items_join_in(client, admin):
    pid, _ = full_setup(client, admin)
    late = next(i for i in get(client, admin, f"/projects/{pid}/work-items?size=500&as_of={AS_OF}")["items"] if i["is_overdue"])
    base = dash(client, admin, pid, "delays")
    client.post(f"{API}/projects/{pid}/work-items/{late['id']}/revisions", json={"field": "planned_finish", "new_date": "2026-12-31", "reason": "Re-baselined with customer", "approve": True}, headers=admin)
    c1 = client.post(f"{API}/projects/{pid}/pending-items", json={"pending_with": "customer", "description": "Tegra input", "original_target_date": "2026-11-10"}, headers=admin).json()
    client.post(f"{API}/projects/{pid}/pending-items", json={"pending_with": "wfx", "description": "WFX input", "original_target_date": "2026-11-12"}, headers=admin)
    p = dash(client, admin, pid, "delays")
    assert p["total"] == base["total"] - 1 + 2  # the revised task is no longer late; two pending items are
    assert not any(r["id"] == late["id"] for r in p["rows"])
    slip = next(r for r in p["slippage"] if r["id"] == late["id"]) if any(r["id"] == late["id"] for r in p["slippage"]) else None
    assert slip is None or slip["slippage"] > 0  # fully-recovered rows drop out; slippage is only ever listed for rows still delayed
    src = {x["key"]: x for x in p["sources"]}
    assert src["pending_item"]["count"] == 2 and src["pending_item"]["available"]
    pend = {r["title"]: r for r in p["rows"] if r["source"] == "pending_item"}
    assert pend["Tegra input"]["party"] == "customer" and pend["WFX input"]["party"] == "wfx"
    # a revised-but-still-late item shows slippage against the original date
    cust = client.post(f"{API}/projects/{pid}/pending-items/{c1['id']}/revisions", json={"field": "target_date", "new_date": "2026-11-14", "reason": "Customer asked for 4 days", "approve": True}, headers=admin)
    assert cust.status_code == 201
    row = next(r for r in dash(client, admin, pid, "delays")["slippage"] if r["id"] == c1["id"])
    assert row["slippage"] == 4 and row["baseline"] == "2026-11-10" and row["due"] == "2026-11-14" and row["days_late"] == 3


def test_empty_project_shows_unavailable_not_zero(client, admin):
    pid, prods = setup_project(client, admin)
    d = dash(client, admin, pid, "delays")
    assert d["available"] is False and d["total"] == 0 and all(x["count"] is None for x in d["sources"])
    o = dash(client, admin, pid, "overall")
    assert o["available"] is False and o["kpis"]["overall"]["pct"] is None and o["kpis"]["overall"]["pct_display"] is None  # no 0%: there is nothing to measure
    pr = dash(client, admin, pid, f"product/{prods['PLM']}")
    assert pr["available"] is False and pr["kpis"]["overall"]["pct"] is None
    assert dash(client, admin, pid, "next-week")["available"] is False


# ======================================================================= export and access
def _pptx_text(data: bytes) -> str:
    prs = Presentation(io.BytesIO(data))
    return "\n".join(sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame)


def test_powerpoint_export_uses_the_same_numbers(client, admin):
    pid, prods = full_setup(client, admin)
    o = dash(client, admin, pid, "overall")
    r = client.get(f"{API}/projects/{pid}/dashboard-exports/overall?as_of={AS_OF}", headers=admin)
    assert r.status_code == 200 and "presentationml" in r.headers["content-type"] and "attachment" in r.headers["content-disposition"]
    t = _pptx_text(r.content)
    assert f"{o['kpis']['overall']['pct_display']}%" in t and "OVERDUE PHASES" in t and "17-Nov-26" in t
    assert "Project Kick Off" in t and "100% Done" in t and "★" in t and "Today" in t
    assert o["kpis"]["overall"]["formula"] in t.replace("% = ", "")
    for kind, needle in (("delays", "Delay Dashboard"), ("next-week", "Next week"), (f"product", "Sign-Off Gate Tracker")):
        extra = f"&product_id={prods['PLM']}" if kind == "product" else ""
        rr = client.get(f"{API}/projects/{pid}/dashboard-exports/{kind}?as_of={AS_OF}{extra}", headers=admin)
        assert rr.status_code == 200 and needle in _pptx_text(rr.content)
    prod = _pptx_text(client.get(f"{API}/projects/{pid}/dashboard-exports/product?as_of={AS_OF}&product_id={prods['PLM']}", headers=admin).content)
    pk = dash(client, admin, pid, f"product/{prods['PLM']}")["kpis"]
    assert f"{pk['items']['done']} / {pk['items']['total']}" in prod and "Business Blueprint Sign off" in prod and "Needs attention" in prod
    assert client.get(f"{API}/projects/{pid}/dashboard-exports/bogus", headers=admin).status_code == 404
    audit = get(client, admin, "/audit-logs?entity_type=dashboard&action=export")["items"]
    assert len(audit) >= 4


def test_dashboard_access_and_export_permissions(client, admin, make_user):
    pid, prods = full_setup(client, admin)
    pmid, pm = make_user("project_manager")
    assert client.get(f"{API}/projects/{pid}/dashboards/overall", headers=pm).status_code == 404  # no project access: invisible
    client.put(f"{API}/users/{pmid}/project-access", json={"project_ids": [pid]}, headers=admin)
    assert client.get(f"{API}/projects/{pid}/dashboards/overall", headers=pm).status_code == 200
    assert client.get(f"{API}/projects/{pid}/dashboard-exports/overall", headers=pm).status_code == 200
    _, mg = make_user("management")
    assert client.get(f"{API}/projects/{pid}/dashboards/delays", headers=mg).status_code == 200
    assert client.get(f"{API}/projects/{pid}/dashboard-exports/overall", headers=mg).status_code == 200
    _, dev = make_user("developer")
    assert client.get(f"{API}/projects/{pid}/dashboards/overall", headers=dev).status_code == 404  # not granted
    dv, devh = make_user("qa", "qa2@example.com")
    client.put(f"{API}/users/{dv}/project-access", json={"project_ids": [pid]}, headers=admin)
    assert client.get(f"{API}/projects/{pid}/dashboards/overall", headers=devh).status_code == 200
    assert client.get(f"{API}/projects/{pid}/dashboard-exports/overall", headers=devh).status_code == 403  # may view, may not export
    assert client.get(f"{API}/projects/{pid}/dashboards/product/00000000-0000-0000-0000-000000000009", headers=admin).status_code == 404
