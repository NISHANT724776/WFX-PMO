"""UAT scenarios and defects, integrations, reports + prints, flex-field entities: rules, summaries that match the records, dashboards, exports, Excel import."""
import io
import zipfile
from datetime import date, timedelta

import openpyxl
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.workspace import IntegrationItem, ReportItem, UatDefect, UatScenario
from test_phase2 import XLSX, confirm_medium, get, setup_project, upload
from test_phase4 import AS_OF, dash
from test_stage1 import member

API = "/api/v1"
TODAY = date.today()


def rec(client, hdr, pid, kind, method="get", rid=None, body=None, params=""):
    url = f"{API}/projects/{pid}/records/{kind}" + (f"/{rid}" if rid else "") + params
    return getattr(client, method)(url, headers=hdr, **({"json": body} if body is not None else {}))


def scenario(client, hdr, pid, **kw):
    r = rec(client, hdr, pid, "uat-scenarios", "post", body={"title": "Post a purchase invoice", **kw})
    assert r.status_code == 201, r.text
    return r.json()


# ======================================================================= UAT rules
def test_uat_scenario_rules(client, admin):
    pid, prods = setup_project(client, admin)
    s = scenario(client, admin, pid, scenario_id="AP-01", module="Accounts Payable", cycle="Cycle 1", planned_date="2026-11-10", product_id=prods["ERP"])
    assert s["result"] == "not_run" and s["is_overdue"] is True  # planned 10 Nov, not run, and today is later
    patch = lambda body: rec(client, admin, pid, "uat-scenarios", "patch", s["id"], body)  # noqa: E731
    assert patch({"result": "passed"}).status_code == 422  # who tested it?
    assert patch({"result": "passed", "tester": "Meera"}).status_code == 422  # and when?
    assert patch({"result": "passed", "tester": "Meera", "executed_date": (TODAY + timedelta(days=3)).isoformat()}).status_code == 422  # not in the future
    assert patch({"result": "failed", "tester": "Meera", "executed_date": "2026-11-12"}).status_code == 422  # a failure needs the actual result
    assert patch({"result": "nonsense"}).status_code == 422
    assert get(client, admin, f"/projects/{pid}/records/uat-scenarios/{s['id']}")["result"] == "not_run"  # nothing saved by the refusals
    ok = patch({"result": "failed", "tester": "Meera", "executed_date": "2026-11-12", "actual_result": "Tax not calculated"}).json()
    assert ok["result"] == "failed" and ok["tester"] == "Meera"
    # a defect against it; then it cannot be passed while the defect is open
    d = rec(client, admin, pid, "uat-defects", "post", body={"title": "GST missing on invoice", "scenario_id": s["id"], "severity": "high", "raised_on": "2026-11-12", "owner_name": "Ravi", "target_date": "2026-11-15"})
    assert d.status_code == 201, d.text
    bad = patch({"result": "passed"})
    assert bad.status_code == 422 and "open defect" in bad.json()["detail"]
    # defect rules
    dp = lambda body: rec(client, admin, pid, "uat-defects", "patch", d.json()["id"], body)  # noqa: E731
    assert dp({"status": "closed"}).status_code == 422  # needs date and resolution
    assert dp({"status": "closed", "closed_on": "2026-11-13"}).status_code == 422
    assert dp({"status": "closed", "closed_on": "2026-11-01", "resolution": "x"}).status_code == 422  # before it was raised
    assert dp({"status": "rejected"}).status_code == 422
    closed = dp({"status": "closed", "closed_on": "2026-11-14", "resolution": "Tax code mapped"}).json()
    assert closed["status"] == "closed" and closed["is_closed"] and closed["closed_on"] == "2026-11-14"
    assert patch({"result": "passed"}).status_code == 200  # no open defect any more
    assert dp({"status": "open"}).status_code == 422  # the scenario is Passed, so its defect cannot be reopened until the scenario is Failed or Retest
    assert patch({"result": "retest"}).status_code == 200
    reopened = dp({"status": "open"}).json()  # reopening clears the closed date; the close stays in the audit log
    assert reopened["closed_on"] is None
    assert rec(client, admin, pid, "uat-defects", "post", body={"title": "Another", "scenario_id": s["id"]}).status_code == 201
    assert patch({"result": "passed"}).status_code == 422  # two defects are open again
    assert patch({"result": "failed", "actual_result": "Still failing"}).status_code == 200
    assert rec(client, admin, pid, "uat-defects", "patch", rec(client, admin, pid, "uat-defects").json()["items"][1]["id"], {"status": "closed", "closed_on": "2026-11-16", "resolution": "x"}).status_code == 200
    assert patch({"result": "passed"}).status_code == 422  # one is still open
    # scenario from another project is refused
    pid2, _ = None, None
    cust = client.get(f"{API}/customers", headers=admin).json()["items"][0]["id"]
    other = client.post(f"{API}/projects", json={"customer_id": cust, "code": "P2", "name": "Other"}, headers=admin).json()["id"]
    foreign = scenario(client, admin, other, title="Foreign")
    assert rec(client, admin, pid, "uat-defects", "post", body={"title": "x", "scenario_id": foreign["id"]}).status_code == 422
    assert pid2 is None
    logs = get(client, admin, f"/audit-logs?entity_type=uat_defect&entity_id={d.json()['id']}&size=20")["items"]
    assert any(l["before"] and l["before"].get("closed_on") == "2026-11-14" for l in logs)


def test_uat_permissions(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    dev = member(client, admin, make_user, "developer", pid)
    assert rec(client, dev, pid, "uat-scenarios", "post", body={"title": "x"}).status_code == 403
    assert rec(client, dev, pid, "uat-defects", "post", body={"title": "x"}).status_code == 403
    assert rec(client, dev, pid, "uat-scenarios").status_code == 200  # they can read


# ======================================================================= summaries equal the records
def test_uat_summary_matches_the_records_and_feeds_every_dashboard(client, admin):
    pid, prods = setup_project(client, admin)
    plan = [("Accounts Payable", "Cycle 1", "passed", "2026-11-05"), ("Accounts Payable", "Cycle 1", "passed", "2026-11-05"), ("Accounts Payable", "Cycle 1", "failed", "2026-11-06"),
            ("Accounts Payable", "Cycle 2", "not_run", "2026-11-10"), ("General Ledger", "Cycle 1", "blocked", "2026-11-12"), ("General Ledger", "Cycle 1", "not_run", "2026-12-20"),
            ("General Ledger", "Cycle 2", "in_progress", None), ("General Ledger", "Cycle 2", "retest", "2026-11-16")]
    for module, cycle, result, planned in plan:
        body = {"module": module, "cycle": cycle, "planned_date": planned, "product_id": prods["ERP"]}
        if result in ("passed", "failed"):
            body.update(result=result, tester="Meera", executed_date="2026-11-07", actual_result="Tax not calculated" if result == "failed" else None)
        s = scenario(client, admin, pid, **body)
        if result not in ("not_run", "passed", "failed"):
            assert rec(client, admin, pid, "uat-scenarios", "patch", s["id"], {"result": result}).status_code == 200
    failed = next(s for s in rec(client, admin, pid, "uat-scenarios", params="?result=failed").json()["items"])
    for sev, status_ in (("critical", "open"), ("high", "in_fix"), ("low", "open")):
        rec(client, admin, pid, "uat-defects", "post", body={"title": f"{sev} defect", "scenario_id": failed["id"], "severity": sev, "status": status_, "raised_on": "2026-11-08", "target_date": "2026-11-12"})
    rec(client, admin, pid, "uat-defects", "post", body={"title": "closed one", "scenario_id": failed["id"], "severity": "medium", "status": "closed", "closed_on": "2026-11-09", "resolution": "fixed", "raised_on": "2026-11-08"})
    u = get(client, admin, f"/projects/{pid}/uat/summary?as_of={AS_OF}")
    S, D = u["scenarios"], u["defects"]
    assert S["total"] == 8 and S["by_result"] == {"passed": 2, "failed": 1, "blocked": 1, "retest": 1, "in_progress": 1, "not_run": 2}
    assert S["pass_rate"] == 25.0 and S["executed_pct"] == 37.5 and S["to_do"] == 5
    assert S["overdue"] == 3  # to do and planned before 17 Nov: not-run 10 Nov, blocked 12 Nov, retest 16 Nov
    ap = next(r for r in S["by_module"] if r["name"] == "Accounts Payable")
    assert (ap["total"], ap["passed"], ap["failed"], ap["not_run"], ap["pass_rate"]) == (4, 2, 1, 1, 50.0)
    assert next(r for r in S["by_cycle"] if r["name"] == "Cycle 2")["total"] == 3
    assert D["total"] == 4 and D["open"] == 3 and D["closed"] == 1 and D["open_by_severity"] == {"critical": 1, "high": 1, "medium": 0, "low": 1} and D["overdue"] == 3
    assert D["oldest_open_days"] == 9
    assert get(client, admin, f"/projects/{pid}/uat/summary?as_of={AS_OF}&product_id={prods['PLM']}")["scenarios"]["total"] == 0  # product filter
    # delays: scenarios and defects are sources
    dl = dash(client, admin, pid, "delays")
    src = {s["key"]: s for s in dl["sources"]}
    assert src["uat_scenario"]["count"] == 3 and src["uat_defect"]["count"] == 3 and src["uat_scenario"]["label"] == "UAT scenarios"
    assert dl["total"] == 6
    # needs attention names them
    pv = dash(client, admin, pid, f"product/{prods['ERP']}")["needs_attention"]
    assert any(i["kind"] == "defect" and "2 open critical / high" in i["text"] for i in pv) and any(i["kind"] == "uat" and i["text"].startswith("3 UAT") for i in pv)
    # week plan carries them (week of 16 Nov holds the retest scenario and the defect target date 12 Nov is carried over)
    wk = dash(client, admin, pid, "next-week", period="this_week")
    uat = next(g for g in wk["groups"] if g["name"] == "UAT")
    assert any("General Ledger" in c["title"] for c in uat["cards"]) and any(c["tag"] == "carry_over" for c in uat["cards"])
    # widgets
    w = lambda cfg: client.post(f"{API}/projects/{pid}/widgets/uat_status/data", json={"config": cfg, "as_of": AS_OF}, headers=admin).json()  # noqa: E731
    assert {x["label"]: x["value"] for x in w({"view": "result"})["series"]}["Passed"] == 2
    assert {x["label"]: x["value"] for x in w({"view": "module"})["series"]}["Accounts Payable"] == 50.0
    assert {x["label"]: x["value"] for x in w({"view": "defects"})["series"]} == {"Critical": 1, "High": 1, "Medium": 0, "Low": 1}
    bd = client.post(f"{API}/projects/{pid}/widgets/breakdown/data", json={"config": {"source": "uat"}, "as_of": AS_OF}, headers=admin).json()
    assert sum(x["value"] for x in bd["series"]) == 8
    # exports equal the summary
    x = openpyxl.load_workbook(io.BytesIO(client.get(f"{API}/projects/{pid}/exports/uat?format=xlsx&as_of={AS_OF}", headers=admin).content))
    summary = {r[0].value: r[1].value for r in x["Summary"].iter_rows() if r[0].value and r[1].value}
    assert summary["Scenarios"] == "8" and summary["Pass rate"] == "25%" and summary["Open defects"] == "3"
    assert x["Scenarios"].max_row - 1 == 8 and x["Defects"].max_row - 1 == 4
    for fmt, magic in (("pdf", b"%PDF"), ("pptx", b"PK")):
        r = client.get(f"{API}/projects/{pid}/exports/uat?format={fmt}&as_of={AS_OF}", headers=admin)
        assert r.status_code == 200 and r.content[:len(magic)] == magic
    # archived scenarios leave every number
    assert client.post(f"{API}/projects/{pid}/lifecycle/uat_scenario/{failed['id']}/archive", json={}, headers=admin).status_code == 200
    assert get(client, admin, f"/projects/{pid}/uat/summary?as_of={AS_OF}")["scenarios"]["total"] == 7


# ======================================================================= integrations and reports/prints
def test_integrations_and_reports_trackers(client, admin):
    pid, prods = setup_project(client, admin)
    mk = lambda kind, **b: rec(client, admin, pid, kind, "post", body=b)  # noqa: E731
    i1 = mk("integration-items", name="E-invoicing to GST portal", partner="NIC", direction="outbound", technology="API", target_date="2026-11-10", owner_name="Anil", product_id=prods["ERP"])
    assert i1.status_code == 201, i1.text
    assert i1.json()["target_date"] == "2026-11-10"
    i2 = mk("integration-items", name="Bank statement import", partner="HDFC", direction="inbound", technology="SFTP", target_date="2026-12-20", status="in_progress")
    r1 = mk("report-items", name="Aged payables", report_type="report", module="AP", folder="Finance", complexity="medium", target_date="2026-11-05", owner_name="Pooja", product_id=prods["ERP"])
    r2 = mk("report-items", name="Tax invoice", report_type="print", module="AR", folder="Finance", target_date="2026-11-30")
    for r in (i2, r1, r2):
        assert r.status_code == 201, r.text
    assert mk("integration-items", name="x", direction="sideways").status_code == 422
    assert mk("report-items", name="x", complexity="huge").status_code == 422
    assert rec(client, admin, pid, "integration-items", "patch", i1.json()["id"], {"target_date": "2026-11-20"}).status_code == 422  # the baseline moves only by revision
    rv = client.post(f"{API}/projects/{pid}/records/integration-items/{i1.json()['id']}/revisions", json={"field": "target_date", "new_date": "2026-11-25", "reason": "Partner sandbox delayed", "approve": True}, headers=admin)
    assert rv.status_code == 201, rv.text
    cur = get(client, admin, f"/projects/{pid}/records/integration-items/{i1.json()['id']}?as_of={AS_OF}")
    assert cur["target_date"] == "2026-11-10" and cur["effective_target_date"] == "2026-11-25" and cur["slippage_days"] == 15 and not cur["is_overdue"]  # baseline kept, no longer overdue
    s = get(client, admin, f"/projects/{pid}/deliverables/summary?as_of={AS_OF}")
    assert s["integrations"]["total"] == 2 and s["integrations"]["overdue"] == 0 and s["integrations"]["by_status"]["in_progress"] == 1
    assert s["reports"]["total"] == 2 and s["reports"]["overdue"] == 1 and s["reports"]["due_in_14_days"] == 1  # Aged payables (5 Nov) late; Tax invoice (30 Nov) is 13 days away
    # closing: status done, or an actual date
    assert rec(client, admin, pid, "report-items", "patch", r1.json()["id"], {"status": "done", "actual_date": "2026-11-14"}).status_code == 200
    assert rec(client, admin, pid, "report-items", "patch", r1.json()["id"], {"status": "no_such_status"}).status_code == 422
    assert get(client, admin, f"/projects/{pid}/deliverables/summary?as_of={AS_OF}")["reports"]["overdue"] == 0
    # delays / week plan / attention
    mk("report-items", name="Stock ageing", report_type="report", target_date="2026-10-20")
    mk("integration-items", name="Courier tracking", partner="DHL", target_date="2026-11-18")
    dl = dash(client, admin, pid, "delays")
    src = {x["key"]: x for x in dl["sources"]}
    assert src["report_item"]["count"] == 1 and src["integration_item"]["count"] == 0 and src["report_item"]["label"] == "Reports + prints"
    wk = dash(client, admin, pid, "next-week", period="this_week")
    names = {g["name"]: [c["title"] for c in g["cards"]] for g in wk["groups"]}
    assert "Courier tracking" in names["Integrations"] and "Stock ageing" in names["Reports + prints"]
    na = dash(client, admin, pid, f"product/{prods['ERP']}")["needs_attention"]
    assert any(i["kind"] == "deliverable" and "report / print(s)" in i["text"] for i in na)
    # exports
    x = openpyxl.load_workbook(io.BytesIO(client.get(f"{API}/projects/{pid}/exports/deliverables?format=xlsx&as_of={AS_OF}", headers=admin).content))
    assert x["Integrations"].max_row - 1 == 3 and x["Reports + prints"].max_row - 1 == 3
    # archive, duplicate, bulk through the shared engine
    assert client.post(f"{API}/projects/{pid}/lifecycle/report_item/{r2.json()['id']}/duplicate", json={}, headers=admin).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ReportItem)) == 4 and db.scalar(select(func.count()).select_from(IntegrationItem)) == 3


# ======================================================================= Excel import
def _workbook() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "UAT Scenarios"
    ws.append(["Scenario ID", "Scenario", "Module", "Pre Condition", "Test Data", "Expected Result", "Business Objective", "Tester", "Test Status", "Planned Date"])
    rows = [("AP-01", "Post vendor invoice", "Accounts Payable", "Vendor exists", "INV-1", "Posted", "Pay vendors", "Meera", "Passed", date(2026, 11, 5)),
            ("AP-02", "Reverse a payment", "Accounts Payable", "Paid invoice", "PAY-1", "Reversed", "Correct errors", "Meera", "Failed", date(2026, 11, 6)),
            ("GL-01", "Month end close", "General Ledger", "Open period", "-", "Closed", "Close books", "Ravi", "Not Started", date(2026, 11, 9)),
            ("GL-02", "Intercompany posting", "General Ledger", "Two entities", "-", "Posted", "Consolidate", "Ravi", "Re-test", date(2026, 11, 10)),
            ("GL-03", "Accrual reversal", "General Ledger", "Accrual", "-", "Reversed", "Accuracy", "Ravi", "Maybe later", date(2026, 11, 11))]
    for r in rows:
        ws.append(list(r))
    ws2 = wb.create_sheet("Integrations")
    ws2.append(["Partner", "System", "Message Type", "Technology", "Direction", "Region", "Endpoint", "Business Domain", "Status", "Target Date"])
    ws2.append(["NIC", "GST portal", "E-invoice", "API", "Outbound", "India", "https://example.test/einv", "Finance", "In Progress", date(2026, 11, 20)])
    ws2.append(["HDFC", "Bank", "Statement", "SFTP", "Inbound", "India", "sftp://example.test/in", "Treasury", "Not Started", date(2026, 12, 5)])
    ws3 = wb.create_sheet("Reports Inventory")
    ws3.append(["Folder", "Sub Folder", "Reports Count", "Owner", "Status", "Target Date"])
    ws3.append(["Finance", "Payables", 12, "Pooja", "In Progress", date(2026, 11, 25)])
    ws3.append(["Finance", "Receivables", 9, "Pooja", "Done", date(2026, 11, 10)])
    ws3.append(["Logistics", "Stock", 7, "Kiran", "Not Started", date(2026, 12, 1)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_excel_import_of_uat_integration_and_report_sheets(client, admin):
    pid, _ = setup_project(client, admin)
    b = get(client, admin, f"/imports/{upload(client, admin, _workbook()).json()['id']}")
    classes = {s["name"]: (s["entity"], s["class"] if "class" in s else None) for s in b["sheets"]}
    assert classes["UAT Scenarios"][0] == "uat_scenario" and classes["Integrations"][0] == "integration_item" and classes["Reports Inventory"][0] == "report_item", classes
    confirm_medium(client, admin, b["id"])
    # the UAT sheet reports wording it cannot place instead of guessing
    uat_sheet = next(s for s in b["sheets"] if s["name"] == "UAT Scenarios")
    r = client.post(f"{API}/imports/{b['id']}/commit", json={"project_id": pid, "confirm_rejected": True}, headers=admin)
    assert r.status_code == 200, r.text
    created = {s["sheet"]: s["created"] for s in r.json()["sheets"]}
    assert created == {"UAT Scenarios": 5, "Integrations": 2, "Reports Inventory": 3}
    sc = {x["scenario_id"]: x for x in rec(client, admin, pid, "uat-scenarios", params="?size=50").json()["items"]}
    assert {k: v["result"] for k, v in sc.items()} == {"AP-01": "passed", "AP-02": "failed", "GL-01": "not_run", "GL-02": "retest", "GL-03": "not_run"}
    assert sc["GL-03"]["result_raw"] == "Maybe later"  # unknown wording: kept, and the scenario is not silently called passed or failed
    assert sc["AP-01"]["tester"] == "Meera" and sc["AP-01"]["planned_date"] == "2026-11-05" and sc["AP-01"]["module"] == "Accounts Payable"
    integ = {x["partner"]: x for x in rec(client, admin, pid, "integration-items").json()["items"]}
    assert integ["NIC"]["target_date"] == "2026-11-20" and integ["NIC"]["status_category"] == "in_progress" and integ["NIC"]["technology"] == "API"
    reps = {x["sub_folder"]: x for x in rec(client, admin, pid, "report-items").json()["items"]}
    assert reps["Payables"]["reports_count"] == 12 and reps["Receivables"]["status_category"] == "done"
    assert get(client, admin, f"/projects/{pid}/deliverables/summary?as_of={AS_OF}")["reports"]["reports_count"] == 28
    # rolling back removes what the import created
    assert client.post(f"{API}/imports/{b['id']}/rollback", headers=admin).status_code == 200
    assert rec(client, admin, pid, "uat-scenarios").json()["total"] == 0 and uat_sheet


# ======================================================================= flex fields on every record type
def test_flex_fields_can_be_defined_for_every_record_type(client, admin):
    pid, _ = setup_project(client, admin)
    ents = {e["value"]: e["label"] for e in get(client, admin, "/custom-fields/entities")}
    assert {"work_item", "dependency_item", "uat_scenario", "uat_defect", "integration_item", "report_item", "delivery_item", "approval_gate"} <= set(ents) and len(ents) == 16
    assert client.post(f"{API}/custom-fields", json={"entity_type": "nonsense", "field_type": "text", "slot": 1, "label": "x"}, headers=admin).status_code == 422
    dd = client.post(f"{API}/custom-fields", json={"entity_type": "uat_scenario", "field_type": "dropdown", "slot": 1, "label": "Severity of business impact", "options": ["Low", "High"]}, headers=admin)
    dt = client.post(f"{API}/custom-fields", json={"entity_type": "uat_scenario", "field_type": "date", "slot": 1, "label": "Customer sign-off"}, headers=admin)
    tx = client.post(f"{API}/custom-fields", json={"entity_type": "uat_scenario", "field_type": "text", "slot": 1, "label": "Business owner"}, headers=admin)
    assert dd.status_code == dt.status_code == tx.status_code == 201
    s = scenario(client, admin, pid)
    vals = get(client, admin, f"/custom-field-values/uat_scenario/{s['id']}")
    assert [v["label"] for v in vals] == ["Customer sign-off", "Severity of business impact", "Business owner"]  # date, dropdown, text
    ids = {v["label"]: v["definition_id"] for v in vals}
    put = client.put(f"{API}/custom-field-values/uat_scenario/{s['id']}", json={"values": [{"definition_id": ids["Severity of business impact"], "value": "High"}, {"definition_id": ids["Customer sign-off"], "value": "2026-12-01"},
                                                                                       {"definition_id": ids["Business owner"], "value": "CFO"}]}, headers=admin)
    assert put.status_code == 200
    again = {v["label"]: v["value"] for v in get(client, admin, f"/custom-field-values/uat_scenario/{s['id']}")}
    assert again == {"Severity of business impact": "High", "Customer sign-off": "2026-12-01", "Business owner": "CFO"}
    bad = client.put(f"{API}/custom-field-values/uat_scenario/{s['id']}", json={"values": [{"definition_id": ids["Severity of business impact"], "value": "Extreme"}]}, headers=admin)
    assert bad.status_code == 422  # not one of the options
    # a record type with no definitions simply has none
    d = rec(client, admin, pid, "delivery-items", "post", body={"description": "Ticket"}).json()
    assert get(client, admin, f"/custom-field-values/delivery_item/{d['id']}") == []
    assert client.get(f"{API}/custom-field-values/nonsense/{d['id']}", headers=admin).status_code == 404
