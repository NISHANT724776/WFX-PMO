"""Phase 2: Excel Intelligence end to end on the REAL Tegra workbooks (tests/data)."""
import io
import uuid
import warnings
import zipfile
from collections import Counter
from pathlib import Path

import openpyxl
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import ApprovalGate, GapSpecification, ProjectPhase, TrackerEvent, WorkItem

warnings.filterwarnings("ignore")
API = "/api/v1"
DATA = Path(__file__).parent / "data"
V3, V1, PLAN = DATA / "tegra_tracker_v3.xlsx", DATA / "tegra_tracker_v1.xlsx", DATA / "tegra_plan_v4.xlsx"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def upload(client, hdr, path_or_bytes, name=None):
    data = path_or_bytes.read_bytes() if isinstance(path_or_bytes, Path) else path_or_bytes
    name = name or (path_or_bytes.name if isinstance(path_or_bytes, Path) else "x.xlsx")
    return client.post(f"{API}/imports", files={"file": (name, data, XLSX)}, headers=hdr)


def get(client, hdr, url):
    r = client.get(f"{API}{url}", headers=hdr)
    assert r.status_code == 200, r.text
    return r.json()


def setup_project(client, admin):
    cust = client.post(f"{API}/customers", json={"code": "TEGRA", "name": "Tegra"}, headers=admin).json()
    prods = {}
    for code in ("PLM", "ERP", "PLAN", "WMS", "MES", "FINANCE"):
        prods[code] = client.post(f"{API}/products", json={"code": code, "name": code}, headers=admin).json()["id"]
    proj = client.post(f"{API}/projects", json={"customer_id": cust["id"], "code": "TEGRA-ERP", "name": "Tegra ERP"}, headers=admin).json()
    return proj["id"], prods


def confirm_medium(client, hdr, batch_id):
    """The user reviewing medium-confidence suggestions (policy: they never apply without a click)."""
    b = get(client, hdr, f"/imports/{batch_id}")
    for sh in b["sheets"]:
        if not sh["unconfirmed"]:
            continue
        d = get(client, hdr, f"/imports/{batch_id}/sheets/{sh['id']}")
        items = [{"column_id": c["id"], "target_field": c["mapping"]["target_field"]} for c in d["columns"]
                 if c["mapping"] and c["mapping"]["status"] == "suggested" and c["mapping"]["level"] == "medium"]
        r = client.put(f"{API}/imports/{batch_id}/sheets/{sh['id']}/mappings", json={"mappings": items}, headers=hdr)
        assert r.status_code == 200, r.text


def sheet_by_name(batch, name):
    return next(s for s in batch["sheets"] if s["name"] == name)


def link_finance(client, hdr, batch_id, prods):
    b = get(client, hdr, f"/imports/{batch_id}")
    ms = sheet_by_name(b, "Master Sheet")
    r = client.patch(f"{API}/imports/{batch_id}/sheets/{ms['id']}", json={"product_map": {"Finance + Actual Costing": prods["FINANCE"]}}, headers=hdr)
    assert r.status_code == 200, r.text


# ======================================================================= analysis
def test_analysis_of_real_tracker_v3(client, admin):
    r = upload(client, admin, V3)
    assert r.status_code == 201, r.text
    b = get(client, admin, f"/imports/{r.json()['id']}")
    assert b["status"] == "ready"
    names = {s["name"]: s for s in b["sheets"]}
    assert list(names) == ["Master Sheet", "Blue Printing Signoff", "Gap Tracker", "E2E", "UAT Accecptence Criteria", "Reports + Prints", "Integration", "Lists"]
    assert names["Master Sheet"]["classification"] == "milestone_matrix" and names["Master Sheet"]["entity"] == "tracker_event"
    assert names["Gap Tracker"]["classification"] == "gap_tracker"
    assert names["Blue Printing Signoff"]["entity"] == "approval_gate" and names["E2E"]["entity"] == "approval_gate"
    # the UAT, integration and reports sheets are importable trackers
    for n, entity in (("UAT Accecptence Criteria", "uat_scenario"), ("Integration", "integration_item"), ("Reports + Prints", "report_item")):
        assert names[n]["entity"] == entity and names[n]["enabled"] is True and names[n]["not_yet"] is None
    # header row detected despite title / link rows above it
    d = get(client, admin, f"/imports/{b['id']}/sheets/{names['Blue Printing Signoff']['id']}")
    assert d["config"]["header_row"] == 4 and d["profile"]["header_candidates"][0]["row"] == 4
    assert [c["header"] for c in d["columns"]][:3] == ["Department/Team", "Mapping Date", "Submission Date"]


def test_matrix_sheet_detects_products_and_hidden_column(client, admin):
    _, prods = setup_project(client, admin)
    b = get(client, admin, f"/imports/{upload(client, admin, V3).json()['id']}")
    ms = sheet_by_name(b, "Master Sheet")
    d = get(client, admin, f"/imports/{b['id']}/sheets/{ms['id']}")
    assert d["layout"] == "matrix"
    assert set(d["config"]["product_map"]) == {"PLM", "ERP", "Plan", "WMS", "MES", "Finance + Actual Costing"}
    # exact-name matches are suggested; the unmatched one is left for the user (never invented)
    assert d["config"]["product_map"]["PLM"] == prods["PLM"] and d["config"]["product_map"]["Plan"] == prods["PLAN"]
    assert d["config"]["product_map"]["Finance + Actual Costing"] is None
    assert "C" in d["profile"]["stats"]["hidden_columns"]
    levels = {c["header"]: c["mapping"]["level"] for c in d["columns"] if c["mapping"] and not c["group_label"]}
    assert levels == {"Events": "high", "Responsibility": "high", "SPOC": "high"}


def test_gap_tracker_mapping_confidence_and_medium_requires_click(client, admin):
    b = get(client, admin, f"/imports/{upload(client, admin, V3).json()['id']}")
    gap = sheet_by_name(b, "Gap Tracker")
    d = get(client, admin, f"/imports/{b['id']}/sheets/{gap['id']}")
    m = {c["header"]: c["mapping"] for c in d["columns"]}
    assert m["Issue ID"]["target_field"] == "external_issue_id" and m["Issue ID"]["level"] == "high"
    assert m["Brief Description"]["target_field"] == "description"
    assert m["Specs Target Date"]["target_field"] == "target_date"
    assert m["S.No."]["level"] == "medium" and m["S.No."]["status"] == "suggested"
    v = client.post(f"{API}/imports/{b['id']}/validate", headers=admin).json()
    g = next(s for s in v["sheets"] if s["name"] == "Gap Tracker")
    assert any(x["code"] == "unconfirmed_mapping" for x in g["blocking"]) and not v["can_commit"]
    confirm_medium(client, admin, b["id"])
    v = client.post(f"{API}/imports/{b['id']}/validate", headers=admin).json()
    assert not next(s for s in v["sheets"] if s["name"] == "Gap Tracker")["blocking"]


def test_tracker_v1_uses_different_columns_and_is_detected(client, admin):
    b = get(client, admin, f"/imports/{upload(client, admin, V1).json()['id']}")
    ms = sheet_by_name(b, "Sheet1")
    assert ms["entity"] == "tracker_event"
    d = get(client, admin, f"/imports/{b['id']}/sheets/{ms['id']}")
    assert d["config"]["header_row"] == 2 and set(d["config"]["product_map"]) == {"PLM", "ERP", "Plan", "MES", "Finance"}  # no WMS in v1
    gap = get(client, admin, f"/imports/{b['id']}/sheets/{sheet_by_name(b, 'Gap Tracker')['id']}")
    m = {c["header"]: c["mapping"]["target_field"] for c in gap["columns"]}
    assert m["Received On Date"] == "received_date" and m["Proto Created"] == "proto_status" and m["Product"] == "product_name"
    assert sheet_by_name(b, "Sheet2")["enabled"] is False  # empty sheet


# ======================================================================= validation / blocking
def test_unlinked_product_blocks_until_user_decides(client, admin):
    _, prods = setup_project(client, admin)
    b = get(client, admin, f"/imports/{upload(client, admin, V3).json()['id']}")
    confirm_medium(client, admin, b["id"])
    v = client.post(f"{API}/imports/{b['id']}/validate", headers=admin).json()
    ms = next(s for s in v["sheets"] if s["name"] == "Master Sheet")
    assert [x["code"] for x in ms["blocking"]] == ["product_unresolved"] and not v["can_commit"]
    link_finance(client, admin, b["id"], prods)
    v = client.post(f"{API}/imports/{b['id']}/validate", headers=admin).json()
    assert not next(s for s in v["sheets"] if s["name"] == "Master Sheet")["blocking"]


def test_excluding_a_product_group_is_an_explicit_choice(client, admin):
    setup_project(client, admin)
    b = get(client, admin, f"/imports/{upload(client, admin, V3).json()['id']}")
    ms = sheet_by_name(b, "Master Sheet")
    client.patch(f"{API}/imports/{b['id']}/sheets/{ms['id']}", json={"product_map": {"Finance + Actual Costing": "__exclude__"}}, headers=admin)
    confirm_medium(client, admin, b["id"])
    v = client.post(f"{API}/imports/{b['id']}/validate", headers=admin).json()
    assert not next(s for s in v["sheets"] if s["name"] == "Master Sheet")["blocking"]


def test_errors_are_reported_never_dropped_and_csv_is_safe(client, admin):
    setup_project(client, admin)
    b = get(client, admin, f"/imports/{upload(client, admin, V3).json()['id']}")
    confirm_medium(client, admin, b["id"])
    client.post(f"{API}/imports/{b['id']}/validate", headers=admin)
    gap = sheet_by_name(b, "Gap Tracker")
    errs = get(client, admin, f"/imports/{b['id']}/errors?sheet_id={gap['id']}&code=unknown_date&size=200")
    assert errs["total"] > 0
    e = errs["items"][0]
    assert e["raw_value"].lower() in ("tba", "tbd") and e["severity"] == "warning" and e["row"] >= 3
    csv_text = client.get(f"{API}/imports/{b['id']}/errors.csv", headers=admin).text
    assert csv_text.splitlines()[0].startswith("Sheet,Row,Column") and "unknown_date" in csv_text
    from app.api.imports import _csv_safe
    assert _csv_safe("=cmd|' /C calc'!A0") == "'=cmd|' /C calc'!A0" and _csv_safe("ok") == "ok"


# ======================================================================= commit on real data
def _expected_counts():
    """Independent oracle: counts straight from the workbooks with openpyxl, not from our parser."""
    wb = openpyxl.load_workbook(V3, data_only=True)
    ms = wb["Master Sheet"]
    pairs = [(4, 5), (6, 7), (8, 9), (10, 11), (12, 13), (14, 15)]
    events = 0
    for r in range(3, ms.max_row + 1):
        if ms.cell(r, 1).value is None:
            continue
        for p, a in pairs:
            if ms.cell(r, p).value not in (None, "") or ms.cell(r, a).value not in (None, ""):
                events += 1
    gap = wb["Gap Tracker"]
    gap_rows = sum(1 for r in range(3, gap.max_row + 1) if gap.cell(r, 7).value not in (None, ""))
    plan = openpyxl.load_workbook(PLAN, data_only=True).active
    tasks = [row for row in plan.iter_rows(min_row=3, values_only=True) if row[1]]
    return events, gap_rows, len(tasks), Counter(str(t[10]) for t in tasks), len({t[0] for t in tasks})


def import_tracker(client, admin, prods, project_id, path=V3, mode="create_only", template=None):
    b = get(client, admin, f"/imports/{upload(client, admin, path).json()['id']}")
    confirm_medium(client, admin, b["id"])
    link_finance(client, admin, b["id"], prods)
    r = client.post(f"{API}/imports/{b['id']}/commit",
                    json={"project_id": project_id, "mode": mode, "confirm_rejected": True, "template_name": template}, headers=admin)
    return b, r


def test_commit_real_tracker_matches_independent_counts(client, admin):
    pid, prods = setup_project(client, admin)
    exp_events, exp_gap, *_ = _expected_counts()
    b, r = import_tracker(client, admin, prods, pid)
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(TrackerEvent)) == exp_events
        assert db.scalar(select(func.count()).select_from(GapSpecification)) == exp_gap
        assert db.scalar(select(func.count()).select_from(ApprovalGate)) == 13 + 4
        assert {g.gate_type for g in db.scalars(select(ApprovalGate))} == {"blue_printing_signoff", "e2e"}
        # repeated external Issue ID = several specification rows, not one overwritten record
        dup = db.execute(select(GapSpecification.external_issue_id, func.count()).group_by(GapSpecification.external_issue_id).having(func.count() > 1)).all()
        assert dup and all(c >= 2 for _, c in dup)
        # unparseable date ("TBA") stored empty, original text preserved
        tba = db.scalar(select(GapSpecification).where(GapSpecification.target_date.is_(None), GapSpecification.raw_values.is_not(None)).limit(1))
        assert tba is not None and tba.raw_values["target_date"].lower() in ("tba", "tbd")
        # wide matrix unpivoted per product, with real planned/actual dates
        ev = db.scalar(select(TrackerEvent).where(TrackerEvent.event_name == "Business Blueprint Creation", TrackerEvent.product_id == uuid.UUID(prods["PLM"])))
        assert str(ev.planned_date) == "2026-04-10" and str(ev.actual_date) == "2026-04-13"
        fin = db.scalar(select(TrackerEvent).where(TrackerEvent.event_name == "Business Blueprint Creation", TrackerEvent.product_id == uuid.UUID(prods["FINANCE"])))
        assert str(fin.planned_date) == "2027-01-18" and fin.actual_date is None
    summary = get(client, admin, f"/imports/{b['id']}")
    assert summary["status"] == "committed" and summary["project_id"] == pid
    assert {s["sheet"] for s in summary["commit_summary"]["sheets"]} == {"Master Sheet", "Blue Printing Signoff", "Gap Tracker", "E2E", "UAT Accecptence Criteria", "Reports + Prints", "Integration"}
    # the three tracker sheets: counts recomputed from the raw workbook (rows below the header row, with something to name them by)
    wb = openpyxl.load_workbook(V3, data_only=True)

    def raw_rows(sheet, header, name_headers):
        ws = wb[sheet]
        hr = next(r for r in range(1, 12) if header in [str(c.value).strip() for c in ws[r] if c.value])
        cols = {str(c.value).strip(): i for i, c in enumerate(ws[hr]) if c.value}
        return [row for row in ws.iter_rows(min_row=hr + 1, values_only=True) if any(row[cols[h]] not in (None, "") for h in name_headers if h in cols)], cols

    uat_rows, _ = raw_rows("UAT Accecptence Criteria", "Scenario Title", ["Scenario Title"])
    integ_rows, _ = raw_rows("Integration", "Message / Format", ["Message / Format", "Partner / System"])
    rep_rows, rcols = raw_rows("Reports + Prints", "Folder", ["Sub-Folders", "Folder"])
    with SessionLocal() as db:
        from app.models.workspace import IntegrationItem, ReportItem, UatScenario  # noqa: PLC0415

        assert db.scalar(select(func.count()).select_from(UatScenario)) == len(uat_rows) == 129
        assert db.scalar(select(func.count()).select_from(IntegrationItem)) == len(integ_rows) == 68
        assert db.scalar(select(func.count()).select_from(ReportItem)) == len(rep_rows) == 22
        count_col = next(i for h, i in rcols.items() if h.startswith("Reports Count"))
        assert db.scalar(select(func.sum(ReportItem.reports_count))) == sum(int(r[count_col] or 0) for r in rep_rows) == 1794
        assert {u.result for u in db.scalars(select(UatScenario))} == {"not_run"}  # the sheet has no results yet, and none are invented
        # statuses it cannot classify stay unclassified (and so are never counted as done)
        assert db.scalar(select(func.count()).select_from(IntegrationItem).where(IntegrationItem.status_raw == "Currently In Use", IntegrationItem.status_category.is_(None))) == 52


def test_commit_real_plan(client, admin):
    pid, _ = setup_project(client, admin)
    _, _, exp_tasks, exp_status, exp_phases = _expected_counts()
    b = get(client, admin, f"/imports/{upload(client, admin, PLAN).json()['id']}")
    sh = b["sheets"][0]
    assert sh["classification"] == "project_plan" and sh["unconfirmed"] == 0
    v = client.post(f"{API}/imports/{b['id']}/validate", headers=admin).json()
    s = v["sheets"][0]
    assert s["section_rows"] == 18 and s["source_rows"] == exp_tasks and s["rejected_rows"] == 0 and v["can_commit"]
    r = client.post(f"{API}/imports/{b['id']}/commit", json={"project_id": pid}, headers=admin)
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(WorkItem)) == exp_tasks
        assert db.scalar(select(func.count()).select_from(ProjectPhase)) == exp_phases == 16
        cats = Counter(w.status_category for w in db.scalars(select(WorkItem)))
        assert cats == {"done": exp_status["Done"], "not_started": exp_status["Not Started"], "in_progress": exp_status["In-Progress"]}
        modes = Counter(w.delivery_mode for w in db.scalars(select(WorkItem)))
        assert modes == {"onsite": 159, "online": 26}  # 'onsite' (lower-case) merged with 'Onsite'; Remote -> online
        parties = {w.responsible_party for w in db.scalars(select(WorkItem))}
        assert parties == {"JOINT", "WFX", "Tegra"}  # 'TEGRA' harmonised, and reported
        w = db.scalar(select(WorkItem).where(WorkItem.title.like("Stakeholder Identification%")))
        assert str(w.planned_start) == "2026-02-02" and w.location_label == "Arena (Honduras)" and w.status_category == "done"
        # placeholder "-" in actual dates is "no value", not an invalid date
        assert db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.status_category == "not_started", WorkItem.actual_finish.is_not(None))) == 0
    codes = {e["code"] for e in get(client, admin, f"/imports/{b['id']}/errors?size=200")["items"]}
    assert {"case_harmonised", "similar_values", "location_unlinked", "section_phase_mismatch"} <= codes
    assert "invalid_date" not in codes
    # readable through the project API
    items = get(client, admin, f"/projects/{pid}/work-items?size=5")
    assert items["total"] == exp_tasks and len(items["items"]) == 5


# ======================================================================= guards: duplicates, rollback, update
def test_same_file_cannot_be_imported_twice_into_a_project(client, admin):
    pid, _ = setup_project(client, admin)
    b = get(client, admin, f"/imports/{upload(client, admin, PLAN).json()['id']}")
    assert client.post(f"{API}/imports/{b['id']}/commit", json={"project_id": pid}, headers=admin).status_code == 200
    up2 = upload(client, admin, PLAN)
    assert up2.json()["duplicate_of"] == b["id"]  # warned at upload
    b2 = up2.json()["id"]
    r = client.post(f"{API}/imports/{b2}/commit", json={"project_id": pid}, headers=admin)
    assert r.status_code == 409 and "already imported" in r.json()["detail"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(WorkItem)) == 185  # nothing doubled


def test_rollback_removes_import_and_allows_reimport(client, admin):
    pid, _ = setup_project(client, admin)
    b = get(client, admin, f"/imports/{upload(client, admin, PLAN).json()['id']}")
    client.post(f"{API}/imports/{b['id']}/commit", json={"project_id": pid}, headers=admin)
    r = client.post(f"{API}/imports/{b['id']}/rollback", headers=admin)
    assert r.status_code == 200 and r.json()["deleted"] == 185
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(WorkItem)) == 0
        assert db.scalar(select(func.count()).select_from(ProjectPhase)) == 0
    assert get(client, admin, f"/imports/{b['id']}")["status"] == "rolled_back"
    b2 = get(client, admin, f"/imports/{upload(client, admin, PLAN).json()['id']}")
    assert client.post(f"{API}/imports/{b2['id']}/commit", json={"project_id": pid}, headers=admin).status_code == 200


def test_rollback_refused_if_records_were_edited_after_import(client, admin):
    pid, _ = setup_project(client, admin)
    b = get(client, admin, f"/imports/{upload(client, admin, PLAN).json()['id']}")
    client.post(f"{API}/imports/{b['id']}/commit", json={"project_id": pid}, headers=admin)
    with SessionLocal() as db:
        w = db.scalar(select(WorkItem).limit(1))
        w.remarks = "edited by a user after import"
        db.commit()
    r = client.post(f"{API}/imports/{b['id']}/rollback", headers=admin)
    assert r.status_code == 409 and "edited after the import" in r.json()["detail"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(WorkItem)) == 185  # nothing changed


def _modified_copy(src: Path, edit):
    wb = openpyxl.load_workbook(src)
    edit(wb)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _edit_remark(wb):
    ws = wb.active
    for r in range(3, ws.max_row + 1):
        if str(ws.cell(r, 2).value or "").startswith("Stakeholder Identification"):
            ws.cell(r, 15).value = "Remark changed in newer file"
            return


def test_update_mode_changes_only_what_differs_and_rollback_restores(client, admin):
    pid, _ = setup_project(client, admin)
    b = get(client, admin, f"/imports/{upload(client, admin, PLAN).json()['id']}")
    client.post(f"{API}/imports/{b['id']}/commit", json={"project_id": pid}, headers=admin)

    b2 = get(client, admin, f"/imports/{upload(client, admin, _modified_copy(PLAN, _edit_remark), 'plan_v4_1.xlsx').json()['id']}")
    # default mode never overwrites silently
    r = client.post(f"{API}/imports/{b2['id']}/commit", json={"project_id": pid}, headers=admin)
    assert r.status_code == 200 and r.json()["sheets"][0] == {"sheet": "Detailed Project Plan-A", "entity": "plan_task", "created": 0, "updated": 0, "skipped": 185, "rejected": 0}

    def edit2(wb):
        _edit_remark(wb)
        wb.active.cell(1, 1).value = "WFX ERP - MES + Finance Implementation (v4.1)"  # new file hash, same data
    b3 = get(client, admin, f"/imports/{upload(client, admin, _modified_copy(PLAN, edit2), 'plan_v4_1b.xlsx').json()['id']}")
    r = client.post(f"{API}/imports/{b3['id']}/commit", json={"project_id": pid, "mode": "update"}, headers=admin)
    assert r.status_code == 200, r.text
    s = r.json()["sheets"][0]
    assert (s["created"], s["updated"], s["skipped"]) == (0, 1, 184)
    with SessionLocal() as db:
        w = db.scalar(select(WorkItem).where(WorkItem.title.like("Stakeholder Identification%")))
        assert w.remarks == "Remark changed in newer file"
    assert client.post(f"{API}/imports/{b3['id']}/rollback", headers=admin).json() == {"deleted": 0, "restored": 1}
    with SessionLocal() as db:
        w = db.scalar(select(WorkItem).where(WorkItem.title.like("Stakeholder Identification%")))
        assert w.remarks == "Onsite – The Arena, Honduras"  # original value restored


def test_rejected_rows_need_explicit_confirmation(client, admin):
    pid, _ = setup_project(client, admin)
    csv_bytes = b"Phase,Task,Start Date,End Date,Status\nP1,Do A,2026-01-05,2026-01-09,Done\nP1,,2026-01-05,2026-01-09,Done\nP2,Do C,TBA,not a date,Weird\n"
    up = client.post(f"{API}/imports", files={"file": ("plan.csv", csv_bytes, "text/csv")}, headers=admin)
    b = get(client, admin, f"/imports/{up.json()['id']}")
    assert b["sheets"][0]["classification"] == "project_plan" and b["sheets"][0]["entity"] == "plan_task"
    confirm_medium(client, admin, b["id"])
    v = client.post(f"{API}/imports/{b['id']}/validate", headers=admin).json()
    s = v["sheets"][0]
    assert (s["source_rows"], s["importable"], s["rejected_rows"]) == (3, 2, 1)
    r = client.post(f"{API}/imports/{b['id']}/commit", json={"project_id": pid}, headers=admin)
    assert r.status_code == 409 and "rejected" in r.json()["detail"]
    r = client.post(f"{API}/imports/{b['id']}/commit", json={"project_id": pid, "confirm_rejected": True}, headers=admin)
    assert r.status_code == 200 and r.json()["sheets"][0]["created"] == 2 and r.json()["sheets"][0]["rejected"] == 1
    errs = get(client, admin, f"/imports/{b['id']}/errors?size=50")["items"]
    codes = {(e["code"], e["row"]) for e in errs}
    assert ("missing_required", 3) in codes and ("unknown_date", 4) in codes and ("invalid_date", 4) in codes and ("unknown_status", None) in codes
    with SessionLocal() as db:
        c = db.scalar(select(WorkItem).where(WorkItem.title == "Do C"))
        assert c.planned_start is None and c.raw_values["planned_start"] == "TBA" and c.status_raw == "Weird" and c.status_category is None


# ======================================================================= templates and history
def test_saved_template_is_recognised_on_next_upload(client, admin):
    pid, prods = setup_project(client, admin)
    _, r = import_tracker(client, admin, prods, pid, template="Tegra Tracker Template")
    assert r.status_code == 200, r.text
    assert [t["name"] for t in get(client, admin, "/import-templates")] == ["Tegra Tracker Template"]

    data = _modified_copy(V3, lambda wb: setattr(wb["Gap Tracker"].cell(3, 12), "value", "touched"))  # new hash, same layout
    b = get(client, admin, f"/imports/{upload(client, admin, data, 'tegra_tracker_v3_next.xlsx').json()['id']}")
    assert b["template"] == "Tegra Tracker Template"
    ms = sheet_by_name(b, "Master Sheet")
    assert ms["template"] == "Tegra Tracker Template" and ms["unconfirmed"] == 0
    d = get(client, admin, f"/imports/{b['id']}/sheets/{ms['id']}")
    # previous decisions come back with the template: Finance is already linked, no re-mapping needed
    assert d["config"]["product_map"]["Finance + Actual Costing"] == prods["FINANCE"]
    gap = get(client, admin, f"/imports/{b['id']}/sheets/{sheet_by_name(b, 'Gap Tracker')['id']}")
    sno = next(c for c in gap["columns"] if c["header"] == "S.No.")["mapping"]
    assert sno["source"] == "template" and sno["level"] == "high"
    v = client.post(f"{API}/imports/{b['id']}/validate", headers=admin).json()
    assert v["can_commit"]


# ======================================================================= security / permissions
def test_unsafe_uploads_rejected(client, admin):
    assert upload(client, admin, b"MZ\x90\x00", "malware.exe").status_code == 422
    assert upload(client, admin, b"x", "macro.xlsm").status_code == 422
    assert upload(client, admin, b"not a zip at all", "fake.xlsx").status_code == 422
    assert client.post(f"{API}/imports", files={"file": ("empty.xlsx", b"", XLSX)}, headers=admin).status_code == 422
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<x/>")
        z.writestr("xl/vbaProject.bin", b"\x00")
    assert upload(client, admin, buf.getvalue(), "hidden_macro.xlsx").status_code == 422
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/big.xml", b"0" * (60 * 1024 * 1024))
    r = upload(client, admin, bomb.getvalue(), "bomb.xlsx")
    assert r.status_code == 422 and "unsafe" in r.json()["detail"].lower()
    with SessionLocal() as db:
        from app.models import ImportBatch
        assert db.scalar(select(func.count()).select_from(ImportBatch)) == 0  # nothing stored for rejected files


def test_corrupt_workbook_fails_cleanly(client, admin):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<x/>")
    r = upload(client, admin, buf.getvalue(), "corrupt.xlsx")
    assert r.status_code == 201
    b = get(client, admin, f"/imports/{r.json()['id']}")
    assert b["status"] == "failed" and "Could not analyse" in b["error"] and "Traceback" not in b["error"]


def test_import_permissions_and_visibility(client, admin, make_user):
    pid, prods = setup_project(client, admin)
    _, qa = make_user("qa")
    assert upload(client, qa, PLAN).status_code == 403
    fid, fc = make_user("functional_consultant")
    up = upload(client, fc, PLAN)
    assert up.status_code == 201  # may upload and suggest
    bid = up.json()["id"]
    assert client.post(f"{API}/imports/{bid}/commit", json={"project_id": pid}, headers=fc).status_code == 403  # may not commit
    # another non-global user cannot see it
    pm_id, pm = make_user("project_manager")
    assert client.get(f"{API}/imports/{bid}", headers=pm).status_code == 404
    assert client.get(f"{API}/imports", headers=pm).json()["total"] == 0
    # PM can commit only into projects they were granted
    own_up = client.post(f"{API}/imports", files={"file": ("pm_plan.xlsx", _modified_copy(PLAN, _edit_remark), XLSX)}, headers=pm)
    own = own_up.json()
    assert client.post(f"{API}/imports/{own['id']}/commit", json={"project_id": pid}, headers=pm).status_code == 404
    client.put(f"{API}/users/{pm_id}/project-access", json={"project_ids": [pid]}, headers=admin)
    assert client.post(f"{API}/imports/{own['id']}/commit", json={"project_id": pid}, headers=pm).status_code == 200
    assert client.post(f"{API}/imports/{own['id']}/rollback", headers=pm).status_code == 403  # rollback = PMO/admin
    assert client.post(f"{API}/imports/{own['id']}/rollback", headers=admin).status_code == 200


def test_mapping_edits_validate_and_are_audited(client, admin):
    b = get(client, admin, f"/imports/{upload(client, admin, PLAN).json()['id']}")
    d = get(client, admin, f"/imports/{b['id']}/sheets/{b['sheets'][0]['id']}")
    col = {c["header"]: c for c in d["columns"]}
    # mapping two columns to one field is refused
    r = client.put(f"{API}/imports/{b['id']}/sheets/{d['id']}/mappings",
                   json={"mappings": [{"column_id": col["Status"]["id"], "target_field": "title"}]}, headers=admin)
    assert r.status_code == 422 and "two columns" in r.json()["detail"]
    r = client.put(f"{API}/imports/{b['id']}/sheets/{d['id']}/mappings",
                   json={"mappings": [{"column_id": col["Status"]["id"], "target_field": "nonsense"}]}, headers=admin)
    assert r.status_code == 422
    # ignoring a required column leaves a blocking issue
    client.put(f"{API}/imports/{b['id']}/sheets/{d['id']}/mappings",
               json={"mappings": [{"column_id": col["Phase"]["id"], "ignore": True}]}, headers=admin)
    v = client.post(f"{API}/imports/{b['id']}/validate", headers=admin).json()
    assert any(x["code"] == "required_unmapped" for x in v["sheets"][0]["blocking"]) and not v["can_commit"]
    logs = get(client, admin, "/audit-logs?action=import_mapping_edit")["items"]
    assert logs and logs[0]["user_email"] == "admin@example.com"


def test_dashboard_suggestions_reflect_available_fields_only(client, admin):
    b = get(client, admin, f"/imports/{upload(client, admin, V3).json()['id']}")
    sug = {s["key"]: s for s in get(client, admin, f"/imports/{b['id']}/dashboard-suggestions")}
    assert sug["overall_status"]["available"] is False  # tracker alone has no plan tasks
    assert sug["signoff_gates"]["available"] is True
    assert sug["product_coverage"]["available"] is True and sug["product_coverage"]["sources"] == ["tracker_event"]
    b2 = get(client, admin, f"/imports/{upload(client, admin, PLAN).json()['id']}")
    sug2 = {s["key"]: s for s in get(client, admin, f"/imports/{b2['id']}/dashboard-suggestions")}
    assert sug2["overall_status"]["available"] is True and "no product column" in sug2["product_coverage"]["note"]
