"""Stage 6: the exact requests Quick Add and inline editing send, so the screens and the API cannot drift apart."""
from datetime import date, timedelta

from test_phase2 import get, setup_project
from test_phase3 import new_item
from test_stage1 import member

API = "/api/v1"


def post(client, hdr, path, body):
    return client.post(f"{API}{path}", json=body, headers=hdr)


def monday(d: date) -> str:
    return (d - timedelta(days=d.weekday())).isoformat()


def test_quick_add_creates_every_kind_with_the_project_and_product_context(client, admin):
    pid, prods = setup_project(client, admin)
    plm = prods["PLM"]
    phase = post(client, admin, f"/projects/{pid}/phases", {"name": "Blueprint"}).json()["id"]
    p = f"/projects/{pid}"
    # Task
    t = post(client, admin, f"{p}/work-items", {"title": "Map chart of accounts", "kind": "task", "phase_id": phase, "product_id": plm, "owner_name": "Asha",
                                                "planned_start": "2026-12-01", "planned_finish": "2026-12-05", "status": "not_started"})
    assert t.status_code == 201, t.text
    assert (t.json()["product_id"], t.json()["phase_id"], t.json()["owner_name"], t.json()["kind"]) == (plm, phase, "Asha", "task")
    # Milestone: a single date
    m = post(client, admin, f"{p}/work-items", {"title": "Blueprint sign-off", "kind": "milestone", "phase_id": None, "product_id": plm, "owner_name": None,
                                                "planned_start": "2026-12-10", "planned_finish": "2026-12-10", "status": "not_started"}).json()
    assert m["kind"] == "milestone" and m["planned_start"] == m["planned_finish"] == "2026-12-10"
    # Project activity (an action) with the default priority
    a = post(client, admin, f"{p}/records/action-items", {"title": "Confirm interface owner", "owner_name": "Ravi", "priority": "medium", "due_date": None, "product_id": plm})
    assert a.status_code == 201 and a.json()["priority"] == "medium" and a.json()["product_id"] == plm and a.json()["status"] == "open"
    # Delivery item
    d = post(client, admin, f"{p}/records/delivery-items", {"description": "Party master revamp", "external_id": "440679", "stream": "Finance", "module": None, "tech_owner": "munish", "product_id": plm})
    assert d.status_code == 201 and d.json()["external_id"] == "440679" and d.json()["product_id"] == plm
    # Dependency, waiting on someone
    pend = post(client, admin, f"{p}/pending-items", {"pending_with": "customer", "description": "Chart of accounts sign-off", "owner_name": None, "original_target_date": "2026-12-03", "product_id": plm, "status": "not_started"})
    assert pend.status_code == 201, pend.text
    assert pend.json()["pending_with"] == "customer" and pend.json()["original_target_date"] == "2026-12-03"
    # Dependency, one task before another
    a1 = new_item(client, admin, pid, title="Task A", planned_start="2026-12-01", planned_finish="2026-12-05")["id"]
    a2 = new_item(client, admin, pid, title="Task B", planned_start="2026-12-06", planned_finish="2026-12-09")["id"]
    assert post(client, admin, f"{p}/work-items/{a2}/dependencies", {"predecessor_id": a1, "lag_days": 0}).status_code == 201
    assert any(x["predecessor_id"] == a1 and x["successor_id"] == a2 for x in get(client, admin, f"{p}/dependencies"))
    assert post(client, admin, f"{p}/work-items/{a1}/dependencies", {"predecessor_id": a2, "lag_days": 0}).status_code == 422  # the loop is refused with a message the form shows
    # Discussion point
    dis = post(client, admin, f"{p}/records/discussions", {"name": "Intercompany posting rules", "concern": None, "module": "GL", "responsibility": None, "target_date": None, "product_id": plm})
    assert dis.status_code == 201 and dis.json()["status"] == "open"
    # Weekly activity: with no date it lands in the current week (a Monday)
    w = post(client, admin, f"{p}/records/week-plan-items", {"title": "Data migration dry run", "workstream": "Data", "owner_name": None, "module": None, "target_date": None, "week_start": monday(date.today()), "product_id": plm})
    assert w.status_code == 201, w.text
    assert w.json()["week_start"] == monday(date.today()) and w.json()["workstream"] == "Data"
    w2 = post(client, admin, f"{p}/records/week-plan-items", {"title": "UAT scripts", "target_date": "2026-12-09", "week_start": monday(date(2026, 12, 9)), "product_id": plm}).json()
    assert w2["week_start"] == "2026-12-07" and w2["target_date"] == "2026-12-09"
    # Sign-off gate: a missing set becomes "manual"
    g = post(client, admin, f"{p}/records/approval-gates", {"name": "Finance blueprint sign-off", "gate_type": None, "approver_name": "R. Mehta", "planned_date": "2026-12-15", "product_id": plm})
    assert g.status_code == 201 and g.json()["gate_type"] == "manual" and g.json()["approver_name"] == "R. Mehta" and g.json()["product_id"] == plm
    # everything is visible on the dashboards that read it
    assert get(client, admin, f"{p}/dashboards/overall?as_of=2026-12-01")["kpis"]["activities"]["all"] >= 4


def test_quick_add_required_fields_and_permissions(client, admin, make_user):
    pid, prods = setup_project(client, admin)
    p = f"/projects/{pid}"
    assert post(client, admin, f"{p}/work-items", {"title": "", "kind": "task", "status": "not_started"}).status_code == 422
    assert post(client, admin, f"{p}/records/delivery-items", {"description": ""}).status_code == 422
    assert post(client, admin, f"{p}/records/discussions", {"name": " "}).status_code == 422
    assert post(client, admin, f"{p}/pending-items", {"pending_with": "nobody", "description": "x", "status": "not_started"}).status_code == 422
    assert post(client, admin, f"{p}/records/week-plan-items", {"title": "x", "week_start": "2026-12-08"}).status_code == 422  # a Tuesday
    assert post(client, admin, f"{p}/records/action-items", {"title": "x", "product_id": "00000000-0000-0000-0000-000000000000"}).status_code == 422
    dev = member(client, admin, make_user, "developer", pid)
    cust = member(client, admin, make_user, "customer_user", pid)
    for who in (dev, cust):  # read-only roles do not get the button, and the server refuses anyway
        assert post(client, who, f"{p}/work-items", {"title": "x", "kind": "task", "status": "not_started"}).status_code == 403
        assert post(client, who, f"{p}/records/action-items", {"title": "x"}).status_code == 403
        assert post(client, who, f"{p}/records/week-plan-items", {"title": "x", "week_start": monday(date.today())}).status_code == 403
        assert post(client, who, f"{p}/records/approval-gates", {"name": "x"}).status_code == 403
    _, outsider = make_user("project_manager")
    assert post(client, outsider, f"{p}/work-items", {"title": "x", "kind": "task", "status": "not_started"}).status_code == 404  # no access to this project


def test_inline_edits_send_small_patches_that_the_server_validates(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    p = f"/projects/{pid}"
    t = new_item(client, admin, pid, title="Blueprint", planned_start="2026-12-01", planned_finish="2026-12-10", owner_name="Asha")
    patch = lambda path, body, who=admin: client.patch(f"{API}{p}{path}", json=body, headers=who)  # noqa: E731
    # quick owner reassignment, and clearing it
    assert patch(f"/work-items/{t['id']}", {"owner_name": "Ravi"}).json()["owner_name"] == "Ravi"
    assert patch(f"/work-items/{t['id']}", {"owner_name": None}).json()["owner_name"] is None
    # quick status change (by status code)
    r = patch(f"/work-items/{t['id']}", {"status": "in_progress"}).json()
    assert r["status_category"] == "in_progress" and r["status_raw"] == "In Progress"
    assert patch(f"/work-items/{t['id']}", {"status": "no_such_state"}).status_code == 422  # the cell shows this message and keeps the old value
    # quick date change: a revision with a reason, the original is kept
    ok = client.post(f"{API}{p}/work-items/{t['id']}/reschedule", json={"finish": "2026-12-14", "reason": "customer asked", "approve": True}, headers=admin)
    assert ok.status_code == 200 and ok.json()["item"]["effective_finish"] == "2026-12-14" and ok.json()["item"]["planned_finish"] == "2026-12-10"
    assert client.post(f"{API}{p}/work-items/{t['id']}/reschedule", json={"finish": "2026-11-20", "reason": "oops", "approve": True}, headers=admin).status_code == 422  # before the start
    assert client.post(f"{API}{p}/work-items/{t['id']}/reschedule", json={"finish": "2026-12-20", "reason": "", "approve": True}, headers=admin).status_code == 422  # a reason is required
    # records: text, date and select fields
    d = post(client, admin, f"{p}/records/delivery-items", {"description": "Party master"}).json()
    assert patch(f"/records/delivery-items/{d['id']}", {"tech_owner": "munish"}).json()["tech_owner"] == "munish"
    assert patch(f"/records/delivery-items/{d['id']}", {"spec_closure_date": "2026-12-02"}).json()["spec_closure_date"] == "2026-12-02"
    assert patch(f"/records/delivery-items/{d['id']}", {"spec_closure_date": None}).json()["spec_closure_date"] is None
    assert patch(f"/records/delivery-items/{d['id']}", {"spec_closure_date": "not a date"}).status_code == 422
    assert patch(f"/records/delivery-items/{d['id']}", {"delivery_target_date": "2026-12-30"}).status_code == 422  # derived dates are never inline-editable
    dis = post(client, admin, f"{p}/records/discussions", {"name": "Posting rules"}).json()
    assert patch(f"/records/discussions/{dis['id']}", {"status": "decided"}).json()["status"] == "decided"
    assert patch(f"/records/discussions/{dis['id']}", {"status": "maybe"}).status_code == 422
    dev = member(client, admin, make_user, "developer", pid)
    assert patch(f"/work-items/{t['id']}", {"owner_name": "X"}, dev).status_code == 403
    assert patch(f"/records/delivery-items/{d['id']}", {"tech_owner": "X"}, dev).status_code == 403
