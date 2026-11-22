"""Phase 3: planning (edit, revisions, dependencies), pending register, flex values, delay rule. Real Tegra/Shahi data."""
import uuid
import warnings
from collections import Counter
from datetime import date
from pathlib import Path

import openpyxl
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Role
from app.modules.planning.delays import assess
from test_phase2 import PLAN, XLSX, get, setup_project, upload  # noqa: E402

warnings.filterwarnings("ignore")
API = "/api/v1"
SHAHI = Path(__file__).parent / "data" / "shahi_tracker.xlsx"
AS_OF = "2026-11-17"  # the report date of the Tegra PPT


def import_plan(client, admin, pid):
    b = get(client, admin, f"/imports/{upload(client, admin, PLAN).json()['id']}")
    r = client.post(f"{API}/imports/{b['id']}/commit", json={"project_id": pid}, headers=admin)
    assert r.status_code == 200, r.text


def items(client, hdr, pid, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return get(client, hdr, f"/projects/{pid}/work-items?size=500&as_of={AS_OF}&{q}")


def one(client, hdr, pid, title_start):
    return next(i for i in items(client, hdr, pid)["items"] if i["title"].startswith(title_start))


def new_item(client, hdr, pid, **kw):
    body = {"title": "Manual task", "planned_start": "2026-11-01", "planned_finish": "2026-11-10", **kw}
    r = client.post(f"{API}/projects/{pid}/work-items", json=body, headers=hdr)
    assert r.status_code == 201, r.text
    return r.json()


# ======================================================================= delay rule (pure)
def d(s):
    return date.fromisoformat(s)


def test_delay_rule_cases():
    a = lambda **k: assess(**{"planned_start": d("2026-11-01"), "planned_finish": d("2026-11-10"), "revised_start": None, "revised_finish": None,  # noqa: E731
                              "status_category": "in_progress", "actual_start": d("2026-11-01"), "actual_finish": None, "as_of": d("2026-11-17"), "grace": 0, **k})
    x = a()
    assert x.overdue and x.days_late == 7 and not x.start_delayed
    assert not a(status_category="done").overdue and not a(actual_finish=d("2026-11-09")).overdue  # closed either way
    assert not a(grace=7).overdue and a(grace=6).overdue and a(grace=6).days_late == 1  # grace applies to the date
    assert not a(as_of=d("2026-11-10")).overdue  # due today is not late
    # revised date moves the deadline, but slippage is measured against the baseline
    r = a(revised_finish=d("2026-11-30"))
    assert not r.overdue and r.slippage_days == 20 and r.effective_finish == d("2026-11-30")
    s = a(status_category="not_started", actual_start=None, planned_finish=d("2026-12-20"))
    assert s.start_delayed and not s.overdue  # should have started, not yet due
    assert not a(status_category="not_started", actual_start=None, planned_start=d("2026-12-01"), planned_finish=d("2026-12-20")).start_delayed
    assert not a(planned_finish=None).overdue  # no date, no verdict


# ======================================================================= work item CRUD and the baseline rule
def test_work_item_lifecycle_and_baseline_is_not_editable(client, admin):
    pid, prods = setup_project(client, admin)
    w = new_item(client, admin, pid, title="Prepare cut-over plan", delivery_mode="onsite", responsible_party="WFX", status="not_started")
    wid = w["id"]
    assert w["status_category"] == "not_started" and w["planned_finish"] == "2026-11-10" and w["revised_finish"] is None
    r = client.patch(f"{API}/projects/{pid}/work-items/{wid}", json={"status": "in_progress", "actual_start": "2026-11-02", "owner_name": "Mayank"}, headers=admin)
    assert r.status_code == 200 and r.json()["status_category"] == "in_progress" and r.json()["owner_name"] == "Mayank"
    # the baseline cannot be overwritten, only revised
    r = client.patch(f"{API}/projects/{pid}/work-items/{wid}", json={"planned_finish": "2026-12-31"}, headers=admin)
    assert r.status_code == 422
    assert get(client, admin, f"/projects/{pid}/work-items/{wid}")["planned_finish"] == "2026-11-10"
    # validation
    assert client.patch(f"{API}/projects/{pid}/work-items/{wid}", json={"status": "nonsense"}, headers=admin).status_code == 422
    assert client.patch(f"{API}/projects/{pid}/work-items/{wid}", json={"actual_finish": "2026-10-01"}, headers=admin).status_code == 422
    assert client.patch(f"{API}/projects/{pid}/work-items/{wid}", json={"parent_id": wid}, headers=admin).status_code == 422
    bad = client.post(f"{API}/projects/{pid}/work-items", json={"title": "x", "planned_start": "2026-11-10", "planned_finish": "2026-11-01"}, headers=admin)
    assert bad.status_code == 422
    # done is a status; the actual finish is a separate fact and is NOT invented
    done = client.patch(f"{API}/projects/{pid}/work-items/{wid}", json={"status": "done"}, headers=admin).json()
    assert done["status_category"] == "done" and done["actual_finish"] is None and not done["is_overdue"]
    audit = get(client, admin, f"/audit-logs?entity_type=work_item&entity_id={wid}")["items"]
    assert {"create", "update"} <= {a["action"] for a in audit}
    assert client.delete(f"{API}/projects/{pid}/work-items/{wid}", headers=admin).status_code == 204
    assert client.get(f"{API}/projects/{pid}/work-items/{wid}", headers=admin).status_code == 404


def test_sub_task_and_milestone(client, admin):
    pid, _ = setup_project(client, admin)
    parent = new_item(client, admin, pid, title="Blueprint")
    ms = new_item(client, admin, pid, title="Blueprint sign-off", kind="milestone", parent_id=parent["id"], planned_start="2026-11-27", planned_finish="2026-11-27")
    assert ms["kind"] == "milestone" and ms["parent_id"] == parent["id"]
    assert [i["title"] for i in items(client, admin, pid, kind="milestone")["items"]] == ["Blueprint sign-off"]


def test_plan_write_permissions_and_project_scope(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    w = new_item(client, admin, pid)
    _, qa = make_user("qa")
    assert client.get(f"{API}/projects/{pid}/work-items", headers=qa).status_code == 404  # no project access: invisible
    assert client.post(f"{API}/projects/{pid}/work-items", json={"title": "x"}, headers=qa).status_code in (403, 404)
    pmid, pm = make_user("project_manager")
    assert client.post(f"{API}/projects/{pid}/work-items", json={"title": "x"}, headers=pm).status_code == 404  # not granted
    client.put(f"{API}/users/{pmid}/project-access", json={"project_ids": [pid]}, headers=admin)
    assert client.post(f"{API}/projects/{pid}/work-items", json={"title": "x"}, headers=pm).status_code == 201
    _, mg = make_user("management")
    assert client.get(f"{API}/projects/{pid}/work-items", headers=mg).status_code == 200
    assert client.post(f"{API}/projects/{pid}/work-items", json={"title": "x"}, headers=mg).status_code == 403
    assert client.patch(f"{API}/projects/{pid}/work-items/{w['id']}", json={"remarks": "x"}, headers=mg).status_code == 403


# ======================================================================= real plan: overdue as of the report date
def test_overdue_on_real_plan_matches_independent_oracle(client, admin):
    pid, _ = setup_project(client, admin)
    import_plan(client, admin, pid)
    ws = openpyxl.load_workbook(PLAN, data_only=True).active
    exp_over = exp_start = 0
    for row in ws.iter_rows(min_row=3, values_only=True):
        if not row[1]:
            continue
        status, start, end, a_start, a_end = row[10], row[4].date(), row[5].date(), row[7], row[8]
        closed = status == "Done" or hasattr(a_end, "date")
        started = hasattr(a_start, "date") or status in ("In-Progress", "Done")
        if not closed and end < d(AS_OF):
            exp_over += 1
        elif not closed and not started and start < d(AS_OF):
            exp_start += 1
    res = items(client, admin, pid)
    assert sum(i["is_overdue"] for i in res["items"]) == exp_over
    assert sum(i["is_start_delayed"] for i in res["items"]) == exp_start
    assert exp_over > 0  # the real plan does have late items (PPT slide 3: overdue phases)
    assert items(client, admin, pid, overdue="true")["total"] == exp_over + exp_start
    late = next(i for i in res["items"] if i["is_overdue"])
    assert late["days_late"] == (d(AS_OF) - d(late["effective_finish"])).days


def test_grace_days_setting_changes_the_verdict(client, admin):
    pid, _ = setup_project(client, admin)
    new_item(client, admin, pid, title="Due 10 Nov", planned_start="2026-11-01", planned_finish="2026-11-10", status="in_progress")  # 7 days late on 17 Nov
    assert items(client, admin, pid)["items"][0]["is_overdue"] is True
    assert client.patch(f"{API}/projects/{pid}", json={"delay_grace_days": 7}, headers=admin).status_code == 200
    graced = items(client, admin, pid)
    assert graced["grace_days"] == 7 and graced["items"][0]["is_overdue"] is False  # inside the grace period
    client.patch(f"{API}/projects/{pid}", json={"delay_grace_days": 6}, headers=admin)
    late = items(client, admin, pid)["items"][0]
    assert late["is_overdue"] is True and late["days_late"] == 1
    assert client.patch(f"{API}/projects/{pid}", json={"delay_grace_days": -1}, headers=admin).status_code == 422
    assert client.patch(f"{API}/projects/{pid}", json={"delay_grace_days": 61}, headers=admin).status_code == 422


# ======================================================================= revisions
def test_revision_history_proposed_approved_and_baseline_kept(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    w = new_item(client, admin, pid, title="Submit BBP", planned_start="2026-11-01", planned_finish="2026-11-10")
    wid = w["id"]
    # overdue at the report date
    assert one(client, admin, pid, "Submit BBP")["is_overdue"] is True
    # proposed (not approved): nothing changes yet
    r = client.post(f"{API}/projects/{pid}/work-items/{wid}/revisions", json={"field": "planned_finish", "new_date": "2026-11-30", "reason": "Customer review pending"}, headers=admin)
    assert r.status_code == 201 and r.json()[0]["status"] == "proposed" and r.json()[0]["old_date"] == "2026-11-10"
    cur = one(client, admin, pid, "Submit BBP")
    assert cur["revised_finish"] is None and cur["is_overdue"] is True
    rid = r.json()[0]["id"]
    # approval moves the deadline; baseline is untouched and slippage is measured against it
    r = client.post(f"{API}/projects/{pid}/revisions/{rid}/decision", json={"approve": True}, headers=admin)
    assert r.status_code == 200 and r.json()[0]["status"] == "approved" and r.json()[0]["decided_by_email"] == "admin@example.com"
    cur = one(client, admin, pid, "Submit BBP")
    assert cur["planned_finish"] == "2026-11-10" and cur["revised_finish"] == "2026-11-30" and cur["effective_finish"] == "2026-11-30"
    assert cur["is_overdue"] is False and cur["slippage_days"] == 20
    # second revision stacks on the first (old_date = previous effective date); history shows every step
    client.post(f"{API}/projects/{pid}/work-items/{wid}/revisions", json={"field": "planned_finish", "new_date": "2026-12-15", "reason": "Scope change", "approve": True}, headers=admin)
    hist = get(client, admin, f"/projects/{pid}/work-items/{wid}")["revisions"]
    assert [(h["old_date"], h["new_date"], h["status"]) for h in hist] == [("2026-11-10", "2026-11-30", "approved"), ("2026-11-30", "2026-12-15", "approved")]
    assert one(client, admin, pid, "Submit BBP")["slippage_days"] == 35
    # rejected revisions are kept in history but change nothing
    rr = client.post(f"{API}/projects/{pid}/work-items/{wid}/revisions", json={"field": "planned_finish", "new_date": "2027-03-01", "reason": "Too far"}, headers=admin).json()[-1]
    client.post(f"{API}/projects/{pid}/revisions/{rr['id']}/decision", json={"approve": False}, headers=admin)
    assert one(client, admin, pid, "Submit BBP")["revised_finish"] == "2026-12-15"
    assert client.post(f"{API}/projects/{pid}/revisions/{rr['id']}/decision", json={"approve": True}, headers=admin).status_code == 409  # already decided
    # guards
    f = lambda **k: client.post(f"{API}/projects/{pid}/work-items/{wid}/revisions", json=k, headers=admin)  # noqa: E731
    assert f(field="planned_finish", new_date="2026-12-15", reason="same").status_code == 422
    assert f(field="planned_finish", new_date="2026-10-01", reason="before start", approve=True).status_code == 422
    assert f(field="planned_finish", new_date="2026-12-20", reason="ab").status_code == 422  # reason required
    assert f(field="bogus", new_date="2026-12-20", reason="why not").status_code == 422
    # revision on the START date extends the range sensibly
    assert f(field="planned_start", new_date="2026-11-05", reason="Kick-off moved", approve=True).status_code == 201


def test_only_users_with_approve_permission_can_approve(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    w = new_item(client, admin, pid)
    pmid, pm = make_user("project_manager")
    client.put(f"{API}/users/{pmid}/project-access", json={"project_ids": [pid]}, headers=admin)
    with SessionLocal() as db:  # take approval away from the PM role for this test
        role = db.scalar(select(Role).where(Role.code == "project_manager"))
        role.permissions = [p for p in role.permissions if p.code != "plan:approve"]
        db.commit()
    pm = {"Authorization": "Bearer " + client.post(f"{API}/auth/login", json={"email": "project_manager@example.com", "password": "Some-Long-Password-1"}).json()["access_token"]}
    body = {"field": "planned_finish", "new_date": "2026-12-01", "reason": "Needs more time"}
    assert client.post(f"{API}/projects/{pid}/work-items/{w['id']}/revisions", json={**body, "approve": True}, headers=pm).status_code == 403
    r = client.post(f"{API}/projects/{pid}/work-items/{w['id']}/revisions", json=body, headers=pm)
    assert r.status_code == 201 and r.json()[0]["status"] == "proposed" and r.json()[0]["requested_by_email"] == "project_manager@example.com"
    assert client.post(f"{API}/projects/{pid}/revisions/{r.json()[0]['id']}/decision", json={"approve": True}, headers=pm).status_code == 403
    assert client.post(f"{API}/projects/{pid}/revisions/{r.json()[0]['id']}/decision", json={"approve": True}, headers=admin).status_code == 200
    pending = get(client, admin, f"/projects/{pid}/revisions?status=approved")
    assert len(pending) == 1


# ======================================================================= dependencies
def test_dependencies_loops_and_suggestions_from_real_plan(client, admin):
    pid, _ = setup_project(client, admin)
    import_plan(client, admin, pid)
    sug = get(client, admin, f"/projects/{pid}/dependency-suggestions")
    row = next(s for s in sug if s["title"].startswith("Understanding of Business Models"))
    assert row["text"] == "Business Scenario Identification"
    assert [m["title"] for m in row["matches"]] == ["Business Scenario Identification"] and row["unambiguous"]
    phase_row = next(s for s in sug if s["text"] == "Project Kick Off")
    assert phase_row["matches"] == [] and phase_row["phase_refs"] == ["Project Kick Off"]  # a phase, not a task: not guessed
    exact = [s for s in sug if s["unambiguous"]]
    assert exact
    res = client.post(f"{API}/projects/{pid}/dependencies/bulk", json={"pairs": [{"predecessor_id": s["matches"][0]["id"], "successor_id": s["work_item_id"]} for s in exact]}, headers=admin).json()
    assert res["created"] + len(res["skipped"]) == len(exact) and res["created"] > 0
    assert len(get(client, admin, f"/projects/{pid}/dependencies")) == res["created"]
    detail = get(client, admin, f"/projects/{pid}/work-items/{row['work_item_id']}")
    assert [p["title"] for p in detail["predecessors"]] == ["Business Scenario Identification"]
    # applied suggestions are not offered again
    assert not [s for s in get(client, admin, f"/projects/{pid}/dependency-suggestions") if s["work_item_id"] == row["work_item_id"] and s["matches"]]


def test_dependency_rules(client, admin):
    pid, _ = setup_project(client, admin)
    a, b, c = (new_item(client, admin, pid, title=t)["id"] for t in "ABC")
    dep = lambda succ, pred: client.post(f"{API}/projects/{pid}/work-items/{succ}/dependencies", json={"predecessor_id": pred}, headers=admin)  # noqa: E731
    assert dep(b, a).status_code == 201 and dep(c, b).status_code == 201
    assert dep(b, a).status_code == 409  # duplicate
    assert dep(a, a).status_code == 422  # self
    r = dep(a, c)  # C <- B <- A, so A <- C closes a loop
    assert r.status_code == 422 and "loop" in r.json()["detail"]
    assert dep(a, str(uuid.uuid4())).status_code == 404  # unknown item
    other_pid, _ = None, None
    link = get(client, admin, f"/projects/{pid}/dependencies")[0]["id"]
    assert client.delete(f"{API}/projects/{pid}/dependencies/{link}", headers=admin).status_code == 204


# ======================================================================= phase -> product, product views
def test_phase_product_assignment_and_product_view(client, admin):
    pid, prods = setup_project(client, admin)
    import_plan(client, admin, pid)
    phases = get(client, admin, f"/projects/{pid}/phases")
    mes = next(p for p in phases if p["name"].startswith("MES – Current State"))
    n_phase = len([i for i in items(client, admin, pid)["items"] if i["phase_id"] == mes["id"]])
    assert n_phase > 0
    r = client.post(f"{API}/projects/{pid}/phases/{mes['id']}/assign-product", json={"product_id": prods["MES"]}, headers=admin)
    assert r.status_code == 200 and r.json()["updated"] == n_phase
    total = items(client, admin, pid)["total"]
    mes_only = items(client, admin, pid, product_id=prods["MES"], include_unassigned="false")["total"]
    mes_plus_wide = items(client, admin, pid, product_id=prods["MES"])["total"]
    plm_view = items(client, admin, pid, product_id=prods["PLM"])["total"]
    assert mes_only == n_phase and mes_plus_wide == total and plm_view == total - n_phase  # PLM sees project-wide tasks, not MES-only ones
    assert client.post(f"{API}/projects/{pid}/phases/{mes['id']}/assign-product", json={"product_id": None}, headers=admin).json()["updated"] == n_phase
    assert items(client, admin, pid, product_id=prods["MES"], include_unassigned="false")["total"] == 0
    audit = get(client, admin, "/audit-logs?entity_type=project_phase")["items"]
    assert len(audit) == 2


# ======================================================================= pending register
def test_pending_register_views_overdue_and_revisions(client, admin):
    pid, _ = setup_project(client, admin)
    mk = lambda **k: client.post(f"{API}/projects/{pid}/pending-items", json=k, headers=admin)  # noqa: E731
    c1 = mk(pending_with="customer", description="Tegra to approve BBP", owner_name="Darwin", original_target_date="2026-11-10").json()
    mk(pending_with="customer", description="UAT criteria from Tegra", original_target_date="2026-12-18")
    w1 = mk(pending_with="wfx", description="WFX to submit gap specs", owner_name="Mayank", original_target_date="2026-11-12").json()
    mk(pending_with="external", description="Courier API docs", original_target_date="2026-11-01")
    lst = lambda **k: get(client, admin, f"/projects/{pid}/pending-items?as_of={AS_OF}&" + "&".join(f"{a}={b}" for a, b in k.items()))  # noqa: E731
    assert lst(pending_with="customer")["total"] == 2 and lst(pending_with="wfx")["total"] == 1 and lst(pending_with="external")["total"] == 1
    assert lst(overdue="true")["total"] == 3  # 10-Nov, 12-Nov, 01-Nov are before 17-Nov
    summ = get(client, admin, f"/projects/{pid}/pending-summary?as_of={AS_OF}")["by_owner"]
    assert summ["customer"] == {"open": 2, "overdue": 1, "closed": 0} and summ["wfx"]["overdue"] == 1
    # baseline target date is immutable; a revision moves it and the history keeps both
    assert client.patch(f"{API}/projects/{pid}/pending-items/{c1['id']}", json={"original_target_date": "2026-12-01"}, headers=admin).status_code == 422
    r = client.post(f"{API}/projects/{pid}/pending-items/{c1['id']}/revisions", json={"field": "ignored", "new_date": "2026-11-25", "reason": "Customer asked for time", "approve": True}, headers=admin)
    assert r.status_code == 201 and r.json()[0]["field"] == "target_date"
    cur = get(client, admin, f"/projects/{pid}/pending-items/{c1['id']}?as_of={AS_OF}")
    assert cur["original_target_date"] == "2026-11-10" and cur["revised_target_date"] == "2026-11-25" and cur["is_overdue"] is False and cur["slippage_days"] == 15
    # closing: status + actual closure
    done = client.patch(f"{API}/projects/{pid}/pending-items/{w1['id']}", json={"status": "done", "actual_closure_date": "2026-11-13"}, headers=admin).json()
    assert done["is_closed"] and not done["is_overdue"]
    assert lst(open_only="true", overdue="true")["total"] == 1  # only the courier docs remain late and open
    assert client.delete(f"{API}/projects/{pid}/pending-items/{w1['id']}", headers=admin).status_code == 204
    assert mk(pending_with="nobody", description="x").status_code == 422


# ======================================================================= pending import from the real Shahi file
def _shahi_oracle():
    ws = openpyxl.load_workbook(SHAHI, data_only=True)["Pending Items"]
    by_resp, revised, completed, closed, rows = Counter(), 0, 0, 0, 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] and not any(row[1:]):
            continue  # section row
        if not row[1] or row[1] == "Responsibility":
            continue
        rows += 1
        by_resp[row[1]] += 1
        revised += hasattr(row[3], "date")
        completed += isinstance(row[2], str) and row[2].strip().lower() == "completed"
        closed += hasattr(row[4], "date")
    return by_resp, revised, completed, closed, rows


def test_import_real_shahi_pending_items_with_classification(client, admin):
    pid, _ = setup_project(client, admin)
    b = get(client, admin, f"/imports/{upload(client, admin, SHAHI).json()['id']}")
    sh = next(s for s in b["sheets"] if s["name"] == "Pending Items")
    assert sh["classification"] == "dependency_register" and sh["entity"] == "dependency_item" and sh["enabled"] is True
    # enable only this sheet; confirm any medium mappings
    for s in b["sheets"]:
        if s["id"] != sh["id"]:
            client.patch(f"{API}/imports/{b['id']}/sheets/{s['id']}", json={"enabled": False}, headers=admin)
    det = get(client, admin, f"/imports/{b['id']}/sheets/{sh['id']}")
    m = {c["header"]: c["mapping"]["target_field"] for c in det["columns"]}
    assert m["Components"] == "description" and m["Responsibility"] == "pending_with" and m["Responsibility (WFX Owner)"] == "owner_name"
    assert m["Target Date"] == "original_target_date" and m["Revised Target Date"] == "revised_target_date" and m["Actual Closure Date"] == "actual_closure_date"
    items_ = [{"column_id": c["id"], "target_field": c["mapping"]["target_field"]} for c in det["columns"] if c["mapping"] and c["mapping"]["level"] == "medium" and c["mapping"]["status"] == "suggested"]
    if items_:
        client.put(f"{API}/imports/{b['id']}/sheets/{sh['id']}/mappings", json={"mappings": items_}, headers=admin)
    # "WFX" is known; "Shahi" is not guessed: blocked until the user decides
    pw = {p["value"]: p["category"] for p in get(client, admin, f"/imports/{b['id']}/sheets/{sh['id']}")["pending_with_values"]}
    assert pw["WFX"] == "wfx" and pw["Shahi"] is None
    v = client.post(f"{API}/imports/{b['id']}/validate", headers=admin).json()
    s = next(x for x in v["sheets"] if x["name"] == "Pending Items")
    assert any(x["code"] == "pending_with_unresolved" for x in s["blocking"]) and not v["can_commit"]
    assert client.patch(f"{API}/imports/{b['id']}/sheets/{sh['id']}", json={"pending_with_map": {"Shahi": "boss"}}, headers=admin).status_code == 422
    client.patch(f"{API}/imports/{b['id']}/sheets/{sh['id']}", json={"pending_with_map": {"Shahi": "customer"}}, headers=admin)
    v = client.post(f"{API}/imports/{b['id']}/validate", headers=admin).json()
    s = next(x for x in v["sheets"] if x["name"] == "Pending Items")
    assert not s["blocking"] and s["rejected_rows"] == 3  # rows 3, 31, 33 have a description but nobody is named: listed, never silent
    codes = {e["code"] for e in get(client, admin, f"/imports/{b['id']}/errors?size=200")["items"]}
    assert {"missing_required", "unknown_date", "hidden_rows"} <= codes
    r = client.post(f"{API}/imports/{b['id']}/commit", json={"project_id": pid, "confirm_rejected": True}, headers=admin)
    assert r.status_code == 200, r.text
    by_resp, revised, completed, closed, rows = _shahi_oracle()
    summ = get(client, admin, f"/projects/{pid}/pending-summary?as_of={AS_OF}")["by_owner"]
    total = lambda k: summ[k]["open"] + summ[k]["closed"]  # noqa: E731
    assert total("customer") == by_resp["Shahi"] and total("wfx") == by_resp["WFX"]
    allp = get(client, admin, f"/projects/{pid}/pending-items?size=500&as_of={AS_OF}")["items"]
    assert len(allp) == rows
    assert sum(1 for p in allp if p["is_closed"]) >= completed  # "Completed" typed in the date column means closed
    comp = [p for p in allp if p["original_target_date"] is None and p["is_closed"]]
    assert comp and all(p["status_raw"] == "Closed" for p in comp)
    assert any(p["category"] == "Finance" for p in allp) and any(p["category"] and p["category"].startswith("Tech Document") for p in allp)
    # source "Revised Target Date" became an approved entry in the revision history
    with_rev = next(p for p in allp if p["revised_target_date"])
    hist = get(client, admin, f"/projects/{pid}/pending-items/{with_rev['id']}")["revisions"]
    assert len(hist) == 1 and hist[0]["status"] == "approved" and hist[0]["reason"].startswith("Imported from")
    assert sum(1 for p in allp if p["revised_target_date"]) == revised
    sug = {x["key"]: x for x in get(client, admin, f"/imports/{b['id']}/dashboard-suggestions")}
    assert sug["delay_dashboard"]["available"] and sug["delay_dashboard"]["sources"] == ["dependency_item"]  # pending items feed the delay view
    assert not sug["overall_status"]["available"]
    # rolling back removes the items (their imported revisions are history rows tied to them)
    assert client.post(f"{API}/imports/{b['id']}/rollback", headers=admin).status_code == 200
    assert get(client, admin, f"/projects/{pid}/pending-items")["total"] == 0


# ======================================================================= flex field values
def test_flex_field_values_per_customer_with_validation(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    cust = client.get(f"{API}/projects/{pid}", headers=admin).json()["customer_id"]
    other = client.post(f"{API}/customers", json={"code": "OTHER", "name": "Other"}, headers=admin).json()["id"]
    mk = lambda **k: client.post(f"{API}/custom-fields", json={"entity_type": "work_item", **k}, headers=admin)  # noqa: E731
    dd = mk(customer_id=cust, field_type="dropdown", slot=1, label="Risk level", options=["Low", "Medium", "High"]).json()
    dt = mk(customer_id=cust, field_type="date", slot=1, label="Customer deadline").json()
    tx = mk(customer_id=cust, field_type="text", slot=1, label="Ticket ref", is_required=False).json()
    mk(customer_id=other, field_type="text", slot=1, label="Other customer's field")
    w = new_item(client, admin, pid)
    url = f"{API}/custom-field-values/work_item/{w['id']}"
    shown = client.get(url, headers=admin).json()
    assert {f["label"] for f in shown} == {"Risk level", "Customer deadline", "Ticket ref"}  # not the other customer's
    ok = client.put(url, json={"values": [{"definition_id": dd["id"], "value": "High"}, {"definition_id": dt["id"], "value": "2026-12-05"}, {"definition_id": tx["id"], "value": "INC-42"}]}, headers=admin)
    assert ok.status_code == 200
    got = {f["label"]: f["value"] for f in client.get(url, headers=admin).json()}
    assert got == {"Risk level": "High", "Customer deadline": "2026-12-05", "Ticket ref": "INC-42"}
    assert client.put(url, json={"values": [{"definition_id": dd["id"], "value": "Extreme"}]}, headers=admin).status_code == 422
    assert client.put(url, json={"values": [{"definition_id": dt["id"], "value": "next tuesday"}]}, headers=admin).status_code == 422
    assert client.put(url, json={"values": [{"definition_id": str(uuid.uuid4()), "value": "x"}]}, headers=admin).status_code == 422
    client.put(url, json={"values": [{"definition_id": tx["id"], "value": ""}]}, headers=admin)  # clearing
    assert {f["label"]: f["value"] for f in client.get(url, headers=admin).json()}["Ticket ref"] is None
    # record-level access: a user without the project cannot read or write
    _, qa = make_user("qa")
    assert client.get(url, headers=qa).status_code == 404
    assert client.put(url, json={"values": []}, headers=qa).status_code in (403, 404)
    assert client.get(f"{API}/custom-field-values/bogus/{w['id']}", headers=admin).status_code == 404


def test_pending_with_skip_choice_and_completed_in_date_column(client, admin):
    pid, _ = setup_project(client, admin)
    csv_bytes = "\n".join([
        "Components,Responsibility,Target Date,Revised Target Date,Actual Closure Date",
        "Approve BBP,Tegra,2026-11-10,2026-11-25,",
        "Responsibility,Responsibility,,,",
        "Sign UAT criteria,Tegra,Completed,,",
        "Submit gap specs,WFX,2026-11-12,TBA,",
    ]).encode()
    up = client.post(f"{API}/imports", files={"file": ("pending.csv", csv_bytes, "text/csv")}, headers=admin).json()
    b = get(client, admin, f"/imports/{up['id']}")
    sh = b["sheets"][0]
    assert sh["entity"] == "dependency_item"
    det = get(client, admin, f"/imports/{b['id']}/sheets/{sh['id']}")
    medium = [{"column_id": c["id"], "target_field": c["mapping"]["target_field"]} for c in det["columns"] if c["mapping"]["level"] == "medium" and c["mapping"]["status"] == "suggested"]
    if medium:
        client.put(f"{API}/imports/{b['id']}/sheets/{sh['id']}/mappings", json={"mappings": medium}, headers=admin)
    client.patch(f"{API}/imports/{b['id']}/sheets/{sh['id']}", json={"pending_with_map": {"Tegra": "customer", "Responsibility": "ignore"}}, headers=admin)
    v = client.post(f"{API}/imports/{b['id']}/validate", headers=admin).json()
    assert v["can_commit"] and v["sheets"][0]["rejected_rows"] == 1
    codes = {e["code"] for e in get(client, admin, f"/imports/{b['id']}/errors?size=50")["items"]}
    assert "skipped_by_choice" in codes and "unknown_date" in codes  # TBA revised date warned; "Completed" target date was NOT flagged
    assert "invalid_date" not in codes
    assert client.post(f"{API}/imports/{b['id']}/commit", json={"project_id": pid}, headers=admin).status_code == 409  # rejected row needs a confirmation
    assert client.post(f"{API}/imports/{b['id']}/commit", json={"project_id": pid, "confirm_rejected": True}, headers=admin).status_code == 200
    got = {p["description"]: p for p in get(client, admin, f"/projects/{pid}/pending-items?as_of={AS_OF}")["items"]}
    assert set(got) == {"Approve BBP", "Sign UAT criteria", "Submit gap specs"}
    assert got["Sign UAT criteria"]["is_closed"] and got["Sign UAT criteria"]["status_raw"] == "Closed" and got["Sign UAT criteria"]["original_target_date"] is None
    assert got["Approve BBP"]["revised_target_date"] == "2026-11-25" and got["Approve BBP"]["pending_with"] == "customer"
    assert got["Submit gap specs"]["pending_with"] == "wfx" and got["Submit gap specs"]["revised_target_date"] is None
