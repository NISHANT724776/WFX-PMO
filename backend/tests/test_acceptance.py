"""The 18-step acceptance scenario, run end to end against the real Tegra files, as a project manager would do it in the browser.
Each step calls the same endpoints the screens call and checks what the person would see, the database, and the audit log."""
import copy
import io
import uuid

from pptx import Presentation
from pypdf import PdfReader
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import AuditLog
from app.models.canonical import DateRevision, WorkItem
from conftest import PASSWORD, _login
from test_phase2 import get
from test_phase4 import AS_OF, dash, full_setup

API = "/api/v1"
NEW_FINISH = "2026-12-18"


def pdf_text(b: bytes) -> str:
    return " ".join(" ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(b)).pages).split())


def ppt_text(b: bytes) -> str:
    out = []
    for s in Presentation(io.BytesIO(b)).slides:
        for sh in s.shapes:
            if sh.has_text_frame:
                out.append(sh.text_frame.text)
    return " ".join(" ".join(out).split())


def test_acceptance_scenario(client, admin, make_user):
    pid, prods = full_setup(client, admin)  # the Tegra plan and tracker, imported from the supplied workbooks
    uid, _ = make_user("project_manager")
    assert client.put(f"{API}/users/{uid}/project-access", json={"project_ids": [pid]}, headers=admin).status_code == 200

    # 1. The user logs in.
    r = client.post(f"{API}/auth/login", json={"email": "project_manager@example.com", "password": PASSWORD})
    assert r.status_code == 200
    pm = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.post(f"{API}/auth/login", json={"email": "project_manager@example.com", "password": "wrong"}).status_code == 401

    # 2. The user opens the Tegra project.
    project = get(client, pm, f"/projects/{pid}")
    assert project["code"] == "TEGRA-ERP"

    # 3. The user sees the PPT-inspired project dashboard (overall status; and the default template is what the builder opens with).
    ov0 = dash(client, pm, pid, "overall")
    assert ov0["available"] and len(ov0["rows"]) == 22 and ov0["kpis"]["overall"]["total"] > 300
    assert ov0["formulas"]["completion"].startswith("(Done + ½ In Progress)")
    lay = get(client, pm, f"/dashboard-layouts?project_id={pid}")
    assert lay["active_id"] == "template:status"
    assert [w["type"] for w in get(client, pm, "/dashboard-layouts/template:status")["config"]["widgets"]][:2] == ["kpi_strip", "phase_timeline"]

    # 4. The user clicks the overdue KPI.  5. The application opens the overdue activity list.
    act0 = ov0["kpis"]["activities"]
    lst0 = get(client, pm, f"/projects/{pid}/dashboards/drilldown/overdue?as_of={AS_OF}&size=100")
    assert lst0["total"] == act0["overdue"] > 0
    for row in lst0["items"]:
        assert row["original_finish"] and row["days_late"] > 0 and row["status"]
        assert {"revised_finish", "current_finish", "owner"} <= set(row)
    assert lst0["label"] == "Overdue activities" and "current finish date" in lst0["rule"]  # the list says how it was counted

    # 6. The user opens an activity.
    task_row = next(r for r in lst0["items"] if r["editable"])
    task = get(client, pm, f"/projects/{pid}/work-items/{task_row['id']}?as_of={AS_OF}")
    assert task["title"] == task_row["title"] and task["is_overdue"]
    old_owner, old_finish = task["owner_name"], task["effective_finish"]

    # 7. The user edits its owner and target date.  8. The user saves the changes.
    saved_owner = client.patch(f"{API}/projects/{pid}/work-items/{task['id']}", json={"owner_name": "Meera Iyer"}, headers=pm)
    assert saved_owner.status_code == 200
    saved_date = client.post(f"{API}/projects/{pid}/work-items/{task['id']}/reschedule", json={"finish": NEW_FINISH, "reason": "Customer agreed a new date", "approve": True}, headers=pm)
    assert saved_date.status_code == 200, saved_date.text

    # 9. The database records the update.
    with SessionLocal() as db:
        w = db.get(WorkItem, uuid.UUID(task["id"]))
        assert w.owner_name == "Meera Iyer" and w.revised_finish.isoformat() == NEW_FINISH
        assert w.planned_finish.isoformat() == task["planned_finish"]  # the original planned date is preserved
        revs = list(db.scalars(select(DateRevision).where(DateRevision.entity_id == w.id)))
        assert [(r.status, r.new_date.isoformat(), r.reason) for r in revs if r.field == "planned_finish"] == [("approved", NEW_FINISH, "Customer agreed a new date")]
        assert revs[-1].requested_by_email == "project_manager@example.com"

    # 10. The audit history records the modification (who, what, before and after).
    logs = get(client, admin, f"/audit-logs?entity_type=work_item&entity_id={task['id']}&size=50")["items"]
    upd = next(l for l in logs if l["action"] == "update" and l["after"]["owner_name"] == "Meera Iyer")
    assert upd["user_email"] == "project_manager@example.com" and upd["before"]["owner_name"] == old_owner
    rev_logs = get(client, admin, "/audit-logs?entity_type=date_revision&size=100")["items"]
    assert {"create", "approve_revision"} <= {l["action"] for l in rev_logs if l["user_email"] == "project_manager@example.com"}

    # 11. The dashboard reflects the updated information automatically.
    ov1 = dash(client, pm, pid, "overall")
    assert ov1["kpis"]["activities"]["overdue"] == act0["overdue"] - 1  # it is no longer overdue
    assert task["id"] not in {r["id"] for r in get(client, pm, f"/projects/{pid}/dashboards/drilldown/overdue?as_of={AS_OF}&size=100")["items"]}
    seen = next(r for r in get(client, pm, f"/projects/{pid}/dashboards/drilldown/all?as_of={AS_OF}&q={task['title'][:20]}&size=100")["items"] if r["id"] == task["id"])
    assert seen["owner"] == "Meera Iyer" and seen["revised_finish"] == NEW_FINISH and seen["original_finish"] == task["planned_finish"]
    assert old_finish != NEW_FINISH

    # 12. The user adds a new milestone.
    phase = task["phase_id"]
    plm = prods["PLM"]
    pv0 = dash(client, pm, pid, f"product/{plm}")
    ms = client.post(f"{API}/projects/{pid}/work-items", json={"title": "Acceptance go-live rehearsal", "kind": "milestone", "phase_id": phase, "product_id": plm, "owner_name": "Meera Iyer",
                                                               "planned_start": "2026-12-22", "planned_finish": "2026-12-22", "status": "not_started"}, headers=pm)
    assert ms.status_code == 201, ms.text
    mid = ms.json()["id"]

    # 13. The milestone appears in the Gantt timeline (the Gantt reads work items and dependencies).
    items = get(client, pm, f"/projects/{pid}/work-items?size=500&as_of={AS_OF}")["items"]
    gantt = next(i for i in items if i["id"] == mid)
    assert gantt["kind"] == "milestone" and gantt["effective_start"] == gantt["effective_finish"] == "2026-12-22" and gantt["phase_name"]
    assert any(m["id"] == mid for m in get(client, pm, f"/projects/{pid}/dashboards/drilldown/upcoming_milestones?as_of={AS_OF}&size=100")["items"])

    # 14. The user updates its status.
    assert client.patch(f"{API}/projects/{pid}/work-items/{mid}", json={"status": "in_progress", "actual_start": "2026-12-01"}, headers=pm).status_code == 200
    done = client.patch(f"{API}/projects/{pid}/work-items/{mid}", json={"status": "done", "actual_finish": "2026-12-16"}, headers=pm)
    assert done.status_code == 200 and done.json()["status_category"] == "done"

    # 15. Product completion and the relevant dashboard metrics recalculate.
    ov2 = dash(client, pm, pid, "overall")
    a2 = ov2["kpis"]["activities"]
    assert a2["all"] == act0["all"] + 1 and a2["completed"] == act0["completed"] + 1
    o = ov2["kpis"]["overall"]
    assert o["pct"] == round((o["done"] + 0.5 * o["in_progress"]) / o["total"] * 100, 1) and o["total"] == ov0["kpis"]["overall"]["total"] + 1
    pv1 = dash(client, pm, pid, f"product/{plm}")
    assert pv1["kpis"]["items"]["done"] == pv0["kpis"]["items"]["done"] + 1 and pv1["kpis"]["items"]["total"] == pv0["kpis"]["items"]["total"] + 1
    assert pv1["kpis"]["overall"]["pct"] != pv0["kpis"]["overall"]["pct"]
    widget = client.post(f"{API}/projects/{pid}/widgets/product_completion/data", json={"config": {}, "filters": {}, "as_of": AS_OF}, headers=pm).json()
    assert {s["label"]: s["value"] for s in widget["series"]}["PLM"] == pv1["kpis"]["overall"]["pct_display"]  # the dashboard builder agrees

    # 16. The user exports the updated project status as PDF and PowerPoint.
    pdf = client.get(f"{API}/projects/{pid}/exports/overall?format=pdf&as_of={AS_OF}", headers=pm)
    pptx = client.get(f"{API}/projects/{pid}/exports/overall?format=pptx&as_of={AS_OF}", headers=pm)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF" and pptx.status_code == 200 and pptx.content[:2] == b"PK"
    text, deck = pdf_text(pdf.content), ppt_text(pptx.content)
    assert f"{o['pct_display']}%" in text and f"{o['pct_display']}%" in deck  # the exported headline number is the updated one
    assert str(a2["overdue"]) in text and "Project Kick Off" in text and "Project Kick Off" in deck
    tl = pdf_text(client.get(f"{API}/projects/{pid}/exports/timeline?format=pdf&as_of={AS_OF}", headers=pm).content)
    assert "Acceptance go-live rehearsal" in tl and "Meera Iyer" in tl  # the new milestone and the new owner are in the exported timeline
    xl = client.get(f"{API}/projects/{pid}/exports/overdue?format=xlsx&as_of={AS_OF}", headers=pm)
    assert xl.status_code == 200
    assert "report" in {a["entity_type"] for a in get(client, admin, "/audit-logs?action=export&size=20")["items"]}

    # 17. The user customises their dashboard layout and saves it.
    mine = client.post(f"{API}/dashboard-layouts", json={"name": "My status view", "scope": "personal", "from_id": "template:status"}, headers=pm)
    assert mine.status_code == 201, mine.text
    cfg = copy.deepcopy(mine.json()["config"])
    cfg["widgets"] = [w for w in cfg["widgets"] if w["type"] != "coverage"]
    cfg["widgets"].append({"id": "w20", "type": "breakdown", "x": 8, "y": 13, "w": 4, "h": 5, "config": {"source": "pending", "chart_type": "table", "title": "Who holds the pending items"}})
    saved = client.put(f"{API}/dashboard-layouts/{mine.json()['id']}", json={"version": 1, "config": cfg}, headers=pm)
    assert saved.status_code == 200, saved.text
    assert client.put(f"{API}/projects/{pid}/dashboard-pref", json={"layout_id": mine.json()["id"]}, headers=pm).status_code == 200

    # 18. On the next visit (a fresh sign-in) the saved layout is restored.
    again = _login(client, "project_manager@example.com")
    lay2 = get(client, again, f"/dashboard-layouts?project_id={pid}")
    assert lay2["active_id"] == mine.json()["id"]
    restored = get(client, again, f"/dashboard-layouts/{lay2['active_id']}")
    assert restored["config"] == saved.json()["config"] and restored["name"] == "My status view"
    assert any(w["config"].get("title") == "Who holds the pending items" for w in restored["config"]["widgets"])
    assert not any(w["type"] == "coverage" for w in restored["config"]["widgets"])
    # and the restored widgets draw live numbers, not copies
    live = client.post(f"{API}/projects/{pid}/widgets/breakdown/data", json={"config": {"source": "activities"}, "filters": {}, "as_of": AS_OF}, headers=again).json()
    assert live["shape"] == "series" and sum(x["value"] for x in live["series"]) == a2["all"]  # includes the milestone added in step 12
    assert client.get(f"{API}/projects/{pid}/dashboards/overall?as_of={AS_OF}", headers=again).json()["kpis"]["activities"]["completed"] == a2["completed"]
    with SessionLocal() as db:  # nothing in the audit trail was lost along the way
        assert db.scalar(select(AuditLog.id).where(AuditLog.entity_type == "dashboard_layout", AuditLog.user_email == "project_manager@example.com").limit(1))
