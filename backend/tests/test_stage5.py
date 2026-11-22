"""Stage 5: dashboard builder. Widget data must equal the fixed dashboards; layouts obey scope permissions, versions and validation."""
import copy

from test_phase2 import get, setup_project
from test_phase4 import AS_OF, dash, full_setup
from test_stage1 import member

API = "/api/v1"


def wdata(client, hdr, pid, wtype, config=None, filters=None):
    r = client.post(f"{API}/projects/{pid}/widgets/{wtype}/data", json={"config": config or {}, "filters": filters or {}, "as_of": AS_OF}, headers=hdr)
    assert r.status_code == 200, (wtype, r.text)
    return r.json()


def layouts(client, hdr, pid):
    return get(client, hdr, f"/dashboard-layouts?project_id={pid}")


def mk(client, hdr, **body):
    return client.post(f"{API}/dashboard-layouts", json=body, headers=hdr)


def w(i, type_, x, y, ww, hh, **config):
    return {"id": f"w{i}", "type": type_, "x": x, "y": y, "w": ww, "h": hh, "config": config}


def cfg(*widgets, **filters):
    return {"version": 1, "filters": filters, "widgets": list(widgets)}


# ======================================================================= registry and data
def test_widget_registry_describes_every_type(client, admin):
    r = get(client, admin, "/widget-types")
    types = {t["type"]: t for t in r["types"]}
    assert r["grid_columns"] == 12
    assert {"kpi_strip", "breakdown", "delays", "phase_timeline", "gate_tracker", "needs_attention", "week_plan", "coverage", "product_completion", "upcoming_milestones", "text_note", "uat_status"} <= set(types)
    for t in types.values():
        assert t["title"] and t["description"] and t["shape"] and t["default_size"]["w"] >= t["min_size"]["w"]
        for s in t["settings"]:
            assert s["kind"] in ("select", "multiselect", "product", "location", "number", "text", "longtext")
    assert {o["value"] for o in next(s for s in types["breakdown"]["settings"] if s["key"] == "source")["options"]} == {"activities", "pending", "delivery", "gates", "actions", "uat", "defects", "integrations", "reports"}
    assert {o["value"] for o in next(s for s in types["breakdown"]["settings"] if s["key"] == "chart_type")["options"]} == {"bar", "donut", "table"}


def test_every_widget_returns_data_in_its_declared_shape_on_real_tegra_data(client, admin):
    pid, _ = full_setup(client, admin)
    for t in get(client, admin, "/widget-types")["types"]:
        d = wdata(client, admin, pid, t["type"])
        assert d["type"] == t["type"] and d["shape"] in (t["shape"], "empty"), (t["type"], d["shape"])
    assert wdata(client, admin, pid, "text_note", {"text": "Finance", "size": "body"}) == {"type": "text_note", "shape": "text", "text": "Finance", "size": "body", "as_of": AS_OF}


def test_widget_numbers_equal_the_fixed_dashboards(client, admin):
    pid, prods = full_setup(client, admin)
    ov = dash(client, admin, pid, "overall")
    act = ov["kpis"]["activities"]
    kp = {i["key"]: i for i in wdata(client, admin, pid, "kpi_strip", {"kpis": ["overall_pct", "phases", "completed", "in_progress", "overdue", "upcoming_milestones", "not_started", "start_delayed"]})["items"]}
    assert kp["overall_pct"]["value"] == f"{ov['kpis']['overall']['pct_display']}%" and kp["phases"]["value"] == act["phases"]
    for k in ("completed", "in_progress", "overdue", "upcoming_milestones", "not_started", "start_delayed"):
        assert kp[k]["value"] == act[k] and kp[k]["drill"] == k
        assert get(client, admin, f"/projects/{pid}/dashboards/drilldown/{k}?as_of={AS_OF}")["total"] == kp[k]["value"]  # the click-through lists exactly that many
    # status breakdown of activities is an exact partition of all activities
    s = {x["label"]: x["value"] for x in wdata(client, admin, pid, "breakdown", {"source": "activities"})["series"]}
    assert sum(s.values()) == act["all"] and s["Completed"] == act["completed"] and s["Overdue"] == act["overdue"]
    over = {r["id"] for r in get(client, admin, f"/projects/{pid}/dashboards/drilldown/overdue?as_of={AS_OF}&size=100")["items"]}
    ip = {r["id"] for r in get(client, admin, f"/projects/{pid}/dashboards/drilldown/in_progress?as_of={AS_OF}&size=100")["items"]}
    assert s["In progress"] == len(ip - over)
    # delays
    dl = dash(client, admin, pid, "delays")
    by_source = wdata(client, admin, pid, "delays", {"dimension": "source", "limit": 25})
    assert by_source["total"] == dl["total"] and {x["label"]: x["value"] for x in by_source["series"]} == {x["label"]: x["count"] for x in dl["sources"] if x["available"]}
    assert [x["value"] for x in wdata(client, admin, pid, "delays", {"dimension": "ageing"})["series"]] == [x["count"] for x in dl["ageing"]]
    # product completion and the phase timeline
    pc = {x["label"]: x["value"] for x in wdata(client, admin, pid, "product_completion")["series"]}
    for code, pidd in prods.items():
        pv = dash(client, admin, pid, f"product/{pidd}")
        if pv["kpis"]["overall"]["total"] and code in pc:
            assert pc[code] == pv["kpis"]["overall"]["pct_display"]
    tl = wdata(client, admin, pid, "phase_timeline", {"limit": 60})
    assert [r["label"] for r in tl["rows"]] == [r["label"] for r in ov["rows"]] and tl["total"] == len(ov["rows"])
    assert {r["state"] for r in wdata(client, admin, pid, "phase_timeline", {"state": "overdue"})["rows"]} <= {"overdue"}
    # product-scoped widgets equal the product dashboard
    plm = prods["PLM"]
    pv = dash(client, admin, pid, f"product/{plm}")
    g = wdata(client, admin, pid, "gate_tracker", {"product_id": plm, "limit": 40})
    assert [x["name"] for x in g["gates"]] == [x["name"] for x in pv["gates"]] and g["approval_summary"] == pv["approval_summary"]
    na = wdata(client, admin, pid, "needs_attention", {"product_id": plm, "limit": 30})
    assert [i["text"] for i in na["items"]] == [i["text"] for i in pv["needs_attention"]]
    assert all(i["severity"] == "high" for i in wdata(client, admin, pid, "needs_attention", {"product_id": plm, "severity": "high"})["items"])
    # milestones: the table length matches the tile when the horizon is wide enough
    um = wdata(client, admin, pid, "upcoming_milestones", {"days": 730, "limit": 30})
    assert um["total"] == act["upcoming_milestones"] and [r["date"] for r in um["rows"]] == sorted(r["date"] for r in um["rows"])
    # week plan equals the week dashboard
    wk = dash(client, admin, pid, "next-week", period="next_week")
    wp = wdata(client, admin, pid, "week_plan", {"period": "next_week", "limit": 30})
    assert wp["total_cards"] == wk["total_cards"] and wp["week"] == wk["week"]


def test_dashboard_wide_filters_apply_but_a_widgets_own_choice_wins(client, admin):
    pid, prods = full_setup(client, admin)
    plm, erp = prods["PLM"], prods["ERP"]
    plm_only = wdata(client, admin, pid, "kpi_strip", {"kpis": ["overall_pct", "completed"]}, {"product_id": plm})
    all_ = wdata(client, admin, pid, "kpi_strip", {"kpis": ["overall_pct", "completed"]})
    assert plm_only["product_id"] == plm and plm_only["items"][1]["value"] != all_["items"][1]["value"]
    own = wdata(client, admin, pid, "kpi_strip", {"kpis": ["overall_pct", "completed"], "product_id": erp}, {"product_id": plm})
    assert own["product_id"] == erp
    pv = dash(client, admin, pid, f"product/{erp}")
    assert own["items"][0]["value"] == f"{pv['kpis']['overall']['pct_display']}%"


def test_widget_settings_are_validated(client, admin):
    pid, _ = setup_project(client, admin)
    post = lambda t, c=None, f=None: client.post(f"{API}/projects/{pid}/widgets/{t}/data", json={"config": c or {}, "filters": f or {}}, headers=admin)  # noqa: E731
    assert post("breakdown", {"chart_type": "pie"}).status_code == 422
    assert post("breakdown", {"source": "nope"}).status_code == 422
    assert post("breakdown", {"colour": "red"}).status_code == 422  # unknown setting
    assert post("delays", {"limit": 0}).status_code == 422 and post("delays", {"limit": 99}).status_code == 422 and post("delays", {"limit": "5"}).status_code == 422
    assert post("kpi_strip", {"kpis": ["overall_pct", "bogus"]}).status_code == 422
    assert post("kpi_strip", {"kpis": ["completed", "completed"]}).status_code == 422
    assert post("kpi_strip", {"product_id": "00000000-0000-0000-0000-000000000000"}).status_code == 422
    assert post("kpi_strip", {"product_id": "not-a-uuid"}).status_code == 422
    assert post("coverage", {"location_id": "00000000-0000-0000-0000-000000000000"}).status_code == 422
    assert post("kpi_strip", {}, {"product_id": "00000000-0000-0000-0000-000000000000"}).status_code == 422
    assert post("kpi_strip", {}, {"colour": "x"}).status_code == 422
    assert post("nonsense").status_code == 404
    assert post("text_note", {"text": "x" * 2001}).status_code == 422
    assert post("coverage").json()["shape"] == "empty"  # no data: says so, not a zero


def test_widget_data_respects_project_access(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    _, outsider = make_user("project_manager")
    assert client.post(f"{API}/projects/{pid}/widgets/kpi_strip/data", json={}, headers=outsider).status_code == 404
    assert client.post(f"{API}/projects/{pid}/widgets/kpi_strip/data", json={}).status_code == 401


# ======================================================================= layouts: scopes and permissions
def test_default_template_is_listed_read_only_and_is_the_default(client, admin):
    pid, _ = setup_project(client, admin)
    lst = layouts(client, admin, pid)
    assert lst["active_id"] == "template:status" and lst["items"][0]["id"] == "template:status" and lst["items"][0]["scope"] == "template" and not lst["items"][0]["can_edit"]
    t = get(client, admin, "/dashboard-layouts/template:status")
    types = [x["type"] for x in t["config"]["widgets"]]
    assert types[:3] == ["kpi_strip", "phase_timeline", "breakdown"] and "needs_attention" in types and "gate_tracker" in types and "week_plan" in types
    assert client.put(f"{API}/dashboard-layouts/template:status", json={"version": 0, "name": "x"}, headers=admin).status_code == 403
    assert client.delete(f"{API}/dashboard-layouts/template:status", headers=admin).status_code == 403
    assert client.get(f"{API}/dashboard-layouts/template:nope", headers=admin).status_code == 404


def test_scope_permissions(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    dev = member(client, admin, make_user, "developer", pid)
    pm = member(client, admin, make_user, "project_manager", pid)
    _, pmo = make_user("pmo")
    base = cfg(w(1, "text_note", 0, 0, 4, 2, text="Hello"))
    # personal: any user who can read
    mine = mk(client, dev, name="My view", scope="personal", config=base)
    assert mine.status_code == 201, mine.text
    assert mk(client, dev, name="Team view", scope="project", project_id=pid, config=base).status_code == 403  # read-only role cannot publish to a project
    assert mk(client, dev, name="Org view", scope="management", config=base).status_code == 403
    assert mk(client, pm, name="Org view", scope="management", config=base).status_code == 403  # a PM edits projects, not the organisation's dashboards
    proj = mk(client, pm, name="Team view", scope="project", project_id=pid, config=base)
    assert proj.status_code == 201
    org = mk(client, pmo, name="Executive view", scope="management", config=base)
    assert org.status_code == 201, org.text
    # visibility
    assert {i["name"] for i in layouts(client, dev, pid)["items"]} == {"Project status (default)", "My view", "Team view", "Executive view"}
    assert {i["name"] for i in layouts(client, pm, pid)["items"]} == {"Project status (default)", "Team view", "Executive view"}  # the PM does not see the developer's personal view
    assert client.get(f"{API}/dashboard-layouts/{mine.json()['id']}", headers=pm).status_code == 404
    assert client.put(f"{API}/dashboard-layouts/{mine.json()['id']}", json={"version": 1, "name": "Hijack"}, headers=pm).status_code == 404
    # who may edit what
    items = {i["name"]: i for i in layouts(client, dev, pid)["items"]}
    assert items["My view"]["can_edit"] and not items["Team view"]["can_edit"] and not items["Executive view"]["can_edit"]
    assert client.put(f"{API}/dashboard-layouts/{proj.json()['id']}", json={"version": 1, "name": "x"}, headers=dev).status_code == 403
    assert client.put(f"{API}/dashboard-layouts/{org.json()['id']}", json={"version": 1, "name": "x"}, headers=pm).status_code == 403
    assert client.delete(f"{API}/dashboard-layouts/{org.json()['id']}", headers=pm).status_code == 403
    assert client.put(f"{API}/dashboard-layouts/{proj.json()['id']}", json={"version": 1, "name": "Team view v2"}, headers=pm).status_code == 200
    # a project layout is invisible to people without access to that project
    _, outsider = make_user("project_manager", "outsider@example.com")
    assert client.get(f"{API}/dashboard-layouts/{proj.json()['id']}", headers=outsider).status_code == 404
    assert client.get(f"{API}/dashboard-layouts?project_id={pid}", headers=outsider).status_code == 404
    other = setup_second_project(client, admin)
    assert client.put(f"{API}/users/{outsider_id(client, admin)}/project-access", json={"project_ids": [other]}, headers=admin).status_code == 200
    assert {i["name"] for i in layouts(client, outsider, other)["items"]} == {"Project status (default)", "Executive view"}  # management view is shared everywhere, the other project's is not
    assert client.get(f"{API}/dashboard-layouts/{proj.json()['id']}", headers=outsider).status_code == 404
    # names are unique per scope
    assert mk(client, dev, name="my VIEW", scope="personal", config=base).status_code == 409
    assert mk(client, pm, name="Team view v2", scope="project", project_id=pid, config=base).status_code == 409
    assert mk(client, admin, name="My view", scope="personal", config=base).status_code == 201  # another user's personal name does not clash


def setup_second_project(client, admin):
    cust = client.get(f"{API}/customers", headers=admin).json()["items"][0]["id"]
    return client.post(f"{API}/projects", json={"customer_id": cust, "code": "OTHER", "name": "Other"}, headers=admin).json()["id"]


def outsider_id(client, admin):
    users = client.get(f"{API}/users?size=100", headers=admin).json()["items"]
    return next(u["id"] for u in users if u["email"] == "outsider@example.com")


# ======================================================================= layout validation, versions, duplicate, restore
def test_layout_validation(client, admin):
    pid, prods = setup_project(client, admin)
    bad = lambda c: mk(client, admin, name=f"L{abs(hash(str(c))) % 99999}", scope="personal", config=c).status_code  # noqa: E731
    assert bad(cfg(w(1, "kpi_strip", 0, 0, 12, 2))) == 201
    assert bad(cfg(w(1, "nonsense", 0, 0, 4, 3))) == 422
    assert bad(cfg(w(1, "breakdown", 10, 0, 4, 4))) == 422  # past column 12
    assert bad(cfg(w(1, "breakdown", -1, 0, 4, 4))) == 422
    assert bad(cfg(w(1, "breakdown", 0, 0, 1, 4))) == 422  # narrower than the minimum
    assert bad(cfg(w(1, "breakdown", 0, 0, 4, 99))) == 422
    assert bad(cfg(w(1, "breakdown", 0, 0, 4.5, 4))) == 422
    assert bad(cfg(w(1, "breakdown", 0, 0, 4, 4), w(2, "delays", 3, 2, 4, 4))) == 422  # overlap
    assert bad(cfg(w(1, "breakdown", 0, 0, 4, 4), w(1, "delays", 4, 0, 4, 4))) == 422  # duplicate id
    assert bad(cfg({"id": "bad id!", "type": "delays", "x": 0, "y": 0, "w": 4, "h": 4, "config": {}})) == 422
    assert bad(cfg(w(1, "breakdown", 0, 0, 4, 4, chart_type="pie"))) == 422  # settings validated too
    assert bad(cfg(w(1, "delays", 0, 0, 4, 4, product_id=prods["PLM"]))) == 422  # not a setting of this type
    assert bad(cfg(w(1, "kpi_strip", 0, 0, 12, 2), product_id="00000000-0000-0000-0000-000000000000")) == 422
    assert bad({"widgets": "no"}) == 422 and bad({"widgets": [], "extra": 1}) == 422 and bad(cfg(filters_x=1)) == 422
    many = [w(i, "text_note", (i % 6) * 2, (i // 6) * 2, 2, 2) for i in range(41)]
    assert bad(cfg(*many)) == 422
    assert bad(cfg(*many[:40])) == 201  # exactly at the limit
    assert bad(cfg(w(1, "text_note", 0, 0, 4, 2, text="ok"), product_id=prods["PLM"])) == 201  # product id valid in the dashboard filter


def test_versions_duplicate_and_restore_default(client, admin):
    pid, _ = setup_project(client, admin)
    base = cfg(w(1, "text_note", 0, 0, 4, 2, text="One"))
    a = mk(client, admin, name="Mine", scope="personal", config=base).json()
    assert a["version"] == 1
    # two editors: the second save is refused, nothing is overwritten
    first = client.put(f"{API}/dashboard-layouts/{a['id']}", json={"version": 1, "config": cfg(w(1, "text_note", 0, 0, 4, 2, text="Two"))}, headers=admin)
    assert first.status_code == 200 and first.json()["version"] == 2
    stale = client.put(f"{API}/dashboard-layouts/{a['id']}", json={"version": 1, "config": cfg(w(1, "text_note", 0, 0, 4, 2, text="Three"))}, headers=admin)
    assert stale.status_code == 409 and "version 2" in stale.json()["detail"]
    assert get(client, admin, f"/dashboard-layouts/{a['id']}")["config"]["widgets"][0]["config"]["text"] == "Two"
    # duplicate the default template, a personal view and into another scope
    d1 = mk(client, admin, name="From template", scope="personal", from_id="template:status")
    assert d1.status_code == 201 and d1.json()["config"] == get(client, admin, "/dashboard-layouts/template:status")["config"]
    d2 = mk(client, admin, name="Team copy", scope="project", project_id=pid, from_id=a["id"])
    assert d2.status_code == 201 and d2.json()["config"]["widgets"][0]["config"]["text"] == "Two" and d2.json()["version"] == 1 and d2.json()["id"] != a["id"]
    assert mk(client, admin, name="Bad source", scope="personal", from_id="template:nope").status_code == 404
    # restore default
    edited = client.put(f"{API}/dashboard-layouts/{d1.json()['id']}", json={"version": 1, "config": cfg(w(1, "text_note", 0, 0, 4, 2))}, headers=admin).json()
    assert len(edited["config"]["widgets"]) == 1
    assert client.post(f"{API}/dashboard-layouts/{d1.json()['id']}/restore-default", json={"version": 1}, headers=admin).status_code == 409  # stale
    back = client.post(f"{API}/dashboard-layouts/{d1.json()['id']}/restore-default", json={"version": edited["version"]}, headers=admin).json()
    assert back["config"] == get(client, admin, "/dashboard-layouts/template:status")["config"] and back["version"] == edited["version"] + 1
    # renaming
    assert client.put(f"{API}/dashboard-layouts/{a['id']}", json={"version": 2, "name": "  Renamed   view "}, headers=admin).json()["name"] == "Renamed view"
    actions = {x["action"] for x in get(client, admin, "/audit-logs?entity_type=dashboard_layout&size=50")["items"]}
    assert {"create", "update", "restore_default"} <= actions


def test_layout_and_choice_are_restored_on_the_next_visit(client, admin, make_user):
    """Acceptance steps 17-18: customise, save, come back later (a fresh sign-in) and find it."""
    pid, _ = full_setup(client, admin)
    uid, pm = make_user("project_manager")
    client.put(f"{API}/users/{uid}/project-access", json={"project_ids": [pid]}, headers=admin)
    assert layouts(client, pm, pid)["active_id"] == "template:status"  # first visit: the default template
    mine = mk(client, pm, name="My status", scope="personal", from_id="template:status").json()
    custom = copy.deepcopy(mine["config"])
    custom["widgets"] = [x for x in custom["widgets"] if x["type"] != "coverage"] + [w(9, "breakdown", 8, 13, 4, 5, source="pending", chart_type="table")]
    saved = client.put(f"{API}/dashboard-layouts/{mine['id']}", json={"version": 1, "config": custom}, headers=pm)
    assert saved.status_code == 200, saved.text
    assert client.put(f"{API}/projects/{pid}/dashboard-pref", json={"layout_id": mine["id"]}, headers=pm).json() == {"layout_id": mine["id"]}
    # a brand new session for the same user
    from conftest import _login  # noqa: PLC0415
    again = _login(client, "project_manager@example.com")
    lst = layouts(client, again, pid)
    assert lst["active_id"] == mine["id"]
    restored = get(client, again, f"/dashboard-layouts/{lst['active_id']}")["config"]
    assert restored == saved.json()["config"] and any(x["config"].get("source") == "pending" for x in restored["widgets"])
    # and it still draws live numbers: the pending breakdown equals the pending widget data, not a stored copy
    pend = wdata(client, again, pid, "breakdown", {"source": "pending", "chart_type": "table"})
    assert pend["shape"] == "series"
    # choosing the default again, a layout of someone else, and deletion
    assert client.put(f"{API}/projects/{pid}/dashboard-pref", json={"layout_id": None}, headers=again).json()["layout_id"] == "template:status"
    assert client.put(f"{API}/projects/{pid}/dashboard-pref", json={"layout_id": mine["id"]}, headers=again).status_code == 200
    theirs = mk(client, admin, name="Admin only", scope="personal", config=cfg(w(1, "text_note", 0, 0, 4, 2))).json()
    assert client.put(f"{API}/projects/{pid}/dashboard-pref", json={"layout_id": theirs["id"]}, headers=again).status_code == 404
    assert client.delete(f"{API}/dashboard-layouts/{mine['id']}", headers=again).status_code == 204
    assert layouts(client, again, pid)["active_id"] == "template:status"  # the deleted layout falls back to the default


def test_restoring_a_shared_layout_needs_the_right_to_edit(client, admin, make_user):
    pid, _ = setup_project(client, admin)
    dev = member(client, admin, make_user, "developer", pid)
    org = mk(client, admin, name="Exec", scope="management", config=cfg(w(1, "text_note", 0, 0, 4, 2))).json()
    assert client.post(f"{API}/dashboard-layouts/{org['id']}/restore-default", json={"version": 1}, headers=dev).status_code == 403
    assert client.post(f"{API}/dashboard-layouts/{org['id']}/restore-default", json={"version": 1}, headers=admin).status_code == 200
