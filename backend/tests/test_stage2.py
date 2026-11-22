"""Stage 2: KPI drill-down. The list behind a tile must be the same records the tile counted, checked against the raw Tegra workbooks."""
from datetime import date, timedelta

from test_phase2 import get
from test_phase4 import AO, AS_OF, GATE, full_setup, raw_events, raw_tasks

API = "/api/v1"


def drill(client, hdr, pid, metric, **params):
    q = "&".join([f"as_of={params.pop('as_of', AS_OF)}"] + [f"{k}={v}" for k, v in params.items()])
    return get(client, hdr, f"/projects/{pid}/dashboards/drilldown/{metric}?{q}")


def overall(client, hdr, pid):
    return get(client, hdr, f"/projects/{pid}/dashboards/overall?as_of={AS_OF}")


def oracle():
    """Independent counts from the raw files: plan tasks + tracker events."""
    tasks, events = raw_tasks(), raw_events()
    ev = [{"closed": e[3] is not None, "over": e[3] is None and e[2] is not None and e[2] < AO, "name": e[1], "end": e[2] or e[3]} for e in events]
    t_open_ms = sum(1 for t in tasks if not t["closed"] and GATE.search(str(t["title"])) and t["end"] and t["end"] >= AO)
    e_open_ms = sum(1 for e in ev if not e["closed"] and GATE.search(str(e["name"])) and e["end"] and e["end"] >= AO)
    return {
        "all": len(tasks) + len(ev),
        "completed": sum(t["closed"] for t in tasks) + sum(e["closed"] for e in ev),
        "in_progress": sum(t["ip"] for t in tasks),
        "overdue": sum(t["over"] for t in tasks) + sum(e["over"] for e in ev),
        "upcoming_milestones": t_open_ms + e_open_ms,
    }


def test_tiles_and_lists_reconcile_with_the_raw_files(client, admin):
    pid, _ = full_setup(client, admin)
    want = oracle()
    act = overall(client, admin, pid)["kpis"]["activities"]
    for m in ("all", "completed", "in_progress", "overdue", "upcoming_milestones"):
        assert act[m] == want[m], (m, act[m], want[m])  # the tile equals the independent count
        d = drill(client, admin, pid, m, size=100)
        assert d["total"] == act[m] and d["unfiltered_total"] == act[m]  # and the list behind it has exactly that many records
        assert d["rule"] and d["label"]
    assert act["phases"] == 22  # 16 plan phases + 6 tracker groups
    ph = drill(client, admin, pid, "phases")
    assert ph["total"] == 22 and {"label", "state", "pct", "late_items"} <= set(ph["items"][0])
    # every record is in exactly one of the exclusive states
    assert act["all"] == sum(drill(client, admin, pid, m, size=1)["total"] for m in ("completed", "in_progress", "overdue", "not_started")) - _overlap(client, admin, pid)


def _overlap(client, admin, pid):
    """Overdue tasks can also be in progress; count the intersection so the partition check is exact."""
    over = {r["id"] for r in drill(client, admin, pid, "overdue", size=100)["items"]}
    ip = {r["id"] for r in drill(client, admin, pid, "in_progress", size=100)["items"]}
    return len(over & ip)


def test_overdue_list_shows_owner_dates_delay_and_status(client, admin):
    pid, _ = full_setup(client, admin)
    d = drill(client, admin, pid, "overdue", size=100)
    assert d["total"] > 0
    tasks = [r for r in d["items"] if r["type"] == "task"]
    assert tasks
    for r in d["items"]:
        assert r["is_overdue"] and not r["is_closed"] and r["original_finish"] and r["days_late"] > 0
        cur = date.fromisoformat(r["current_finish"])
        assert r["days_late"] == (AO - cur).days  # delay = report date - current finish (grace is 0)
        assert {"owner", "responsible", "revised_finish", "status", "phase", "product"} <= set(r)
    assert [r["days_late"] for r in d["items"]] == sorted((r["days_late"] for r in d["items"]), reverse=True)  # default: most late first
    # a revision moves the current date, keeps the original, and the list shows both
    t = tasks[0]
    new = (AO + timedelta(days=10)).isoformat()
    rev = client.post(f"{API}/projects/{pid}/work-items/{t['id']}/revisions", json={"field": "planned_finish", "new_date": new, "reason": "customer rescheduled", "approve": True}, headers=admin)
    assert rev.status_code == 201, rev.text
    after = drill(client, admin, pid, "overdue", size=100)
    assert t["id"] not in {r["id"] for r in after["items"]} and after["total"] == d["total"] - 1
    moved = next(r for r in drill(client, admin, pid, "all", q=t["title"][:30], size=100)["items"] if r["id"] == t["id"])
    assert moved["original_finish"] == t["original_finish"] and moved["revised_finish"] == new and moved["current_finish"] == new and moved["slippage_days"] > 0


def test_edit_in_the_list_flows_back_into_tiles_and_lists(client, admin):
    pid, _ = full_setup(client, admin)
    before = overall(client, admin, pid)["kpis"]
    d = drill(client, admin, pid, "overdue", size=100)
    t = next(r for r in d["items"] if r["type"] == "task")
    assert client.patch(f"{API}/projects/{pid}/work-items/{t['id']}", json={"owner_name": "Meera Iyer"}, headers=admin).status_code == 200
    assert next(r for r in drill(client, admin, pid, "overdue", size=100)["items"] if r["id"] == t["id"])["owner"] == "Meera Iyer"
    assert drill(client, admin, pid, "overdue", owner="meera iyer")["total"] == 1  # owner filter is server side and case-insensitive
    assert client.patch(f"{API}/projects/{pid}/work-items/{t['id']}", json={"status": "done", "actual_finish": "2026-11-16"}, headers=admin).status_code == 200
    after = overall(client, admin, pid)["kpis"]
    a, b = before["activities"], after["activities"]
    assert (b["overdue"], b["completed"]) == (a["overdue"] - 1, a["completed"] + 1)
    assert b["overdue"] == drill(client, admin, pid, "overdue")["total"] and b["completed"] == drill(client, admin, pid, "completed")["total"]
    assert after["overall"]["done"] == before["overall"]["done"] + 1


def test_paging_sorting_search_and_product_scope(client, admin):
    pid, prods = full_setup(client, admin)
    allr = drill(client, admin, pid, "all", size=100)
    assert allr["total"] > 100 and len(allr["items"]) == 100  # never more than a page at a time
    p1, p2 = drill(client, admin, pid, "all", size=10, page=1), drill(client, admin, pid, "all", size=10, page=2)
    assert len(p1["items"]) == 10 and not ({r["id"] for r in p1["items"]} & {r["id"] for r in p2["items"]})
    asc = drill(client, admin, pid, "all", sort="title", direction="asc", size=30)["items"]
    assert [r["title"].lower() for r in asc] == sorted(r["title"].lower() for r in asc)
    cur = drill(client, admin, pid, "all", sort="current", direction="asc", size=100)["items"]
    dates = [r["current_finish"] for r in cur if r["current_finish"]]
    assert dates == sorted(dates)
    word = next(r["title"] for r in allr["items"]).split()[0]
    hit = drill(client, admin, pid, "all", q=word, size=100)
    assert 0 < hit["total"] <= allr["total"] and all(word.lower() in r["title"].lower() for r in hit["items"]) and hit["unfiltered_total"] == allr["total"]
    # product scope = the product view's scope (its tasks + project-wide tasks + its events)
    plm = drill(client, admin, pid, "all", product_id=prods["PLM"])
    prod_dash = get(client, admin, f"/projects/{pid}/dashboards/product/{prods['PLM']}?as_of={AS_OF}")
    assert plm["total"] == prod_dash["kpis"]["overall"]["total"]
    plm_late = drill(client, admin, pid, "overdue", product_id=prods["PLM"])
    assert plm_late["total"] == prod_dash["kpis"]["overall"]["overdue"]


def test_archived_records_leave_the_drilldown(client, admin):
    pid, _ = full_setup(client, admin)
    t = next(r for r in drill(client, admin, pid, "overdue", size=100)["items"] if r["type"] == "task")
    n = drill(client, admin, pid, "overdue")["total"]
    assert client.post(f"{API}/projects/{pid}/lifecycle/work_item/{t['id']}/archive", json={}, headers=admin).status_code == 200
    assert drill(client, admin, pid, "overdue")["total"] == n - 1 == overall(client, admin, pid)["kpis"]["activities"]["overdue"]
    assert client.post(f"{API}/projects/{pid}/lifecycle/work_item/{t['id']}/restore", json={}, headers=admin).status_code == 200
    assert drill(client, admin, pid, "overdue")["total"] == n


def test_drilldown_access_and_errors(client, admin, make_user):
    pid, _ = full_setup(client, admin)
    assert client.get(f"{API}/projects/{pid}/dashboards/drilldown/nonsense", headers=admin).status_code == 404
    assert client.get(f"{API}/projects/{pid}/dashboards/drilldown/overdue?sort=nonsense", headers=admin).status_code == 422
    assert client.get(f"{API}/projects/{pid}/dashboards/drilldown/overdue?size=1000", headers=admin).status_code == 422
    uid, outsider = make_user("project_manager")
    assert client.get(f"{API}/projects/{pid}/dashboards/drilldown/overdue", headers=outsider).status_code == 404  # no access to the project
    assert client.get(f"{API}/projects/{pid}/dashboards/drilldown/overdue").status_code == 401
    assert client.put(f"{API}/users/{uid}/project-access", json={"project_ids": [pid]}, headers=admin).status_code == 200
    assert client.get(f"{API}/projects/{pid}/dashboards/drilldown/overdue", headers=outsider).status_code == 200
