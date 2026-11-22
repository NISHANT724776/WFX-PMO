"""Stage 4: approval gates, department x location coverage, Needs Attention actions, week plan activities."""
import io
from datetime import date, timedelta

import openpyxl

from test_phase2 import get, setup_project
from test_phase3 import new_item
from test_phase4 import AS_OF, dash, full_setup

API = "/api/v1"


def rec(client, hdr, pid, kind, method="get", rid=None, body=None, params=""):
    url = f"{API}/projects/{pid}/records/{kind}" + (f"/{rid}" if rid else "") + params
    return getattr(client, method)(url, headers=hdr, **({"json": body} if body is not None else {}))


def gates(client, hdr, pid, **p):
    return get(client, hdr, f"/projects/{pid}/records/approval-gates?as_of={AS_OF}&size=200" + "".join(f"&{k}={v}" for k, v in p.items()))


# ======================================================================= approval gates
def test_gate_lifecycle_rules(client, admin):
    pid, prods = setup_project(client, admin)
    r = rec(client, admin, pid, "approval-gates", "post", body={"name": "Finance blueprint sign-off", "approver_name": "R. Mehta", "planned_date": "2026-11-10", "product_id": prods["PLM"]})
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["gate_type"] == "manual"
    od = get(client, admin, f"/projects/{pid}/records/approval-gates/{g['id']}?as_of={AS_OF}")
    assert od["is_overdue"] and od["days_late"] == 7 and not od["is_closed"]  # planned 10 Nov, report date 17 Nov
    gid = g["id"]
    # approving: submission date and approval date are required, never assumed
    assert rec(client, admin, pid, "approval-gates", "patch", gid, {"status": "approved"}).status_code == 422
    assert rec(client, admin, pid, "approval-gates", "patch", gid, {"status": "approved", "submission_date": "2026-11-05"}).status_code == 422
    assert rec(client, admin, pid, "approval-gates", "patch", gid, {"status": "approved", "submission_date": "2026-11-05", "signoff_date": "2026-11-01"}).status_code == 422  # before submission
    assert rec(client, admin, pid, "approval-gates", "patch", gid, {"status": "nonsense"}).status_code == 422
    assert get(client, admin, f"/projects/{pid}/records/approval-gates/{gid}")["approval_status"] is None  # nothing was saved by the failures
    # a blocked state needs the reason
    assert rec(client, admin, pid, "approval-gates", "patch", gid, {"status": "rejected"}).status_code == 422
    ok = rec(client, admin, pid, "approval-gates", "patch", gid, {"status": "rejected", "comments": "Scope of GL not covered"})
    assert ok.status_code == 200 and ok.json()["approval_status"] == "Rejected" and ok.json()["approval_category"] == "blocked"
    done = rec(client, admin, pid, "approval-gates", "patch", gid, {"status": "approved", "submission_date": "2026-11-05", "signoff_date": "2026-11-12"}).json()
    assert done["approval_status"] == "Approved" and done["approval_category"] == "done" and done["signoff_date"] == "2026-11-12"
    got = get(client, admin, f"/projects/{pid}/records/approval-gates/{gid}?as_of={AS_OF}")
    assert got["is_closed"] and not got["is_overdue"]
    # reopening clears the approval date; the old approval stays in the audit log
    re = rec(client, admin, pid, "approval-gates", "patch", gid, {"status": "under_review"}).json()
    assert re["approval_category"] == "in_progress" and re["signoff_date"] is None
    logs = get(client, admin, f"/audit-logs?entity_type=approval_gate&entity_id={gid}&size=50")["items"]
    assert any(l["before"] and l["before"].get("signoff_date") == "2026-11-12" and l["after"]["signoff_date"] is None for l in logs)


def test_approval_states_are_configurable_and_decide_what_counts_as_approved(client, admin):
    pid, _ = setup_project(client, admin)
    g = rec(client, admin, pid, "approval-gates", "post", body={"name": "Legal review", "planned_date": "2026-11-01", "submission_date": "2026-10-20"}).json()
    new = client.post(f"{API}/status-configs", json={"entity_type": "approval_gate", "code": "legal_cleared", "label": "Cleared by Legal", "category": "done"}, headers=admin)
    assert new.status_code in (200, 201), new.text
    r = rec(client, admin, pid, "approval-gates", "patch", g["id"], {"status": "legal_cleared", "signoff_date": "2026-11-02"}).json()
    assert r["approval_status"] == "Cleared by Legal" and r["is_closed"]
    assert get(client, admin, f"/projects/{pid}/dashboards/delays?as_of={AS_OF}")["total"] == 0  # a cleared gate is not a delay


def test_gate_edits_flow_to_the_dashboard_on_real_tegra_data(client, admin):
    pid, prods = full_setup(client, admin)
    lst = gates(client, admin, pid)
    assert lst["total"] > 0
    before = dash(client, admin, pid, f"product/{prods['PLM']}")
    open_g = next(g for g in lst["items"] if not g["is_closed"])
    set_name = open_g["gate_type"]
    b_sum = before["approval_summary"].get(set_name, {"approved": 0, "total": 0})
    r = rec(client, admin, pid, "approval-gates", "patch", open_g["id"], {"status": "approved", "submission_date": "2026-11-10", "signoff_date": "2026-11-14", "approver_name": "A. Rao"})
    assert r.status_code == 200, r.text
    after = dash(client, admin, pid, f"product/{prods['PLM']}")
    a_sum = after["approval_summary"][set_name]
    if open_g["product_id"] in (None, prods["PLM"]):
        assert a_sum["approved"] == b_sum["approved"] + 1 and a_sum["total"] == b_sum["total"]
        row = next(a for a in after["approvals"] if a["id"] == open_g["id"])
        assert row["state"] == "done" and row["approver"] == "A. Rao"
    # the delay dashboard counts exactly the overdue open gates
    now = gates(client, admin, pid)["items"]
    late = sum(1 for g in now if g["is_overdue"])
    src = next(s for s in dash(client, admin, pid, "delays")["sources"] if s["key"] == "approval_gate")
    assert src["count"] == late


# ======================================================================= coverage
def master(client, admin, path, code, name):
    r = client.post(f"{API}/{path}", json={"code": code, "name": name}, headers=admin)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_coverage_is_calculated_never_typed(client, admin):
    pid, prods = setup_project(client, admin)
    cov = lambda **p: get(client, admin, f"/projects/{pid}/dashboards/coverage" + ("?" + "&".join(f"{k}={v}" for k, v in p.items()) if p else ""))  # noqa: E731
    assert cov()["available"] is False
    fin, log = master(client, admin, "departments", "FIN", "Finance"), master(client, admin, "departments", "LOG", "Logistics")
    blr, dxb = master(client, admin, "locations", "BLR", "Bengaluru"), master(client, admin, "locations", "DXB", "Dubai")
    mk = lambda **b: rec(client, admin, pid, "coverage-activities", "post", body=b)  # noqa: E731
    a1 = mk(title="AP configuration", department_id=fin, location_id=blr, planned_count=4, completed_count=2, responsible_name="Asha")
    assert a1.status_code == 201, a1.text
    mk(title="AR configuration", department_id=fin, location_id=blr, planned_count=6, completed_count=6)
    mk(title="Pick and pack", department_id=log, location_id=blr, planned_count=5, completed_count=1, product_id=prods["WMS"])
    mk(title="AP configuration", department_id=fin, location_id=dxb, planned_count=4, completed_count=4)
    mk(title="Nothing planned yet", department_id=log, location_id=dxb, planned_count=0)
    c = cov()
    assert c["available"] and c["total"] == {"planned": 19, "completed": 13, "pct": 68.4, "activities": 5}
    cell = {(x["department_id"], x["location_id"]): x for x in c["cells"]}
    assert cell[(fin, blr)]["planned"] == 10 and cell[(fin, blr)]["completed"] == 8 and cell[(fin, blr)]["pct"] == 80.0
    assert cell[(log, dxb)]["pct"] is None  # nothing planned: n/a, not 0%
    by_loc = {x["code"]: x for x in c["locations"]}
    assert by_loc["BLR"]["pct"] == round(9 / 15 * 100, 1) and by_loc["DXB"]["pct"] == 100.0
    assert [x["code"] for x in c["locations"]] == ["DXB", "BLR"]  # compared, best first
    assert {x["code"]: x["pct"] for x in c["departments"]} == {"FIN": round(12 / 14 * 100, 1), "LOG": round(1 / 5 * 100, 1)}
    # recording progress recalculates everything
    rid = a1.json()["id"]
    assert rec(client, admin, pid, "coverage-activities", "patch", rid, {"completed_count": 4}).status_code == 200
    assert cov()["total"]["completed"] == 15
    assert cov(product_id=prods["WMS"])["total"] == {"planned": 5, "completed": 1, "pct": 20.0, "activities": 1}
    # validation
    assert rec(client, admin, pid, "coverage-activities", "patch", rid, {"completed_count": 9}).status_code == 422  # more than planned
    assert rec(client, admin, pid, "coverage-activities", "patch", rid, {"planned_count": 2}).status_code == 422  # below what is completed
    assert rec(client, admin, pid, "coverage-activities", "patch", rid, {"planned_count": -1}).status_code == 422
    assert rec(client, admin, pid, "coverage-activities", "patch", rid, {"completed_count": "x"}).status_code == 422
    assert mk(title="x", department_id="00000000-0000-0000-0000-000000000000", location_id=blr).status_code == 422
    assert mk(title="x", department_id=fin).status_code == 422  # location required
    # archived activities leave the numbers
    client.post(f"{API}/projects/{pid}/lifecycle/coverage_activity/{rid}/archive", json={}, headers=admin)
    assert cov()["total"]["planned"] == 15
    # list filters (server side)
    assert get(client, admin, f"/projects/{pid}/records/coverage-activities?location_id={dxb}")["total"] == 2


# ======================================================================= week plan
def week(client, admin, pid, period="next_week"):
    return dash(client, admin, pid, "next-week", period=period)


def test_week_plan_activities_end_to_end(client, admin):
    pid, prods = setup_project(client, admin)
    mk = lambda **b: rec(client, admin, pid, "week-plan-items", "post", body=b)  # noqa: E731
    r = mk(title="Customer data migration dry run", target_date="2026-11-25", workstream="Data", owner_name="Kiran", product_id=prods["ERP"], module="Migration")  # a Wednesday
    assert r.status_code == 201, r.text
    it = r.json()
    assert it["week_start"] == "2026-11-23" and it["week_end"] == "2026-11-29"  # derived Monday
    assert mk(title="x", week_start="2026-11-24").status_code == 422  # not a Monday
    assert mk(title="x", week_start="2026-11-23", target_date="2026-12-01").status_code == 422  # outside the week
    assert mk(title="x").status_code == 422  # neither week nor date
    assert mk(title="x", target_date="2026-11-25", percent_complete=101).status_code == 422
    assert mk(title="x", target_date="2026-11-25", status="finished").status_code == 422
    w = week(client, admin, pid)
    assert w["week"]["start"] == "2026-11-23" and w["available"]
    grp = next(g for g in w["groups"] if g["name"] == "Data")
    card = grp["cards"][0]
    assert card["title"] == "Customer data migration dry run" and card["tag"] == "planned" and card["owner"] == "Kiran" and card["source"]["type"] == "week_plan_item"
    assert not any(g["cards"] for g in week(client, admin, pid, "this_week")["groups"])  # not in this week
    # update completion and remarks
    up = rec(client, admin, pid, "week-plan-items", "patch", it["id"], {"percent_complete": 40, "status": "in_progress", "remarks": "Waiting for the mapping sheet"}).json()
    assert up["percent_complete"] == 40 and up["status"] == "in_progress"
    c2 = week(client, admin, pid)["groups"][0]["cards"][0]
    assert c2["percent_complete"] == 40 and c2["plan_status"] == "in_progress" and "mapping sheet" in c2["description"]
    # move to this week: the target date keeps its weekday
    mv = client.post(f"{API}/projects/{pid}/records/week-plan-items/{it['id']}/move", json={"weeks": -1}, headers=admin)
    assert mv.status_code == 200, mv.text
    assert mv.json()["week_start"] == "2026-11-16" and mv.json()["target_date"] == "2026-11-18"
    assert week(client, admin, pid, "this_week")["groups"][0]["cards"][0]["title"] == "Customer data migration dry run"
    assert not week(client, admin, pid)["available"] or all(c["tag"] != "planned" for g in week(client, admin, pid)["groups"] for c in g["cards"])
    for bad in ({"week_start": "2026-11-17"}, {"week_start": "2026-11-16"}, {"week_start": "2026-11-23", "weeks": 1}, {}):
        assert client.post(f"{API}/projects/{pid}/records/week-plan-items/{it['id']}/move", json=bad, headers=admin).status_code == 422
    # last week and not done -> carried over when looking at next week
    client.post(f"{API}/projects/{pid}/records/week-plan-items/{it['id']}/move", json={"weeks": -2}, headers=admin)
    carry = [c for g in week(client, admin, pid)["groups"] for c in g["cards"] if c["tag"] == "carry_over"]
    assert [c["title"] for c in carry] == ["Customer data migration dry run"] and carry[0]["days_late"] > 0
    rec(client, admin, pid, "week-plan-items", "patch", it["id"], {"status": "done", "percent_complete": 100})
    assert not [c for g in week(client, admin, pid)["groups"] for c in g["cards"] if c["tag"] == "carry_over"]  # done work is not carried
    # remove from the plan = archive; restorable
    client.post(f"{API}/projects/{pid}/records/week-plan-items/{it['id']}/move", json={"week_start": "2026-11-23"}, headers=admin)
    assert client.post(f"{API}/projects/{pid}/lifecycle/week_plan_item/{it['id']}/archive", json={}, headers=admin).status_code == 200
    assert not week(client, admin, pid)["available"]
    assert client.post(f"{API}/projects/{pid}/lifecycle/week_plan_item/{it['id']}/restore", json={}, headers=admin).status_code == 200
    assert week(client, admin, pid)["available"]
    assert {"create", "update", "move_week", "archive"} <= {a["action"] for a in get(client, admin, f"/audit-logs?entity_type=week_plan_item&entity_id={it['id']}&size=50")["items"]}


def test_derived_cards_know_when_they_are_planned_and_exports_include_planned_work(client, admin):
    pid, _ = setup_project(client, admin)
    t = new_item(client, admin, pid, title="Prepare UAT scripts", planned_start="2026-11-24", planned_finish="2026-11-27", owner_name="Meera")
    card = lambda: next(c for g in week(client, admin, pid)["groups"] for c in g["cards"] if c["source"]["id"] == t["id"])  # noqa: E731
    assert card()["in_plan"] is False and card()["tag"] == "due"
    r = rec(client, admin, pid, "week-plan-items", "post", body={"title": "Prepare UAT scripts", "target_date": "2026-11-27", "owner_name": "Meera", "source_type": "task", "source_id": t["id"]})
    assert r.status_code == 201
    assert card()["in_plan"] is True  # the card shows it has been put on the plan
    # Excel export carries derived and planned activities
    x = client.get(f"{API}/projects/{pid}/dashboard-exports/next_week?as_of={AS_OF}&format=xlsx", headers=admin)
    assert x.status_code == 200 and "spreadsheetml" in x.headers["content-type"]
    ws = openpyxl.load_workbook(io.BytesIO(x.content)).active
    rows = [[c.value for c in r] for r in ws.iter_rows(min_row=5, values_only=False)]
    rows = [r for r in rows if isinstance(r[0], int)]  # the last row is a footer
    titles = [r[2] for r in rows]
    assert titles.count("Prepare UAT scripts") == 2 and {r[6] for r in rows} == {"Due", "Planned"}
    assert client.get(f"{API}/projects/{pid}/dashboard-exports/overall?as_of={AS_OF}&format=xlsx", headers=admin).status_code == 422
    p = client.get(f"{API}/projects/{pid}/dashboard-exports/next_week?as_of={AS_OF}", headers=admin)  # PowerPoint still renders with planned cards
    assert p.status_code == 200 and p.content[:2] == b"PK"
    assert "export" in {a["action"] for a in get(client, admin, "/audit-logs?entity_type=dashboard&size=10")["items"]}


# ======================================================================= Needs Attention -> actions
def test_attention_items_become_actions_and_show_their_latest_step(client, admin):
    pid, prods = full_setup(client, admin)
    pdash = lambda: dash(client, admin, pid, f"product/{prods['PLM']}")  # noqa: E731
    items = pdash()["needs_attention"]
    target = next(i for i in items if i["kind"] == "task" and i["refs"][0]["id"])
    assert target["action"] is None
    ref = target["refs"][0]
    r = rec(client, admin, pid, "action-items", "post", body={"title": target["text"][:120], "owner_name": "Meera", "priority": "high", "due_date": "2026-11-20",
                                                                 "source_type": ref["type"], "source_id": ref["id"], "product_id": prods["PLM"]})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    again = next(i for i in pdash()["needs_attention"] if i["refs"] == target["refs"])
    assert again["action"]["owner"] == "Meera" and again["action"]["priority"] == "high" and again["action"]["last_action"] == "Created"
    assert again["action"]["last_action_by"] == "admin@example.com"
    client.post(f"{API}/projects/{pid}/records/action-items/{aid}/escalate", json={"reason": "no movement", "to": "Sponsor"}, headers=admin)
    latest = next(i for i in pdash()["needs_attention"] if i["refs"] == target["refs"])["action"]
    assert latest["status"] == "escalated" and "Escalated" in latest["last_action"]
    client.post(f"{API}/projects/{pid}/records/action-items/{aid}/resolve", json={"reason": "date agreed with customer"}, headers=admin)
    assert next(i for i in pdash()["needs_attention"] if i["refs"] == target["refs"])["action"] is None  # resolved actions leave the panel
    # an overdue action with no source of its own shows up by itself
    rec(client, admin, pid, "action-items", "post", body={"title": "Confirm interface owner with customer IT", "owner_name": "Ravi", "due_date": "2026-11-10", "product_id": prods["PLM"]})
    mine = [i for i in pdash()["needs_attention"] if i["kind"] == "action"]
    assert len(mine) == 1 and "overdue" in mine[0]["text"] and mine[0]["action"]["owner"] == "Ravi"
    # PowerPoint export still renders with the new items
    assert client.get(f"{API}/projects/{pid}/dashboard-exports/product?as_of={AS_OF}&product_id={prods['PLM']}", headers=admin).status_code == 200
