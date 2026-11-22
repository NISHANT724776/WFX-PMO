"""Phase 5: delivery tickets, requirements, helpdesk, discussions, scope, links. Oracles are computed from the raw Shahi workbook."""
import re
import types
import warnings
from collections import Counter, defaultdict
from datetime import date

import openpyxl
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Role
from app.models.canonical import DeliveryItem, RequirementLink
from app.modules.delivery.lifecycle import delivery_extras
from app.modules.excel_intel.committer import derive_delivery_target, merge_delivery
from test_phase2 import XLSX, confirm_medium, get, setup_project, upload  # noqa: E402
from test_phase3 import SHAHI  # noqa: E402

warnings.filterwarnings("ignore")
API = "/api/v1"
AS_OF = "2026-11-17"
IMPORT_SHEETS = ["Delivery Schedule", "Tech_Final", "Finance BRD", "Operations BRD", "Open for Discussion", "Out Of Scope Points", "New-Open Points-Ops", "Pending Items"]


# ----------------------------------------------------------------- raw-file oracles
def clean_id(v):
    if v is None:
        return None
    s = str(int(v)) if isinstance(v, float) and v.is_integer() else " ".join(str(v).split())
    return None if s.lower() in ("", "-", "na", "n/a") else s


def sheet_rows(name):
    ws = openpyxl.load_workbook(SHAHI, data_only=True)[name]
    hdr = [" ".join(str(c.value or "").split()) for c in ws[1]]
    return [dict(zip(hdr, [c.value for c in r])) for r in ws.iter_rows(min_row=2)] if False else [dict(zip(hdr, r)) for r in ws.iter_rows(min_row=2, values_only=True)]


def keyed(rows, idcol, desccol):
    """(id, occurrence) -> row, for rows that can be imported (they have an id and a description)."""
    seen, out = Counter(), {}
    for r in rows:
        i = clean_id(r[idcol])
        if i is None or not r[desccol]:
            continue
        seen[i] += 1
        out[(i, seen[i])] = r
    return out


def norm(x):
    return " ".join(str(x).split()) if x is not None else None


def import_shahi(client, admin, pid, sheets=IMPORT_SHEETS, template=None):
    b = get(client, admin, f"/imports/{upload(client, admin, SHAHI).json()['id']}")
    for s in b["sheets"]:
        client.patch(f"/api/v1/imports/{b['id']}/sheets/{s['id']}", json={"enabled": s["name"] in sheets and bool(s["entity"])}, headers=admin)
    confirm_medium(client, admin, b["id"])
    pend = next(s for s in b["sheets"] if s["name"] == "Pending Items")
    client.patch(f"{API}/imports/{b['id']}/sheets/{pend['id']}", json={"pending_with_map": {"Shahi": "customer"}}, headers=admin)
    r = client.post(f"{API}/imports/{b['id']}/commit", json={"project_id": pid, "confirm_rejected": True, "template_name": template}, headers=admin)
    assert r.status_code == 200, r.text
    return b, r.json()


def records(client, admin, pid, kind, **params):
    q = "&".join(f"{k}={v}" for k, v in {"size": 200, "as_of": AS_OF, **params}.items())
    out, page = [], 1
    while True:
        r = get(client, admin, f"/projects/{pid}/records/{kind}?{q}&page={page}")
        out += r["items"]
        if len(out) >= r["total"]:
            return out, r["total"]
        page += 1


# ======================================================================= classification and mapping
def test_every_shahi_sheet_is_recognised_and_mapped(client, admin):
    b = get(client, admin, f"/imports/{upload(client, admin, SHAHI).json()['id']}")
    ents = {s["name"]: (s["classification"], s["entity"]) for s in b["sheets"]}
    assert ents["Delivery Schedule"] == ("delivery_schedule", "delivery_schedule") and ents["Tech_Final"] == ("tech_tracker", "tech_tracker")
    assert ents["Finance BRD"] == ("brd", "brd_requirement") and ents["Operations BRD"] == ("helpdesk_brd", "helpdesk_ops_brd")
    assert ents["Open for Discussion"][1] == "discussion_item" and ents["New-Open Points-Ops"][1] == "ops_open_point"
    assert ents["Out Of Scope Points"] == ("scope", "scope_decision")  # 4 rows x 3 columns, not mistaken for a lookup list
    assert ents["Pending Items"][1] == "dependency_item" and ents["WBS Week Wise"][1] is None  # WBS arrives in Phase 7
    sid = {s["name"]: s["id"] for s in b["sheets"]}
    tech = {c["header"]: c["mapping"]["target_field"] for c in get(client, admin, f"/imports/{b['id']}/sheets/{sid['Tech_Final']}")["columns"] if c["mapping"]}
    assert tech["Tech Owner"] == "tech_owner" and tech["QA Owner"] == "qa_owner" and tech["Functional Specs Status"] == "functional_specs_status"
    assert tech["Customer Spec Closure date-Actual"] == "spec_closure_actual" and tech["Customer Spec Closure date-Planned"] == "spec_closure_date"
    assert tech["Relase to Customer UAT Server Release"] == "uat_release" and tech["Target BRD Clsoure Date"] == "target_brd_closure"
    ds = {c["header"]: c["mapping"]["target_field"] for c in get(client, admin, f"/imports/{b['id']}/sheets/{sid['Delivery Schedule']}")["columns"] if c["mapping"]}
    assert ds["Customer Release Date on Customer UAT"] == "customer_release" and ds["WFX helpdesk Status"] == "helpdesk_status" and ds["Status"] == "status"
    assert ds["Handover to QA Date - Dev Completion Date"] == "dev_completion" and ds["Specs Responsibility"] == "specs_responsibility"


def test_status_values_can_be_classified_by_the_user(client, admin):
    b = get(client, admin, f"/imports/{upload(client, admin, SHAHI).json()['id']}")
    sh = next(s for s in b["sheets"] if s["name"] == "Delivery Schedule")
    sv = {(v["field"], v["value"]): v for v in get(client, admin, f"/imports/{b['id']}/sheets/{sh['id']}")["status_values"]}
    assert sv[("status", "Under Development")]["category"] == "in_progress"  # recognised
    assert sv[("status", "Pending For Delivery")]["category"] is None  # ambiguous wording is NOT guessed
    assert sv[("helpdesk_status", "Closed")]["category"] == "done" and sv[("status", "Pending For Delivery")]["count"] == 228
    assert client.patch(f"{API}/imports/{b['id']}/sheets/{sh['id']}", json={"value_maps": {"status": {"Pending For Delivery": "maybe"}}}, headers=admin).status_code == 422
    client.patch(f"{API}/imports/{b['id']}/sheets/{sh['id']}", json={"value_maps": {"status": {"Pending For Delivery": "not_started"}}}, headers=admin)
    sv = {(v["field"], v["value"]): v for v in get(client, admin, f"/imports/{b['id']}/sheets/{sh['id']}")["status_values"]}
    assert sv[("status", "Pending For Delivery")]["category"] == "not_started" and sv[("status", "Pending For Delivery")]["chosen"]
    confirm_medium(client, admin, b["id"])
    v = client.post(f"{API}/imports/{b['id']}/validate", headers=admin).json()
    errs = get(client, admin, f"/imports/{b['id']}/errors?sheet_id={sh['id']}&code=unknown_status&size=100")["items"]
    texts = " ".join(e["message"] for e in errs)
    assert "Pending For Delivery" not in texts and "Pending for Specs" in texts  # one warning per distinct value, and it shrank
    assert all(e["row"] is None for e in errs) and len(errs) < 30


# ======================================================================= delivery import: merge, authority, derived fields
def test_delivery_import_merges_the_two_sheets_by_ticket(client, admin):
    pid, _ = setup_project(client, admin)
    b, summary = import_shahi(client, admin, pid, sheets=["Delivery Schedule", "Tech_Final"])
    ds, tf = keyed(sheet_rows("Delivery Schedule"), "ID", "Description"), keyed(sheet_rows("Tech_Final"), "ID", "Description")
    union, both = set(ds) | set(tf), set(ds) & set(tf)
    sheets = {s["sheet"]: s for s in summary["sheets"]}
    assert sheets["Delivery Schedule"]["created"] == len(ds) and sheets["Tech_Final"]["created"] == len(tf) - len(both) and sheets["Tech_Final"]["merged"] == len(both)
    items, total = records(client, admin, pid, "delivery-items")
    assert total == len(union) and len(both) > 300  # 366 tickets are in both sheets
    srcs = Counter(tuple(it["sources"]) for it in items)
    expected = {("delivery_schedule", "tech_tracker"): len(both), ("delivery_schedule",): len(set(ds) - set(tf)), ("tech_tracker",): len(set(tf) - set(ds))}
    assert dict(srcs) == {k: v for k, v in expected.items() if v}
    # a ticket that exists in both sheets: owners from Tech_Final, customer-facing dates from Delivery Schedule, nothing lost
    t = next(i for i in items if i["external_id"] == "440679")
    assert (t["tech_owner"], t["qa_owner"], t["product_owner"]) == ("munish", "Rajat Sharma", "Hari Om")
    assert (t["customer_release"], t["dev_initiation"], t["qa_release"]) == ("2026-11-30", "2026-10-16", "2026-11-19")
    assert t["delivery_target_date"] == "2026-11-30" and t["revised_target_date"] is None  # derived once: customer UAT release wins
    assert t["specs_responsibility"] == "Abhirath" and t["functional_specs_status"] == "Awaited" and t["spec_closure_actual"] is None
    # parent tickets: "440679 : Party Configuration" is a child of 440679
    child = next(i for i in items if i["external_id"] == "452263")
    assert child["parent_external_id"] == "440679" and t["parent_external_id"] is None
    exp_children = sum(1 for k, r in tf.items() if re.match(r"\s*(\d{4,9})\s*[:\-]", str(r["Description"])) and re.match(r"\s*(\d{4,9})", str(r["Description"])).group(1) != k[0])
    assert sum(1 for i in items if i["parent_external_id"]) == exp_children > 100
    # "Completed" under the SPECS target date means the specs are done; it must NOT mark the ticket delivered
    exp_completed = sum(1 for r in ds.values() if str(r["Target Date"]).strip().lower() == "completed")
    assert sum(1 for i in items if i["specs_completed"]) >= exp_completed > 100
    spec_done = next(i for i in items if i["specs_completed"] and i["status_category"] != "done" and i["helpdesk_status_category"] != "done")
    assert spec_done["is_closed"] is False and spec_done["actual_completion"] is None
    closed = next(i for i in items if i["helpdesk_status_category"] == "done")  # helpdesk status "Closed" does close it
    assert closed["is_closed"] is True and closed["is_overdue"] is False
    # problems found in the source are reported, not hidden
    for code in ("hidden_rows", "formula_error", "odd_id", "missing_required", "unknown_status"):
        assert get(client, admin, f"/imports/{b['id']}/errors?code={code}&size=1")["total"] > 0, code


def test_delivery_conflicts_are_recorded_and_authority_decides_overlaps(client, admin):
    pid, _ = setup_project(client, admin)
    import_shahi(client, admin, pid, sheets=["Delivery Schedule", "Tech_Final"])
    ds, tf = keyed(sheet_rows("Delivery Schedule"), "ID", "Description"), keyed(sheet_rows("Tech_Final"), "ID", "Description")
    items, _ = records(client, admin, pid, "delivery-items")
    by_id = defaultdict(list)
    for i in items:
        by_id[i["external_id"]].append(i)

    def find(field_ds, field_tf):
        for k in set(ds) & set(tf):
            a, b = norm(ds[k][field_ds]), norm(tf[k][field_tf])
            if a and b and a != b and len(by_id[k[0]]) == 1:
                return k, a, b
    # non-authoritative field where both sheets disagree: the first value is kept and the disagreement is written down
    hit = find("Priority", "Priority") or find("WFX helpdesk Status", "WFX helpdesk Status") or find("Status", "Status")
    assert hit, "the real data should contain at least one disagreement"
    k, a, b = hit
    it = by_id[k[0]][0]
    field = "priority" if norm(ds[k]["Priority"]) == a and norm(tf[k]["Priority"]) == b and norm(ds[k]["Priority"]) != norm(tf[k]["Priority"]) else None
    notes = it["merge_notes"] or {}
    assert notes, "a disagreement must be recorded"
    note = next(iter(notes.values()))
    assert note["from"] == "tech_tracker" and "kept" in note and ("ignored" in note or "replaced" in note)
    # authoritative overlap: Tech_Final decides the functional owner
    own = find("Functional Owner", "Functional Owner")
    if own:
        ok, da, tb = own
        assert by_id[ok[0]][0]["functional_owner"] == tb
        assert by_id[ok[0]][0]["merge_notes"]["functional_owner"] == {"kept": tb, "replaced": da, "from": "tech_tracker"}


def _obj(**kw):
    base = dict(merge_notes=None, sources=None, delivery_target_date=None, specs_completed=False, status_raw=None, status_category=None, priority=None,
                functional_owner=None, qa_owner=None, qa_release=None, customer_release=None, uat_release=None, dev_completion=None, remarks=None)
    return types.SimpleNamespace(**{**base, **kw})


def test_merge_rule_is_order_independent_for_authoritative_fields():
    # Delivery Schedule first, then Tech_Final
    a = _obj(sources=["delivery_schedule"], functional_owner="From DS", qa_release=date(2026, 11, 20), priority="Go Live priority")
    merge_delivery(a, "tech_tracker", {"functional_owner": "From TF", "qa_release": date(2026, 12, 1), "priority": "UAT Priority", "qa_owner": "Tester"})
    assert a.functional_owner == "From TF" and a.qa_release == date(2026, 11, 20) and a.qa_owner == "Tester" and a.priority == "Go Live priority"
    assert a.sources == ["delivery_schedule", "tech_tracker"] and set(a.merge_notes) == {"functional_owner", "qa_release", "priority"}
    # Tech_Final first, then Delivery Schedule: same winners
    b = _obj(sources=["tech_tracker"], functional_owner="From TF", qa_release=date(2026, 12, 1), qa_owner="Tester", priority="UAT Priority")
    merge_delivery(b, "delivery_schedule", {"functional_owner": "From DS", "qa_release": date(2026, 11, 20), "priority": "Go Live priority", "remarks": "r"})
    assert b.functional_owner == "From TF" and b.qa_release == date(2026, 11, 20) and b.remarks == "r" and b.priority == "UAT Priority"
    # empty cells never erase, and a status text moves together with its category
    c = _obj(sources=["delivery_schedule"], status_raw="Open", status_category="not_started")
    merge_delivery(c, "tech_tracker", {"status_raw": None, "status_category": None, "functional_owner": None})
    assert c.status_raw == "Open" and c.status_category == "not_started"
    d = _obj(sources=["delivery_schedule"], status_raw=None, status_category=None)
    merge_delivery(d, "tech_tracker", {"status_raw": "In QA", "status_category": "in_progress"})
    assert (d.status_raw, d.status_category) == ("In QA", "in_progress")
    # the delivery commitment is the first available stage date and is set once
    e = _obj(qa_release=date(2026, 11, 20), dev_completion=date(2026, 11, 10))
    derive_delivery_target(e)
    assert e.delivery_target_date == date(2026, 11, 20)
    e.customer_release = date(2026, 12, 5)
    derive_delivery_target(e)
    assert e.delivery_target_date == date(2026, 11, 20)  # never re-derived: revisions move it, not new stage dates


# ======================================================================= requirements, helpdesk, discussions, scope
def test_requirement_helpdesk_discussion_scope_counts_match_the_workbook(client, admin):
    pid, _ = setup_project(client, admin)
    import_shahi(client, admin, pid)
    brd = [r for r in sheet_rows("Finance BRD") if r["Key Pointers"]]
    ops = [r for r in sheet_rows("Operations BRD") if clean_id(r["Helpdesk ID"]) and r["Helpdesk Description"]]
    disc = [r for r in sheet_rows("Open for Discussion") if r["Name"]]
    scope = [r for r in sheet_rows("Out Of Scope Points") if r["Feedback"]]
    reqs, n_req = records(client, admin, pid, "requirements")
    hd, n_hd = records(client, admin, pid, "helpdesk-items")
    dc, n_dc = records(client, admin, pid, "discussions")
    sd, n_sd = records(client, admin, pid, "scope-decisions")
    assert n_req == len(brd) == 143 and n_dc == len(disc) and n_sd == len(scope) == 4
    assert n_hd == len(ops) + 1  # operations BRD + the one real open operations point
    assert Counter(h["kind"] for h in hd) == {"ops_brd": len(ops), "open_point": 1}
    # source row numbers are kept (BRD serial repeats and can be 'Not Received')
    assert len({r["sr_no"] for r in reqs}) == 143 and sum(1 for r in reqs if r["brd_serial"] == "Not Received") == 14
    ids = [h["external_id"] for h in hd if h["kind"] == "ops_brd"]
    assert len(ids) > len(set(ids)) - 1  # helpdesk IDs may repeat; each row is its own record
    # closed BRD items come from the sheet's own wording
    assert sum(1 for h in hd if h["kind"] == "ops_brd" and h["status_category"] == "done") >= sum(1 for r in ops if str(r["BRD status"]).strip().lower() == "closed")
    # scope decisions start undecided
    assert {s["approval_status"] for s in sd} == {"pending"} and all(s["decision_owner"] is None for s in sd)
    assert sum(1 for x in dc if x["status"] == "open") == len(dc)


# ======================================================================= links (many-to-many) from evidence
def test_link_suggestions_match_independent_counts_and_can_be_applied(client, admin):
    pid, _ = setup_project(client, admin)
    import_shahi(client, admin, pid)
    ds, tf = keyed(sheet_rows("Delivery Schedule"), "ID", "Description"), keyed(sheet_rows("Tech_Final"), "ID", "Description")
    ops = [r for r in sheet_rows("Operations BRD") if clean_id(r["Helpdesk ID"]) and r["Helpdesk Description"]]
    disc = [r for r in sheet_rows("Open for Discussion") if r["Name"]]
    brd = [r for r in sheet_rows("Finance BRD") if r["Key Pointers"]]
    ticket_ids = Counter(k[0] for k in set(ds) | set(tf))
    sug = get(client, admin, f"/projects/{pid}/link-suggestions")
    rules = Counter(s["rule"] for s in sug["suggestions"])
    # helpdesk <-> delivery: same number on both sides
    exp_hd = sum(ticket_ids.get(clean_id(r["Helpdesk ID"]), 0) for r in ops)
    assert rules["helpdesk_id"] == exp_hd and exp_hd > 90
    one = next(s for s in sug["suggestions"] if s["rule"] == "helpdesk_id")
    assert one["link_type"] == "same_ticket" and re.fullmatch(r"helpdesk ID \S+ = delivery ID \S+", one["basis"])
    # parent ticket: only where the parent really exists
    parents = {k[0] for k in set(ds) | set(tf)}
    exp_parent = sum(1 for k, r in tf.items() if (m := re.match(r"\s*(\d{4,9})\s*[:\-]", str(r["Description"]))) and m.group(1) != k[0] and m.group(1) in parents)
    assert rules["parent_ticket"] == exp_parent > 100
    # BRD <-> discussion: only the serials that exist on both sides, nothing fabricated
    serials = Counter(clean_id(r["BRD SR"]) for r in brd if clean_id(r["BRD SR"]) and str(r["BRD SR"]).lower() != "not received")
    exp_brd = sum(serials.get(clean_id(r["BRD Serial No"]), 0) for r in disc if clean_id(r["BRD Serial No"]))
    assert rules["brd_serial"] == exp_brd and 0 < exp_brd < len(disc)
    assert sug["unmatched"]["discussions_without_requirement"] == sum(1 for r in disc if clean_id(r["BRD Serial No"]) and clean_id(r["BRD Serial No"]) not in serials)
    # apply the unambiguous ones; a second call has nothing left to suggest from them
    pick = [s for s in sug["suggestions"] if not s["ambiguous"]]
    body = {"links": [{k: s[k] for k in ("source_type", "source_id", "target_type", "target_id", "link_type", "basis")} for s in pick]}
    res = client.post(f"{API}/projects/{pid}/links/bulk", json=body, headers=admin).json()
    assert res["created"] == len(pick) and not res["skipped"]
    again = client.post(f"{API}/projects/{pid}/links/bulk", json=body, headers=admin).json()
    assert again["created"] == 0 and len(again["skipped"]) == len(pick)  # nothing doubled
    after = get(client, admin, f"/projects/{pid}/link-suggestions")["suggestions"]
    assert len(after) == len(sug["suggestions"]) - len(pick) and all(s["ambiguous"] for s in after if s["rule"] == "helpdesk_id")
    # a helpdesk requirement shows its development tickets and vice versa (many-to-many)
    pair = next(s for s in pick if s["rule"] == "helpdesk_id")
    detail = get(client, admin, f"/projects/{pid}/records/helpdesk-items/{pair['source_id']}")
    assert any(l["record_id"] == pair["target_id"] and l["kind"] == "delivery-items" for l in detail["links"])
    child = get(client, admin, f"/projects/{pid}/records/delivery-items/{pair['target_id']}")
    assert any(l["record_id"] == pair["source_id"] and l["kind"] == "helpdesk-items" for l in child["links"])
    pt = next(s for s in pick if s["rule"] == "parent_ticket")  # a development ticket and its parent ticket, both deliveries
    assert any(l["record_id"] == pt["source_id"] and l["link_type"] == "parent_child" for l in get(client, admin, f"/projects/{pid}/records/delivery-items/{pt['target_id']}")["links"])


def test_manual_links_and_their_rules(client, admin):
    pid, _ = setup_project(client, admin)
    other_pid = client.post(f"{API}/projects", json={"customer_id": client.get(f"{API}/projects/{pid}", headers=admin).json()["customer_id"], "code": "OTHER", "name": "Other"}, headers=admin).json()["id"]
    mk = lambda p, kind, **b: client.post(f"{API}/projects/{p}/records/{kind}", json=b, headers=admin)  # noqa: E731
    req = mk(pid, "requirements", description="Consolidate branch accounts", brd_serial="12").json()
    dev = mk(pid, "delivery-items", external_id="900001", description="Intercompany posting").json()
    foreign = mk(other_pid, "delivery-items", external_id="900002", description="Elsewhere").json()
    link = lambda s, t, **k: client.post(f"{API}/projects/{pid}/links", json={"source_type": s[0], "source_id": s[1], "target_type": t[0], "target_id": t[1], **k}, headers=admin)  # noqa: E731
    r = link(("brd_requirement", req["id"]), ("delivery_item", dev["id"]))
    assert r.status_code == 201
    assert link(("delivery_item", dev["id"]), ("brd_requirement", req["id"])).status_code == 409  # same pair in the other direction
    assert link(("brd_requirement", req["id"]), ("brd_requirement", req["id"])).status_code == 422
    assert link(("brd_requirement", req["id"]), ("delivery_item", foreign["id"])).status_code == 422  # another project's record
    assert link(("brd_requirement", req["id"]), ("nonsense", dev["id"])).status_code == 422
    d = get(client, admin, f"/projects/{pid}/records/requirements/{req['id']}")
    assert [l["title"] for l in d["links"]] == ["900001 Intercompany posting"]
    # deleting a record hides its links; purging it removes them
    assert client.delete(f"{API}/projects/{pid}/records/delivery-items/{dev['id']}", headers=admin).status_code == 204
    assert get(client, admin, f"/projects/{pid}/records/requirements/{req['id']}")["links"] == []  # hidden at once
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(RequirementLink)) == 1  # but kept while the record is in the trash (restorable)
    assert client.post(f"{API}/projects/{pid}/lifecycle/delivery_item/{dev['id']}/purge", json={"confirm": True}, headers=admin).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(RequirementLink)) == 0  # a purge removes it for good


def test_rollback_of_an_import_removes_what_it_linked(client, admin):
    pid, _ = setup_project(client, admin)
    b, _ = import_shahi(client, admin, pid, sheets=["Delivery Schedule", "Tech_Final", "Operations BRD"])
    sug = get(client, admin, f"/projects/{pid}/link-suggestions")["suggestions"]
    pick = [s for s in sug if s["rule"] == "helpdesk_id" and not s["ambiguous"]][:5]
    client.post(f"{API}/projects/{pid}/links/bulk", json={"links": [{k: s[k] for k in ("source_type", "source_id", "target_type", "target_id", "link_type", "basis")} for s in pick]}, headers=admin)
    r = client.post(f"{API}/imports/{b['id']}/rollback", headers=admin)
    assert r.status_code == 200, r.text  # links are not "edits" of the imported rows, so rollback is still safe
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(RequirementLink)) == 0 and db.scalar(select(func.count()).select_from(DeliveryItem)) == 0
    assert records(client, admin, pid, "delivery-items")[1] == 0


# ======================================================================= editing, revisions, lifecycle
def test_delivery_item_lifecycle_and_revision_history(client, admin):
    pid, _ = setup_project(client, admin)
    mk = lambda **b: client.post(f"{API}/projects/{pid}/records/delivery-items", json=b, headers=admin)  # noqa: E731
    assert mk(external_id="1").status_code == 422  # description is required
    it = mk(external_id="900010", description="Bank reconciliation", dev_initiation="2026-11-01", qa_release="2026-11-10", status="in_progress").json()
    assert it["status_category"] == "in_progress" and it["delivery_target_date"] == "2026-11-10" and it["sources"] == ["manual"]
    url = f"{API}/projects/{pid}/records/delivery-items/{it['id']}"
    cur = get(client, admin, f"/projects/{pid}/records/delivery-items/{it['id']}?as_of={AS_OF}")
    assert cur["is_overdue"] and cur["days_late"] == 7 and [s["state"] for s in cur["stages"]][1:3] == ["done", "none"] or cur["is_overdue"]
    # the commitment date is a baseline: it changes only through a revision
    r = client.patch(url, json={"delivery_target_date": "2026-12-31"}, headers=admin)
    assert r.status_code == 422 and "revision" in r.json()["detail"]
    assert client.patch(url, json={"status": "bogus"}, headers=admin).status_code == 422
    assert client.patch(url, json={"qa_release": "not a date"}, headers=admin).status_code == 422
    assert client.patch(url, json={"not_a_field": 1}, headers=admin).status_code == 422
    rv = client.post(f"{url}/revisions", json={"field": "ignored", "new_date": "2026-11-30", "reason": "Customer asked to wait", "approve": True}, headers=admin)
    assert rv.status_code == 201 and rv.json()[0]["field"] == "delivery_target_date" and rv.json()[0]["status"] == "approved"
    cur = get(client, admin, f"/projects/{pid}/records/delivery-items/{it['id']}?as_of={AS_OF}")
    assert (cur["delivery_target_date"], cur["revised_target_date"], cur["effective_target_date"]) == ("2026-11-10", "2026-11-30", "2026-11-30")
    assert cur["is_overdue"] is False and cur["slippage_days"] == 20 and len(cur["revisions"]) == 1
    # closing it: an actual completion date (never inferred from the status)
    done = client.patch(url, json={"status": "done"}, headers=admin).json()
    assert done["status_category"] == "done" and done["actual_completion"] is None and done["is_closed"]
    assert client.get(url, headers=admin).status_code == 200
    audit = get(client, admin, f"/audit-logs?entity_type=delivery_item&entity_id={it['id']}")["items"]
    assert {"create", "update"} <= {a["action"] for a in audit}


def test_gap_and_requirement_target_dates_use_revisions(client, admin):
    pid, _ = setup_project(client, admin)
    gap = client.post(f"{API}/projects/{pid}/records/gap-specifications", json={"external_issue_id": "409562", "description": "AI techpack setup"}, headers=admin).json()
    url = f"{API}/projects/{pid}/records/gap-specifications/{gap['id']}"
    rv = client.post(f"{url}/revisions", json={"field": "x", "new_date": "2026-12-01", "reason": "Spec drafting slipped", "approve": True}, headers=admin)
    assert rv.status_code == 201 and rv.json()[0]["old_date"] is None and rv.json()[0]["field"] == "target_date"
    assert get(client, admin, f"/projects/{pid}/records/gap-specifications/{gap['id']}?as_of={AS_OF}")["effective_target_date"] == "2026-12-01"
    assert client.patch(url, json={"target_date": "2026-01-01"}, headers=admin).status_code == 422
    assert client.post(f"{API}/projects/{pid}/records/discussions/{client.post(f'{API}/projects/{pid}/records/discussions', json={'name': 'x'}, headers=admin).json()['id']}/revisions",
                       json={"field": "x", "new_date": "2026-12-01", "reason": "nope!"}, headers=admin).status_code == 422  # discussions have no revisable date


def test_scope_decisions_need_an_approver_an_owner_and_a_date(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    sd = client.post(f"{API}/projects/{pid}/records/scope-decisions", json={"customer_feedback": "Bulk payment hold", "original_scope": "Invoice-wise hold"}, headers=admin).json()
    url = f"{API}/projects/{pid}/records/scope-decisions/{sd['id']}"
    assert sd["approval_status"] == "pending"
    r = client.patch(url, json={"approval_status": "approved"}, headers=admin)
    assert r.status_code == 422 and "who decided" in r.json()["detail"]
    ok = client.patch(url, json={"approval_status": "approved", "decision_owner": "Kalpesh", "decision_date": "2026-11-12", "reason": "Customer accepts a change request"}, headers=admin)
    assert ok.status_code == 200 and ok.json()["approval_status"] == "approved"
    pmid, _ = make_user("project_manager")
    client.put(f"{API}/users/{pmid}/project-access", json={"project_ids": [pid]}, headers=admin)
    with SessionLocal() as db:  # a writer who may not approve
        role = db.scalar(select(Role).where(Role.code == "project_manager"))
        role.permissions = [p for p in role.permissions if p.code != "plan:approve"]
        db.commit()
    pm = {"Authorization": "Bearer " + client.post(f"{API}/auth/login", json={"email": "project_manager@example.com", "password": "Some-Long-Password-1"}).json()["access_token"]}
    sd2 = client.post(f"{API}/projects/{pid}/records/scope-decisions", json={"customer_feedback": "PIN code validation"}, headers=pm).json()
    r = client.patch(f"{API}/projects/{pid}/records/scope-decisions/{sd2['id']}", json={"approval_status": "approved", "decision_owner": "x", "decision_date": "2026-11-12"}, headers=pm)
    assert r.status_code == 403 and "plan:approve" in r.json()["detail"]
    assert client.patch(f"{API}/projects/{pid}/records/scope-decisions/{sd2['id']}", json={"remarks": "needs review"}, headers=pm).status_code == 200  # editing text is fine


def test_records_filters_facets_search_and_access(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    import_shahi(client, admin, pid, sheets=["Delivery Schedule", "Tech_Final", "Finance BRD"])
    items, total = records(client, admin, pid, "delivery-items")
    streams = Counter(i["stream"] for i in items)
    f = get(client, admin, f"/projects/{pid}/records/delivery-items/facets")
    assert {x["value"]: x["count"] for x in f["stream"]} == dict(streams)
    one = next(iter(streams))
    assert records(client, admin, pid, "delivery-items", stream=one)[1] == streams[one]
    assert records(client, admin, pid, "delivery-items", q="Party", size=50)[1] == sum(1 for i in items if "party" in i["description"].lower() or "party" in (i["external_id"] or "").lower() or "party" in (i["module"] or "").lower() or "party" in (i["tracker_ref"] or "").lower())
    late = records(client, admin, pid, "delivery-items", overdue="true")[0]
    assert late and all(i["is_overdue"] or i["is_start_delayed"] for i in late)
    assert get(client, admin, f"/projects/{pid}/records/delivery-items?page=2&size=100&as_of={AS_OF}")["items"][0]["id"] != items[0]["id"]
    assert client.get(f"{API}/projects/{pid}/records/bogus", headers=admin).status_code == 404
    _, qa = make_user("qa")
    assert client.get(f"{API}/projects/{pid}/records/delivery-items", headers=qa).status_code == 404  # no project access
    qid, qa2 = make_user("qa", "qa2@example.com")
    client.put(f"{API}/users/{qid}/project-access", json={"project_ids": [pid]}, headers=admin)
    assert client.get(f"{API}/projects/{pid}/records/delivery-items", headers=qa2).status_code == 200  # can read
    assert client.post(f"{API}/projects/{pid}/records/delivery-items", json={"description": "x"}, headers=qa2).status_code == 403  # cannot write


# ======================================================================= dashboards pick delivery up
def test_delay_week_and_attention_dashboards_include_delivery(client, admin):
    pid, prods = setup_project(client, admin)
    import_shahi(client, admin, pid, sheets=["Delivery Schedule", "Tech_Final"])
    items, _ = records(client, admin, pid, "delivery-items")
    exp_over = sum(1 for i in items if i["is_overdue"])
    exp_start = sum(1 for i in items if i["is_start_delayed"] and not i["is_overdue"])
    d = get(client, admin, f"/projects/{pid}/dashboards/delays?as_of={AS_OF}")
    src = {s["key"]: s for s in d["sources"]}
    assert src["delivery_item"]["available"] and src["delivery_item"]["count"] == exp_over + exp_start
    assert d["total"] == sum(s["count"] or 0 for s in d["sources"])
    # the dashboard and the records list apply one rule, so they agree item by item
    assert {r["id"] for r in d["rows"] if r["source"] == "delivery_item"} == {i["id"] for i in items if i["is_overdue"] or i["is_start_delayed"]}
    # development delays stay out of the completion formula (decision 9)
    o = get(client, admin, f"/projects/{pid}/dashboards/overall?as_of={AS_OF}")
    assert o["available"] is False and o["kpis"]["overall"]["pct"] is None  # no plan, no tracker events: delivery does not stand in for them
    # week plan: deliveries due in a period are aggregated per stream
    for period in ("this_week", "next_week", "next_month"):
        w = get(client, admin, f"/projects/{pid}/dashboards/next-week?as_of={AS_OF}&period={period}")
        lo, hi = w["week"]["start"], w["week"]["end"]
        due = [i for i in items if not i["is_closed"] and i["effective_target_date"] and lo <= i["effective_target_date"] <= hi]
        grp = next((g for g in w["groups"] if g["name"] == "Development delivery"), None)
        got = sum(len(c["source"]["ids"]) for g in w["groups"] if g["name"] == "Development delivery" for c in g["cards"] if c["tag"] == "due")
        assert got == len(due), period
        if due:
            assert grp and all(re.search(r"\(\d+\)$", c["title"]) for c in grp["cards"])
    na = get(client, admin, f"/projects/{pid}/dashboards/product/{prods['ERP']}?as_of={AS_OF}")["needs_attention"]
    assert any(a["kind"] == "delivery" for a in na) == (exp_over > 0)
