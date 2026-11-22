"""Stage 3: interactive Gantt back end (reschedule by drag/resize, dependency rules, critical milestones, phases, percent complete)."""
from datetime import date

from test_phase2 import get, setup_project
from test_phase3 import import_plan, new_item
from test_stage1 import member

API = "/api/v1"
AS_OF = "2026-11-17"


def item(client, hdr, pid, wid):
    return get(client, hdr, f"/projects/{pid}/work-items/{wid}?as_of={AS_OF}")


def resched(client, hdr, pid, wid, **body):
    return client.post(f"{API}/projects/{pid}/work-items/{wid}/reschedule", json={"reason": "customer asked", "approve": True, **body}, headers=hdr)


def listing(client, hdr, pid):
    return {i["id"]: i for i in get(client, hdr, f"/projects/{pid}/work-items?size=500&as_of={AS_OF}")["items"]}


def link(client, hdr, pid, pred, succ, lag=0):
    return client.post(f"{API}/projects/{pid}/work-items/{succ}/dependencies", json={"predecessor_id": pred, "lag_days": lag}, headers=hdr)


# ======================================================================= move and resize
def test_move_and_resize_keep_the_baseline_and_record_revisions(client, admin):
    pid, _ = setup_project(client, admin)
    t = new_item(client, admin, pid, title="Blueprint", planned_start="2026-11-01", planned_finish="2026-11-10")
    r = resched(client, admin, pid, t["id"], start="2026-11-05", finish="2026-11-14")  # drag the whole bar
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["applied"] and len(out["revisions"]) == 2
    cur = item(client, admin, pid, t["id"])
    assert (cur["planned_start"], cur["planned_finish"]) == ("2026-11-01", "2026-11-10")  # baseline never overwritten
    assert (cur["effective_start"], cur["effective_finish"]) == ("2026-11-05", "2026-11-14") and cur["slippage_days"] == 4
    assert {x["reason"] for x in cur["revisions"]} == {"customer asked"} and all(x["status"] == "approved" for x in cur["revisions"])
    # resize: only the finish changes -> exactly one more revision, old date recorded
    r = resched(client, admin, pid, t["id"], finish="2026-11-20", reason="scope grew")
    assert len(r.json()["revisions"]) == 1
    cur = item(client, admin, pid, t["id"])
    assert cur["effective_finish"] == "2026-11-20" and len(cur["revisions"]) == 3
    assert cur["revisions"][-1]["old_date"] == "2026-11-14" and cur["revisions"][-1]["new_date"] == "2026-11-20"
    # moving earlier than the original is allowed too (start first, so the range stays valid)
    assert resched(client, admin, pid, t["id"], start="2026-10-20", finish="2026-10-25").status_code == 200
    assert item(client, admin, pid, t["id"])["effective_start"] == "2026-10-20"
    audit = [a["action"] for a in get(client, admin, f"/audit-logs?entity_type=date_revision&size=50")["items"]]
    assert audit.count("create") >= 5 and "approve_revision" in audit


def test_reschedule_validation(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    t = new_item(client, admin, pid, title="T", planned_start="2026-11-01", planned_finish="2026-11-10")
    assert resched(client, admin, pid, t["id"], start="2026-11-12").status_code == 422  # finish would precede start
    assert resched(client, admin, pid, t["id"], start="2026-11-01", finish="2026-11-10").status_code == 422  # nothing changed
    assert resched(client, admin, pid, t["id"]).status_code == 422
    assert client.post(f"{API}/projects/{pid}/work-items/{t['id']}/reschedule", json={"finish": "2026-11-12", "reason": "x"}, headers=admin).status_code == 422  # reason needed
    dev = member(client, admin, make_user, "developer", pid)
    assert resched(client, dev, pid, t["id"], finish="2026-11-12").status_code == 403  # read-only roles cannot move bars
    # unapproved: a proposal only; nothing moves until someone approves it
    r = resched(client, admin, pid, t["id"], finish="2026-11-15", approve=False).json()
    assert not r["applied"] and r["item"]["effective_finish"] == "2026-11-10"
    assert listing(client, admin, pid)[t["id"]]["has_pending_revision"] is True
    rev = r["revisions"][0]
    assert client.post(f"{API}/projects/{pid}/revisions/{rev['id']}/decision", json={"approve": True}, headers=admin).status_code == 200
    now = listing(client, admin, pid)[t["id"]]
    assert now["effective_finish"] == "2026-11-15" and now["has_pending_revision"] is False
    # a milestone is one date: moving it sets both
    m = new_item(client, admin, pid, title="Go-live", kind="milestone", planned_start="2026-12-01", planned_finish="2026-12-01")
    mv = resched(client, admin, pid, m["id"], start="2026-12-05").json()["item"]
    assert mv["effective_start"] == mv["effective_finish"] == "2026-12-05"


def test_dependency_rules_while_scheduling(client, admin):
    pid, _ = setup_project(client, admin)
    a = new_item(client, admin, pid, title="A", planned_start="2026-11-01", planned_finish="2026-11-10")
    b = new_item(client, admin, pid, title="B", planned_start="2026-11-10", planned_finish="2026-11-20")
    ok = link(client, admin, pid, a["id"], b["id"])
    assert ok.status_code == 201 and ok.json()["warnings"] == []  # B starts the day A finishes: allowed
    assert link(client, admin, pid, b["id"], a["id"]).status_code == 422  # loop
    assert link(client, admin, pid, a["id"], a["id"]).status_code == 422
    bad = resched(client, admin, pid, b["id"], start="2026-11-05", finish="2026-11-15")
    assert bad.status_code == 422 and "predecessor 'A'" in bad.json()["detail"]  # cannot start before A finishes
    assert item(client, admin, pid, b["id"])["effective_start"] == "2026-11-10"  # and nothing was saved
    assert resched(client, admin, pid, b["id"], start="2026-11-12", finish="2026-11-22").status_code == 200
    # pushing the predecessor later squeezes the successor: allowed, but reported
    r = resched(client, admin, pid, a["id"], finish="2026-11-18").json()
    assert [c["title"] for c in r["successor_conflicts"]] == ["B"] and r["successor_conflicts"][0]["earliest"] == "2026-11-18"
    links = get(client, admin, f"/projects/{pid}/dependencies?as_of={AS_OF}")
    assert len(links) == 1 and links[0]["slack_days"] == -6 and links[0]["violated"] and links[0]["critical"]
    # lag counts
    c = new_item(client, admin, pid, title="C", planned_start="2026-12-01", planned_finish="2026-12-05")
    d = new_item(client, admin, pid, title="D", planned_start="2026-12-05", planned_finish="2026-12-09")
    w = link(client, admin, pid, c["id"], d["id"], lag=3).json()["warnings"]
    assert len(w) == 1 and "3 day(s) before" in w[0]
    assert resched(client, admin, pid, d["id"], start="2026-12-08", finish="2026-12-11").status_code == 200  # 5 Dec + 3 lag = 8 Dec is the earliest
    assert resched(client, admin, pid, d["id"], start="2026-12-07", finish="2026-12-11").status_code == 422


def test_critical_milestones_and_slack_follow_the_rule(client, admin):
    pid, _ = setup_project(client, admin)
    late = new_item(client, admin, pid, title="Late task", planned_start="2026-10-01", planned_finish="2026-11-01")  # open and overdue on AS_OF
    ms = new_item(client, admin, pid, title="Sign-off", kind="milestone", planned_start="2026-12-20", planned_finish="2026-12-20")
    calm = new_item(client, admin, pid, title="Calm milestone", kind="milestone", planned_start="2026-12-30", planned_finish="2026-12-30")
    link(client, admin, pid, late["id"], ms["id"])
    got = listing(client, admin, pid)
    assert got[ms["id"]]["is_critical_milestone"] and got[ms["id"]]["blocked_by_late"]  # an overdue predecessor blocks it
    assert not got[calm["id"]]["is_critical_milestone"] and not got[late["id"]]["is_critical_milestone"]  # tasks are never 'critical milestones'
    link_row = get(client, admin, f"/projects/{pid}/dependencies?as_of={AS_OF}")[0]
    assert link_row["slack_days"] == 49 and not link_row["violated"] and not link_row["critical"]  # lots of room
    client.patch(f"{API}/projects/{pid}/work-items/{late['id']}", json={"status": "done", "actual_finish": "2026-11-01"}, headers=admin)
    assert not listing(client, admin, pid)[ms["id"]]["blocked_by_late"]  # closed predecessors stop blocking
    # a milestone that is itself overdue is critical
    old = new_item(client, admin, pid, title="Missed gate", kind="milestone", planned_start="2026-11-05", planned_finish="2026-11-05")
    assert listing(client, admin, pid)[old["id"]]["is_critical_milestone"]


def test_slack_matches_an_independent_calculation_on_the_tegra_plan(client, admin):
    pid, _ = setup_project(client, admin)
    import_plan(client, admin, pid)
    sug = get(client, admin, f"/projects/{pid}/dependency-suggestions")
    pairs = [{"predecessor_id": s["matches"][0]["id"], "successor_id": s["work_item_id"]} for s in sug if s["unambiguous"]]
    assert client.post(f"{API}/projects/{pid}/dependencies/bulk", json={"pairs": pairs}, headers=admin).json()["created"] > 0
    items = listing(client, admin, pid)
    links = get(client, admin, f"/projects/{pid}/dependencies?as_of={AS_OF}")
    assert links
    for l in links:
        p, s = items[l["predecessor_id"]], items[l["successor_id"]]
        if p["effective_finish"] and s["effective_start"]:
            want = (date.fromisoformat(s["effective_start"]) - date.fromisoformat(p["effective_finish"])).days - l["lag_days"]
            assert l["slack_days"] == want and l["violated"] == (want < 0)
            assert l["critical"] == ((not p["is_closed"]) and want <= 0)


# ======================================================================= phases and percent
def test_phases_add_rename_remove(client, admin):
    pid, _ = setup_project(client, admin)
    ph = client.post(f"{API}/projects/{pid}/phases", json={"name": "  UAT   Preparation "}, headers=admin)
    assert ph.status_code == 201 and ph.json()["name"] == "UAT Preparation"  # spaces normalised
    assert client.post(f"{API}/projects/{pid}/phases", json={"name": "uat preparation"}, headers=admin).status_code == 409
    assert client.patch(f"{API}/projects/{pid}/phases/{ph.json()['id']}", json={"name": "UAT Prep"}, headers=admin).json()["name"] == "UAT Prep"
    t = new_item(client, admin, pid, title="Scenario", phase_id=ph.json()["id"])
    assert listing(client, admin, pid)[t["id"]]["phase_name"] == "UAT Prep"
    assert client.delete(f"{API}/projects/{pid}/phases/{ph.json()['id']}", headers=admin).status_code == 409  # not empty
    client.post(f"{API}/projects/{pid}/lifecycle/work_item/{t['id']}/archive", json={}, headers=admin)
    assert client.delete(f"{API}/projects/{pid}/phases/{ph.json()['id']}", headers=admin).status_code == 409  # archived tasks still count
    client.post(f"{API}/projects/{pid}/lifecycle/work_item/{t['id']}/delete", json={}, headers=admin)
    client.post(f"{API}/projects/{pid}/lifecycle/work_item/{t['id']}/purge", json={"confirm": True}, headers=admin)
    assert client.delete(f"{API}/projects/{pid}/phases/{ph.json()['id']}", headers=admin).status_code == 204
    assert [p["name"] for p in get(client, admin, f"/projects/{pid}/phases")] == []
    assert {"create", "update", "delete"} <= {a["action"] for a in get(client, admin, "/audit-logs?entity_type=project_phase&size=20")["items"]}


def test_percent_complete_is_validated_and_never_silently_changes_status(client, admin):
    pid, _ = setup_project(client, admin)
    t = new_item(client, admin, pid, title="T")
    assert client.patch(f"{API}/projects/{pid}/work-items/{t['id']}", json={"percent_complete": 101}, headers=admin).status_code == 422
    assert client.patch(f"{API}/projects/{pid}/work-items/{t['id']}", json={"percent_complete": -1}, headers=admin).status_code == 422
    r = client.patch(f"{API}/projects/{pid}/work-items/{t['id']}", json={"percent_complete": 60}, headers=admin).json()
    assert r["percent_complete"] == 60 and r["status_category"] == "not_started" and not r["percent_mismatch"]  # status untouched
    r = client.patch(f"{API}/projects/{pid}/work-items/{t['id']}", json={"percent_complete": 100}, headers=admin).json()
    assert r["percent_mismatch"] is True  # 100% but still open: flagged, not auto-closed
    r = client.patch(f"{API}/projects/{pid}/work-items/{t['id']}", json={"status": "done", "actual_finish": "2026-11-10"}, headers=admin).json()
    assert r["percent_mismatch"] is False
    r = client.patch(f"{API}/projects/{pid}/work-items/{t['id']}", json={"percent_complete": 40}, headers=admin).json()
    assert r["percent_mismatch"] is True  # done but 40%


def test_rescheduling_an_overdue_task_clears_it_from_the_dashboard(client, admin):
    pid, _ = setup_project(client, admin)
    t = new_item(client, admin, pid, title="Late", planned_start="2026-10-01", planned_finish="2026-11-01")
    over = lambda: get(client, admin, f"/projects/{pid}/dashboards/drilldown/overdue?as_of={AS_OF}")["total"]  # noqa: E731
    assert over() == 1
    assert resched(client, admin, pid, t["id"], finish="2026-12-01", reason="new plan agreed").status_code == 200
    assert over() == 0
    k = get(client, admin, f"/projects/{pid}/dashboards/overall?as_of={AS_OF}")["kpis"]["activities"]
    assert k["overdue"] == 0
