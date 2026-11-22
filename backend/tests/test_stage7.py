"""Stage 7: the eight management reports in Excel, PDF and PowerPoint. Numbers in a file must equal the numbers on the dashboards."""
import io

import openpyxl
from pptx import Presentation
from pypdf import PdfReader
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.canonical import ApprovalGate
from app.modules.dashboards.export_reports import safe
from test_phase2 import get, setup_project
from test_phase3 import new_item
from test_phase4 import AS_OF, dash, full_setup
from test_stage1 import member

API = "/api/v1"
KEYS = ["overall", "product", "timeline", "gates", "coverage", "attention", "next_week", "overdue", "uat", "deliverables"]
MAGIC = {"xlsx": b"PK", "pptx": b"PK", "pdf": b"%PDF"}
TYPE = {"xlsx": "spreadsheetml", "pptx": "presentationml", "pdf": "application/pdf"}


def export(client, hdr, pid, key, fmt, **params):
    q = "".join(f"&{k}={v}" for k, v in params.items())
    return client.get(f"{API}/projects/{pid}/exports/{key}?format={fmt}&as_of={AS_OF}{q}", headers=hdr)


def sheets(content: bytes) -> dict:
    wb = openpyxl.load_workbook(io.BytesIO(content))
    return {ws.title: [[c.value for c in r] for r in ws.iter_rows(values_only=False)] for ws in wb.worksheets}


def pdf_text(content: bytes) -> str:
    return " ".join(" ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(content)).pages).split())  # table cells wrap: compare on single-spaced text


def ppt_text(content: bytes) -> str:
    out = []
    for s in Presentation(io.BytesIO(content)).slides:
        for sh in s.shapes:
            if sh.has_text_frame:
                out.append(sh.text_frame.text)
            if getattr(sh, "has_table", False) and sh.has_table:
                out += [c.text for r in sh.table.rows for c in r.cells]
    return " ".join(" ".join(out).split())


def test_every_report_in_every_format_on_real_tegra_data(client, admin):
    pid, prods = full_setup(client, admin)
    cat = get(client, admin, f"/projects/{pid}/exports")
    assert [c["key"] for c in cat] == KEYS and all(c["formats"] == ["xlsx", "pdf", "pptx"] for c in cat)
    assert next(c for c in cat if c["key"] == "product")["needs_product"] and next(c for c in cat if c["key"] == "next_week")["takes_period"]
    for key in KEYS:
        for fmt in ("xlsx", "pdf", "pptx"):
            extra = {"product_id": prods["PLM"]} if key == "product" else {}
            r = export(client, admin, pid, key, fmt, **extra)
            assert r.status_code == 200, (key, fmt, r.text[:200])
            assert TYPE[fmt] in r.headers["content-type"] and r.content[:len(MAGIC[fmt])] == MAGIC[fmt], (key, fmt)
            assert f"TEGRA-ERP-{key}-{AS_OF}.{fmt}" in r.headers["content-disposition"]
    assert export(client, admin, pid, "product", "pdf").status_code == 422  # a product is needed
    assert export(client, admin, pid, "nonsense", "pdf").status_code == 404
    assert client.get(f"{API}/projects/{pid}/exports/overall?format=docx", headers=admin).status_code == 422
    actions = get(client, admin, "/audit-logs?entity_type=report&size=100")["items"]
    assert len(actions) == 30 and {a["after"]["format"] for a in actions} == {"xlsx", "pdf", "pptx"}


def test_export_permissions(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    dev = member(client, admin, make_user, "developer", pid)  # may read, may not export
    pm = member(client, admin, make_user, "project_manager", pid)
    assert export(client, dev, pid, "overall", "pdf").status_code == 403
    assert export(client, pm, pid, "overall", "pdf").status_code == 200
    _, outsider = make_user("project_manager", "outsider@example.com")
    assert export(client, outsider, pid, "overall", "xlsx").status_code == 404
    assert client.get(f"{API}/projects/{pid}/exports/overall?format=pdf").status_code == 401


def test_overall_and_timeline_files_match_the_dashboard(client, admin):
    pid, _ = full_setup(client, admin)
    ov = dash(client, admin, pid, "overall")
    act, pct = ov["kpis"]["activities"], ov["kpis"]["overall"]["pct_display"]
    x = sheets(export(client, admin, pid, "overall", "xlsx").content)
    summary = {r[0]: r[1] for r in x["Summary"] if r[0] and r[1]}
    assert summary["Overall completion"] == f"{pct}%" and summary["Overdue activities"] == str(act["overdue"]) and summary["Total phases"] == str(act["phases"])
    phases = x["Phases"]
    assert len(phases) - 1 == len(ov["rows"]) and [r[1] for r in phases[1:]] == [r["label"] for r in ov["rows"]]
    assert [r[3] for r in phases[1:]] == [r["pct"] for r in ov["rows"]]  # the same % per phase
    text = pdf_text(export(client, admin, pid, "overall", "pdf").content)
    assert "Project status" in text and f"{pct}%" in text and "Project Kick Off" in text and "Timeline" in text and "Tegra ERP" in text
    assert "Page 1" in text
    deck = ppt_text(export(client, admin, pid, "overall", "pptx").content)
    assert f"{pct}%" in deck and "Project Kick Off" in deck
    # timeline: every task and tracker event, with baseline and current dates
    t = sheets(export(client, admin, pid, "timeline", "xlsx").content)
    items = get(client, admin, f"/projects/{pid}/work-items?size=500&as_of={AS_OF}")["items"]
    assert len(t["Tasks and milestones"]) - 1 == len(items) > 150
    by_title = {r[1]: r for r in t["Tasks and milestones"][1:]}
    for it in items[:25]:
        row = next(r for r in t["Tasks and milestones"][1:] if r[1] == it["title"] and str(r[6])[:10] == (it["planned_finish"] or ""))
        assert str(row[7])[:10] == (it["effective_start"] or "") or row[7] is None
    assert len(t["Tracker milestones"]) - 1 == dash(client, admin, pid, "overall")["sources"]["tracker_events"]
    assert by_title
    deck = ppt_text(export(client, admin, pid, "timeline", "pptx").content)
    assert "more rows are in the Excel export" in deck  # long lists are cut in PowerPoint and say so


def test_overdue_gates_attention_and_week_files_match_their_screens(client, admin):
    pid, prods = full_setup(client, admin)
    # overdue activities
    d = get(client, admin, f"/projects/{pid}/dashboards/drilldown/overdue?as_of={AS_OF}&size=100")
    x = sheets(export(client, admin, pid, "overdue", "xlsx").content)
    rows = x["Overdue activities"][1:]
    assert len(rows) == d["total"] and sorted(r[0] for r in rows) == sorted(i["title"] for i in d["items"])
    assert [r[7] for r in rows] == sorted((i["days_late"] for i in d["items"]), reverse=True)  # most late first
    delays = dash(client, admin, pid, "delays")
    assert len(x["Delayed items, all sources"]) - 1 == delays["total"]
    text = pdf_text(export(client, admin, pid, "overdue", "pdf").content)
    assert "Overdue activities" in text and all(safe(" ".join(i["title"].split())[:25]) in text for i in d["items"][:3])  # the PDF fonts have no en dash: it prints as a hyphen
    assert all(" ".join(i["title"].split())[:30] in ppt_text(export(client, admin, pid, "overdue", "pptx").content) for i in d["items"][:3])
    # gates
    g = sheets(export(client, admin, pid, "gates", "xlsx").content)
    expected = sum(len([x for x in dash(client, admin, pid, f"product/{p}")["gates"]]) for p in prods.values() if dash(client, admin, pid, f"product/{p}")["gates"])
    assert len(g["Sign-off gates and go-live"]) - 1 == expected
    with SessionLocal() as db:
        assert len(g["Blueprint approvals"]) - 1 == db.scalar(select(func.count()).select_from(ApprovalGate))
    # needs attention (project wide) and for one product
    na = sheets(export(client, admin, pid, "attention", "xlsx", product_id=prods["PLM"]).content)["Needs attention"][1:]
    assert [r[2] for r in na] == [i["text"] for i in dash(client, admin, pid, f"product/{prods['PLM']}")["needs_attention"]]
    assert sheets(export(client, admin, pid, "attention", "xlsx").content)["Needs attention"][1:]
    # next week
    wk = dash(client, admin, pid, "next-week", period="next_week")
    w = sheets(export(client, admin, pid, "next_week", "xlsx").content)["Activities"][1:]
    assert len(w) == wk["total_cards"]
    assert "Next week" in pdf_text(export(client, admin, pid, "next_week", "pdf").content)


def test_coverage_report_equals_the_coverage_screen(client, admin):
    pid, _ = setup_project(client, admin)
    empty = sheets(export(client, admin, pid, "coverage", "xlsx").content)
    assert "No coverage activities" in " ".join(str(r[0]) for r in empty["Summary"] if r[0])
    fin = client.post(f"{API}/departments", json={"code": "FIN", "name": "Finance"}, headers=admin).json()["id"]
    blr = client.post(f"{API}/locations", json={"code": "BLR", "name": "Bengaluru"}, headers=admin).json()["id"]
    dxb = client.post(f"{API}/locations", json={"code": "DXB", "name": "Dubai"}, headers=admin).json()["id"]
    for loc, planned, done in ((blr, 4, 2), (dxb, 4, 4)):
        assert client.post(f"{API}/projects/{pid}/records/coverage-activities", json={"title": "AP", "department_id": fin, "location_id": loc, "planned_count": planned, "completed_count": done}, headers=admin).status_code == 201
    cov = get(client, admin, f"/projects/{pid}/dashboards/coverage")
    x = sheets(export(client, admin, pid, "coverage", "xlsx").content)
    summary = {r[0]: r[1] for r in x["Summary"] if r[0] and r[1]}
    assert summary["Coverage"] == f"{cov['total']['pct']:g}%" and summary["Planned"] == "8" and summary["Completed"] == "6"
    assert [r[0] for r in x["Locations compared"][1:]] == [l["name"] for l in cov["locations"]]  # best first, same order as the screen
    assert "75% (6/8)" in " ".join(str(c) for r in x["Dept x location coverage"] for c in r)
    t = pdf_text(export(client, admin, pid, "coverage", "pdf").content)
    assert "Department and location coverage" in t and "Bengaluru" in t and "75%" in t


def test_product_report_has_every_section_and_empty_projects_still_export(client, admin):
    pid, prods = full_setup(client, admin)
    x = sheets(export(client, admin, pid, "product", "xlsx", product_id=prods["PLM"]).content)
    assert {"Summary", "Phases", "Sign-off gate tracker", "Blueprint approvals", "Needs attention"} <= set(x)
    pv = dash(client, admin, pid, f"product/{prods['PLM']}")
    assert len(x["Phases"]) - 1 == len(pv["rows"]) and len(x["Sign-off gate tracker"]) - 1 == len(pv["gates"])
    assert "PLM" in pdf_text(export(client, admin, pid, "product", "pdf", product_id=prods["PLM"]).content)
    blank, _ = setup_project_blank(client, admin)
    for key in ("overall", "timeline", "gates", "attention", "overdue", "next_week", "coverage"):
        for fmt in ("xlsx", "pdf", "pptx"):
            assert export(client, admin, blank, key, fmt).status_code == 200, (key, fmt)
    t = new_item(client, admin, blank, title="Only task")
    assert "Only task" in pdf_text(export(client, admin, blank, "timeline", "pdf").content) and t


def setup_project_blank(client, admin):
    cust = client.get(f"{API}/customers", headers=admin).json()["items"][0]["id"]
    return client.post(f"{API}/projects", json={"customer_id": cust, "code": "BLANK", "name": "Blank project"}, headers=admin).json()["id"], None


def test_text_typed_by_people_never_becomes_a_spreadsheet_formula(client, admin):
    """A task title or a remark starting with '=' must open as text in Excel, not run (spreadsheet injection)."""
    import zipfile  # noqa: PLC0415

    pid, _ = setup_project(client, admin)
    new_item(client, admin, pid, title='=HYPERLINK("http://evil.example","click")', owner_name="@SUM(1+1)")
    client.post(f"{API}/projects/{pid}/records/week-plan-items", json={"title": "=1+1", "target_date": "2026-11-25", "week_start": "2026-11-23"}, headers=admin)
    for key, params in (("timeline", ""), ("overdue", ""), ("next_week", "")):
        content = export(client, admin, pid, key, "xlsx").content
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            for name in z.namelist():
                if name.startswith("xl/worksheets/"):
                    assert b"<f>" not in z.read(name), (key, name)  # no sheet contains a formula
    t = sheets(export(client, admin, pid, "timeline", "xlsx").content)["Tasks and milestones"]
    assert any(str(r[1]).startswith("=HYPERLINK") for r in t[1:])  # the text itself is still there
    wb = openpyxl.load_workbook(io.BytesIO(client.get(f"{API}/projects/{pid}/dashboard-exports/next_week?as_of={AS_OF}&format=xlsx", headers=admin).content))
    cell = next(c for r in wb["Week plan"].iter_rows() for c in r if c.value == "=1+1")
    assert cell.data_type == "s"  # stored as text
