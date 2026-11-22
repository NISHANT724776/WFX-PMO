"""Stage 1 (manage foundation): archive / restore / trash / purge / duplicate / bulk, comments, attachments, action items."""
import io
import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.workspace import Attachment
from test_phase2 import get, setup_project
from test_phase3 import new_item

API = "/api/v1"


def life(client, hdr, pid, typ, rid, action, **body):
    return client.post(f"{API}/projects/{pid}/lifecycle/{typ}/{rid}/{action}", json=body or None, headers=hdr)


def total_tasks(client, hdr, pid):
    return get(client, hdr, f"/projects/{pid}/work-items?size=500")["total"]


def dash_total(client, hdr, pid):
    return get(client, hdr, f"/projects/{pid}/dashboards/overall")["kpis"]["overall"]["total"]


def member(client, admin, make_user, role, pid):
    uid, hdr = make_user(role)
    assert client.put(f"{API}/users/{uid}/project-access", json={"project_ids": [pid]}, headers=admin).status_code == 200
    return hdr


# ======================================================================= archive / trash / restore
def test_archive_hides_everywhere_and_restore_brings_back(client, admin):
    pid, _ = setup_project(client, admin)
    a, b, c = (new_item(client, admin, pid, title=t) for t in ("A", "B", "C"))
    dep = client.post(f"{API}/projects/{pid}/work-items/{b['id']}/dependencies", json={"predecessor_id": a["id"]}, headers=admin)
    assert dep.status_code in (200, 201), dep.text
    assert total_tasks(client, admin, pid) == 3 and dash_total(client, admin, pid) == 3
    assert len(get(client, admin, f"/projects/{pid}/dependencies")) == 1

    assert life(client, admin, pid, "work_item", a["id"], "archive").json()["state"] == "archived"
    assert total_tasks(client, admin, pid) == 2 and dash_total(client, admin, pid) == 2  # list and dashboard both recomputed
    assert client.get(f"{API}/projects/{pid}/work-items/{a['id']}", headers=admin).status_code == 404
    assert get(client, admin, f"/projects/{pid}/dependencies") == []  # the chart never points at a hidden task
    assert get(client, admin, f"/projects/{pid}/lifecycle")["work_item"] == {"archived": 1}
    assert [i["title"] for i in get(client, admin, f"/projects/{pid}/lifecycle/work_item?state=archived")["items"]] == ["A"]

    assert life(client, admin, pid, "work_item", a["id"], "archive").status_code == 409  # already archived
    assert life(client, admin, pid, "work_item", a["id"], "restore").json()["state"] == "active"
    assert total_tasks(client, admin, pid) == 3 and dash_total(client, admin, pid) == 3
    assert len(get(client, admin, f"/projects/{pid}/dependencies")) == 1  # dependency came back with it

    # audit shows who archived and restored
    acts = [x["action"] for x in get(client, admin, f"/audit-logs?entity_type=work_item&entity_id={a['id']}")["items"]]
    assert {"archive", "restore"} <= set(acts)


def test_trash_purge_rules_and_subtasks_travel_with_parent(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    parent = new_item(client, admin, pid, title="Parent")
    child = new_item(client, admin, pid, title="Child", parent_id=parent["id"])
    other = new_item(client, admin, pid, title="Other")
    assert client.delete(f"{API}/projects/{pid}/work-items/{parent['id']}", headers=admin).status_code == 204  # DELETE now means "to the trash"
    assert total_tasks(client, admin, pid) == 1
    trash = get(client, admin, f"/projects/{pid}/lifecycle/work_item?state=deleted")
    assert sorted(i["title"] for i in trash["items"]) == ["Child", "Parent"]
    assert life(client, admin, pid, "work_item", parent["id"], "restore").status_code == 200
    assert total_tasks(client, admin, pid) == 3  # the sub-task came back too

    life(client, admin, pid, "work_item", other["id"], "delete")
    assert life(client, admin, pid, "work_item", child["id"], "purge", confirm=True).status_code == 409  # not in the trash: refuse
    pm = member(client, admin, make_user, "project_manager", pid)
    assert life(client, pm, pid, "work_item", other["id"], "purge", confirm=True).status_code == 403  # editors cannot destroy
    assert life(client, admin, pid, "work_item", other["id"], "purge").status_code == 422  # confirmation is enforced by the server
    assert life(client, admin, pid, "work_item", other["id"], "purge", confirm=True).status_code == 200
    assert life(client, admin, pid, "work_item", other["id"], "restore").status_code == 404  # really gone
    assert total_tasks(client, admin, pid) == 2

    viewer = member(client, admin, make_user, "developer", pid)
    assert life(client, viewer, pid, "work_item", child["id"], "archive").status_code == 403  # read-only roles cannot manage


def test_duplicate_is_a_fresh_copy(client, admin):
    pid, _ = setup_project(client, admin)
    t = new_item(client, admin, pid, title="Blueprint", owner_name="Asha")
    rev = client.post(f"{API}/projects/{pid}/work-items/{t['id']}/revisions",
                      json={"field": "planned_finish", "new_date": "2026-11-20", "reason": "customer delay", "approve": True}, headers=admin)
    assert rev.status_code == 201, rev.text
    client.patch(f"{API}/projects/{pid}/work-items/{t['id']}", json={"actual_start": "2026-11-02"}, headers=admin)
    cp = life(client, admin, pid, "work_item", t["id"], "duplicate")
    assert cp.status_code == 200, cp.text
    new = get(client, admin, f"/projects/{pid}/work-items/{cp.json()['id']}")
    assert new["title"] == "Blueprint (copy)" and new["owner_name"] == "Asha" and new["planned_finish"] == "2026-11-10"
    assert new["revised_finish"] is None and new["actual_start"] is None  # history and actuals are not inherited
    assert total_tasks(client, admin, pid) == 2
    life(client, admin, pid, "work_item", t["id"], "archive")
    assert life(client, admin, pid, "work_item", t["id"], "duplicate").status_code == 409  # only active records


def test_bulk_update_is_all_or_nothing_and_delete_needs_confirm(client, admin):
    pid, _ = setup_project(client, admin)
    ids = [new_item(client, admin, pid, title=f"T{i}")["id"] for i in range(3)]
    url = f"{API}/projects/{pid}/lifecycle/work_item/bulk"
    ok = client.post(url, json={"ids": ids, "action": "update", "fields": {"owner_name": "Ravi", "status": "in_progress"}}, headers=admin)
    assert ok.status_code == 200 and ok.json()["done"] == 3
    rows = get(client, admin, f"/projects/{pid}/work-items")["items"]
    assert {r["owner_name"] for r in rows} == {"Ravi"} and {r["status_category"] for r in rows} == {"in_progress"}
    bad = client.post(url, json={"ids": ids, "action": "update", "fields": {"owner_name": "Zed", "status": "no_such_status"}}, headers=admin)
    assert bad.status_code == 422 and "nothing was changed" in bad.json()["detail"]
    assert {r["owner_name"] for r in get(client, admin, f"/projects/{pid}/work-items")["items"]} == {"Ravi"}  # untouched
    assert client.post(url, json={"ids": ids, "action": "update", "fields": {"planned_finish": "2026-12-01"}}, headers=admin).status_code == 422  # dates only via revisions
    assert client.post(url, json={"ids": [*ids, str(uuid.uuid4())], "action": "archive"}, headers=admin).status_code == 404  # unknown id stops everything
    assert total_tasks(client, admin, pid) == 3
    assert client.post(url, json={"ids": ids, "action": "delete"}, headers=admin).status_code == 422  # no confirm
    r = client.post(url, json={"ids": ids[:2], "action": "archive"}, headers=admin).json()
    assert r["done"] == 2 and total_tasks(client, admin, pid) == 1
    again = client.post(url, json={"ids": ids[:2], "action": "archive"}, headers=admin).json()
    assert again["done"] == 0 and len(again["skipped"]) == 2  # reported, not hidden
    assert client.post(url, json={"ids": ids[:2], "action": "delete", "confirm": True}, headers=admin).json()["done"] == 2


def test_records_list_states_and_facets(client, admin):
    pid, _ = setup_project(client, admin)
    mk = lambda d, s: client.post(f"{API}/projects/{pid}/records/delivery-items", json={"description": d, "stream": s}, headers=admin).json()  # noqa: E731
    x, y = mk("one", "Finance"), mk("two", "Finance")
    mk("three", "Logistics")
    life(client, admin, pid, "delivery_item", x["id"], "archive")
    assert get(client, admin, f"/projects/{pid}/records/delivery-items")["total"] == 2
    assert get(client, admin, f"/projects/{pid}/records/delivery-items?state=archived")["total"] == 1
    fac = {f["value"]: f["count"] for f in get(client, admin, f"/projects/{pid}/records/delivery-items/facets")["stream"]}
    assert fac == {"Finance": 1, "Logistics": 1}  # counts follow what is visible
    assert client.delete(f"{API}/projects/{pid}/records/delivery-items/{y['id']}", headers=admin).status_code == 204
    assert get(client, admin, f"/projects/{pid}/records/delivery-items?state=deleted")["total"] == 1


# ======================================================================= comments and attachments
def test_comments_permissions_and_audit(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    t = new_item(client, admin, pid, title="Task")
    dev = member(client, admin, make_user, "developer", pid)
    url = f"{API}/projects/{pid}/comments"
    body = {"entity_type": "work_item", "entity_id": t["id"], "body": "Waiting for the customer sample"}
    r = client.post(url, json=body, headers=dev)  # developers can comment although they cannot edit
    assert r.status_code == 201 and r.json()["author_email"] == "developer@example.com"
    assert client.patch(f"{API}/projects/{pid}/work-items/{t['id']}", json={"title": "x"}, headers=dev).status_code == 403
    cust = member(client, admin, make_user, "customer_user", pid)
    assert client.post(url, json=body, headers=cust).status_code == 403  # customers read only
    assert client.post(url, json={**body, "body": "   "}, headers=admin).status_code == 422
    assert client.post(url, json={**body, "entity_type": "nonsense"}, headers=admin).status_code == 404
    assert client.post(url, json={**body, "entity_id": str(uuid.uuid4())}, headers=admin).status_code == 404
    listed = get(client, admin, f"/projects/{pid}/comments?entity_type=work_item&entity_id={t['id']}")
    assert [c["body"] for c in listed] == ["Waiting for the customer sample"]
    qa = member(client, admin, make_user, "qa", pid)
    assert client.delete(f"{url}/{listed[0]['id']}", headers=qa).status_code == 403  # not yours, and you are not an editor
    assert client.delete(f"{url}/{listed[0]['id']}", headers=dev).status_code == 204
    assert "comment" in {a["action"] for a in get(client, admin, f"/audit-logs?entity_type=work_item&entity_id={t['id']}")["items"]}


def test_attachments_rules(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    t = new_item(client, admin, pid, title="Task")
    url = f"{API}/projects/{pid}/attachments"
    up = lambda name, data, hdr=admin: client.post(url, data={"entity_type": "work_item", "entity_id": t["id"], "note": "signed copy"},  # noqa: E731
                                                   files={"file": (name, io.BytesIO(data), "application/pdf")}, headers=hdr)
    ok = up("../../Sign-off form.pdf", b"%PDF-1.4 test")
    assert ok.status_code == 201, ok.text
    a = ok.json()
    assert a["filename"] == "Sign-off form.pdf" and a["size_bytes"] == 13 and a["note"] == "signed copy"  # path stripped from the label
    assert up("run.exe", b"MZ").status_code == 422 and up("noext", b"x").status_code == 422
    assert up("empty.txt", b"").status_code == 422
    dl = client.get(f"{url}/{a['id']}/download", headers=admin)
    assert dl.status_code == 200 and dl.content == b"%PDF-1.4 test" and dl.headers["content-type"] == "application/octet-stream"
    assert "attachment" in dl.headers["content-disposition"]
    with SessionLocal() as db:
        stored = db.scalar(select(Attachment.storage_name))
    assert stored and "Sign-off" not in stored  # stored under a generated name, never the user's
    other_pid, _ = None, None
    qa = member(client, admin, make_user, "qa", pid)
    assert client.delete(f"{url}/{a['id']}", headers=qa).status_code == 403  # not the uploader, not an editor
    assert len(get(client, admin, f"/projects/{pid}/attachments?entity_type=work_item&entity_id={t['id']}")) == 1
    assert client.delete(f"{url}/{a['id']}", headers=admin).status_code == 204
    assert client.get(f"{url}/{a['id']}/download", headers=admin).status_code == 404
    assert other_pid is None


def test_no_access_to_another_projects_records(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    t = new_item(client, admin, pid, title="Task")
    uid, outsider = make_user("project_manager")  # no grant on this project
    assert client.get(f"{API}/projects/{pid}/comments?entity_type=work_item&entity_id={t['id']}", headers=outsider).status_code == 404
    assert life(client, outsider, pid, "work_item", t["id"], "archive").status_code == 404
    assert client.post(f"{API}/projects/{pid}/lifecycle/work_item/bulk", json={"ids": [t["id"]], "action": "archive"}, headers=outsider).status_code == 404


# ======================================================================= action items (Needs Attention)
def test_action_item_workflow(client, admin):
    pid, prods = setup_project(client, admin)
    base = f"{API}/projects/{pid}/records/action-items"
    r = client.post(base, json={"title": "Chase customer for BOM sign-off", "owner_name": "Meera", "priority": "high", "due_date": "2026-11-10",
                                "product_id": prods["PLM"], "description": "Delay found on the dashboard"}, headers=admin)
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["status"] == "open" and a["last_action"] == "Created" and a["last_action_by"] == "admin@example.com"
    assert client.post(base, json={"title": "x", "priority": "urgent"}, headers=admin).status_code == 422
    assert client.post(base, json={"owner_name": "no title"}, headers=admin).status_code == 422
    late = get(client, admin, f"/projects/{pid}/records/action-items?overdue=true&as_of=2026-11-17")
    assert late["total"] == 1 and late["items"][0]["days_late"] == 7

    upd = client.patch(f"{base}/{a['id']}", json={"owner_name": "Ravi", "status": "in_progress"}, headers=admin).json()
    assert upd["owner_name"] == "Ravi" and upd["status"] == "in_progress" and upd["last_action"].startswith("Edited")
    assert client.patch(f"{base}/{a['id']}", json={"status": "resolved"}, headers=admin).status_code == 422  # resolving has its own step

    assert client.post(f"{base}/{a['id']}/escalate", json={"reason": "no reply in a week"}, headers=admin).status_code == 200
    esc = client.post(f"{base}/{a['id']}/escalate", json={"reason": "still nothing", "to": "Sponsor"}, headers=admin).json()
    assert esc["status"] == "escalated" and esc["escalation_level"] == 2 and esc["escalated_to"] == "Sponsor" and "Escalated (level 2)" in esc["last_action"]
    assert client.patch(f"{base}/{a['id']}", json={"status": "open"}, headers=admin).json()["status"] == "in_progress"  # never back to plain open

    assert client.post(f"{base}/{a['id']}/resolve", json={"reason": "x"}, headers=admin).status_code == 422  # a real note is required
    done = client.post(f"{base}/{a['id']}/resolve", json={"reason": "Sign-off received by mail"}, headers=admin).json()
    assert done["status"] == "resolved" and done["is_closed"] and not done["is_overdue"] and done["resolved_by_email"] == "admin@example.com"
    assert client.patch(f"{base}/{a['id']}", json={"status": "open"}, headers=admin).status_code == 409
    assert client.post(f"{base}/{a['id']}/escalate", json={"reason": "late again"}, headers=admin).status_code == 409
    assert client.post(f"{base}/{a['id']}/resolve", json={"reason": "again please"}, headers=admin).status_code == 409
    back = client.post(f"{base}/{a['id']}/reopen", json={"reason": "The mail was not from the approver"}, headers=admin).json()
    assert back["status"] == "open" and back["reopen_count"] == 1 and back["resolution_note"] is None
    assert client.post(f"{base}/{a['id']}/reopen", json={"reason": "not resolved"}, headers=admin).status_code == 409
    actions = [x["action"] for x in get(client, admin, f"/audit-logs?entity_type=action_item&entity_id={a['id']}&size=50")["items"]]
    assert {"create", "update", "escalated", "resolved", "reopened"} <= set(actions)  # the earlier resolution stays in history

    # a task from another project cannot be linked
    pid2 = client.post(f"{API}/projects", json={"customer_id": client.get(f"{API}/customers", headers=admin).json()["items"][0]["id"], "code": "P2", "name": "Other"},
                       headers=admin).json()["id"]
    foreign = new_item(client, admin, pid2, title="Foreign")
    assert client.patch(f"{base}/{a['id']}", json={"linked_work_item_id": foreign["id"]}, headers=admin).status_code == 422
    mine = new_item(client, admin, pid, title="Mine")
    assert client.patch(f"{base}/{a['id']}", json={"linked_work_item_id": mine["id"]}, headers=admin).status_code == 200

    # action items archive like everything else
    assert life(client, admin, pid, "action_item", a["id"], "archive").status_code == 200
    assert get(client, admin, f"/projects/{pid}/records/action-items")["total"] == 0
    cp = life(client, admin, pid, "action_item", a["id"], "restore")
    dup = life(client, admin, pid, "action_item", a["id"], "duplicate").json()
    assert cp.status_code == 200 and dup["title"].endswith("(copy)")
    d = get(client, admin, f"/projects/{pid}/records/action-items/{dup['id']}")
    assert d["status"] == "open" and d["reopen_count"] == 0 and d["escalation_level"] == 0


def test_customers_cannot_read_internal_comments_or_attachments(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    t = new_item(client, admin, pid, title="Task")
    client.post(f"{API}/projects/{pid}/comments", json={"entity_type": "work_item", "entity_id": t["id"], "body": "Internal: customer is slow to sign"}, headers=admin)
    up = client.post(f"{API}/projects/{pid}/attachments", data={"entity_type": "work_item", "entity_id": t["id"]}, files={"file": ("notes.txt", io.BytesIO(b"internal"), "text/plain")}, headers=admin).json()
    cust = member(client, admin, make_user, "customer_user", pid)
    dev = member(client, admin, make_user, "developer", pid)
    q = f"entity_type=work_item&entity_id={t['id']}"
    assert client.get(f"{API}/projects/{pid}/comments?{q}", headers=cust).status_code == 403
    assert client.get(f"{API}/projects/{pid}/attachments?{q}", headers=cust).status_code == 403
    assert client.get(f"{API}/projects/{pid}/attachments/{up['id']}/download", headers=cust).status_code == 403
    assert len(client.get(f"{API}/projects/{pid}/comments?{q}", headers=dev).json()) == 1  # internal roles still read them
    assert client.get(f"{API}/projects/{pid}/attachments/{up['id']}/download", headers=dev).status_code == 200
