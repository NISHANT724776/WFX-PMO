import pytest

API = "/api/v1"


# ---------- auth ----------
def test_login_wrong_password_and_unknown_user_are_identical(client):
    a = client.post(f"{API}/auth/login", json={"email": "admin@example.com", "password": "wrong-password-1"})
    b = client.post(f"{API}/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-1"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_protected_routes_require_token(client):
    assert client.get(f"{API}/customers").status_code == 401
    assert client.get(f"{API}/customers", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_me_returns_role_and_permissions(client, admin):
    me = client.get(f"{API}/auth/me", headers=admin).json()
    assert me["role"] == "super_admin" and "users:write" in me["permissions"]


def test_inactive_user_token_rejected(client, admin, make_user):
    uid, hdr = make_user("qa")
    assert client.get(f"{API}/auth/me", headers=hdr).status_code == 200
    assert client.patch(f"{API}/users/{uid}", json={"is_active": False}, headers=admin).status_code == 200
    assert client.get(f"{API}/auth/me", headers=hdr).status_code == 401


# ---------- RBAC (backend enforced) ----------
def test_read_only_role_cannot_write_master_data(client, make_user):
    _, hdr = make_user("developer")
    assert client.get(f"{API}/customers", headers=hdr).status_code == 200
    r = client.post(f"{API}/customers", json={"code": "X", "name": "X"}, headers=hdr)
    assert r.status_code == 403


def test_non_admin_cannot_manage_users_or_read_audit(client, make_user):
    _, hdr = make_user("project_manager")
    assert client.get(f"{API}/users", headers=hdr).status_code == 403
    assert client.get(f"{API}/audit-logs", headers=hdr).status_code == 403


def test_password_policy_enforced(client, admin):
    r = client.post(
        f"{API}/users",
        json={"email": "a@b.co", "full_name": "A", "password": "short", "role_code": "qa"},
        headers=admin,
    )
    assert r.status_code == 422


def test_admin_cannot_demote_self(client, admin):
    me = client.get(f"{API}/auth/me", headers=admin).json()
    r = client.patch(f"{API}/users/{me['id']}", json={"is_active": False}, headers=admin)
    assert r.status_code == 400


# ---------- master data ----------
def test_customer_crud_search_pagination_and_duplicate(client, admin):
    for i in range(3):
        r = client.post(f"{API}/customers", json={"code": f"C{i}", "name": f"Cust {i}"}, headers=admin)
        assert r.status_code == 201
    assert client.post(f"{API}/customers", json={"code": "C0", "name": "dup"}, headers=admin).status_code == 409
    page = client.get(f"{API}/customers?size=2&page=2", headers=admin).json()
    assert page["total"] == 3 and len(page["items"]) == 1
    assert client.get(f"{API}/customers?q=Cust 1", headers=admin).json()["total"] == 1
    cid = page["items"][0]["id"]
    assert client.patch(f"{API}/customers/{cid}", json={"name": "Renamed"}, headers=admin).json()["name"] == "Renamed"
    assert client.delete(f"{API}/customers/{cid}", headers=admin).status_code == 204
    assert client.get(f"{API}/customers/{cid}", headers=admin).status_code == 404


def test_invalid_code_rejected(client, admin):
    assert client.post(f"{API}/products", json={"code": "bad code!", "name": "P"}, headers=admin).status_code == 422


# ---------- projects, products, sites, record-level access ----------
def _setup_tegra(client, admin):
    cust = client.post(f"{API}/customers", json={"code": "TEGRA", "name": "Tegra"}, headers=admin).json()
    plm = client.post(f"{API}/products", json={"code": "PLM", "name": "PLM"}, headers=admin).json()
    loc = client.post(f"{API}/locations", json={"code": "ARENA", "name": "Arena", "country": "Honduras"}, headers=admin).json()
    proj = client.post(
        f"{API}/projects",
        json={"customer_id": cust["id"], "code": "TEGRA-ERP", "name": "Tegra ERP", "start_date": "2026-02-02",
              "target_go_live": "2027-06-01"},
        headers=admin,
    )
    assert proj.status_code == 201, proj.text
    return cust, plm, loc, proj.json()


def test_project_with_products_and_sites(client, admin):
    cust, plm, loc, proj = _setup_tegra(client, admin)
    r = client.post(f"{API}/projects/{proj['id']}/products", json={"product_id": plm["id"]}, headers=admin)
    assert r.status_code == 201 and r.json()["products"][0]["product"]["code"] == "PLM"
    assert client.post(f"{API}/projects/{proj['id']}/products", json={"product_id": plm["id"]}, headers=admin).status_code == 409
    r = client.post(f"{API}/projects/{proj['id']}/sites", json={"location_id": loc["id"], "entity_name": "Arena"}, headers=admin)
    assert r.json()["sites"][0]["location"]["code"] == "ARENA"
    link = client.get(f"{API}/projects/{proj['id']}", headers=admin).json()["products"][0]["id"]
    assert client.delete(f"{API}/projects/{proj['id']}/products/{link}", headers=admin).json()["products"] == []


def test_project_date_order_validated(client, admin):
    cust, *_ = _setup_tegra(client, admin)
    r = client.post(
        f"{API}/projects",
        json={"customer_id": cust["id"], "code": "BAD", "name": "Bad", "start_date": "2026-05-01", "target_go_live": "2026-01-01"},
        headers=admin,
    )
    assert r.status_code == 422


def test_unknown_customer_rejected(client, admin):
    r = client.post(
        f"{API}/projects",
        json={"customer_id": "00000000-0000-0000-0000-000000000001", "code": "Z", "name": "Z"},
        headers=admin,
    )
    assert r.status_code == 422


def test_record_level_project_access(client, admin, make_user):
    cust, _, _, p1 = _setup_tegra(client, admin)
    p2 = client.post(f"{API}/projects", json={"customer_id": cust["id"], "code": "OTHER", "name": "Other"}, headers=admin).json()
    uid, pm = make_user("project_manager")
    # no grants yet: sees nothing, and cannot open or edit directly by id
    assert client.get(f"{API}/projects", headers=pm).json()["total"] == 0
    assert client.get(f"{API}/projects/{p1['id']}", headers=pm).status_code == 404
    assert client.patch(f"{API}/projects/{p1['id']}", json={"name": "hacked"}, headers=pm).status_code == 404
    # grant p1 only
    assert client.put(f"{API}/users/{uid}/project-access", json={"project_ids": [p1["id"]]}, headers=admin).status_code == 200
    ids = [p["id"] for p in client.get(f"{API}/projects", headers=pm).json()["items"]]
    assert ids == [p1["id"]]
    assert client.get(f"{API}/projects/{p2['id']}", headers=pm).status_code == 404
    assert client.patch(f"{API}/projects/{p1['id']}", json={"status": "Active"}, headers=pm).status_code == 200
    # PM can edit but not create/delete projects
    assert client.post(f"{API}/projects", json={"customer_id": cust["id"], "code": "N", "name": "N"}, headers=pm).status_code == 403
    assert client.delete(f"{API}/projects/{p1['id']}", headers=pm).status_code == 403


def test_global_scope_role_sees_all_projects(client, admin, make_user):
    cust, *_ = _setup_tegra(client, admin)
    _, mgmt = make_user("management")
    assert client.get(f"{API}/projects", headers=mgmt).json()["total"] == 1
    assert client.patch(f"{API}/projects/{client.get(f'{API}/projects', headers=mgmt).json()['items'][0]['id']}",
                        json={"name": "x"}, headers=mgmt).status_code == 403


# ---------- flex fields ----------
def test_flex_field_rules(client, admin):
    base = {"entity_type": "work_item", "field_type": "dropdown", "slot": 1, "label": "Phase Gate", "options": ["A", "B"]}
    assert client.post(f"{API}/custom-fields", json=base, headers=admin).status_code == 201
    assert client.post(f"{API}/custom-fields", json=base, headers=admin).status_code == 409  # slot taken
    assert client.post(f"{API}/custom-fields", json={**base, "slot": 6}, headers=admin).status_code == 422
    assert client.post(f"{API}/custom-fields", json={**base, "slot": 2, "options": None}, headers=admin).status_code == 422
    text = {"entity_type": "work_item", "field_type": "text", "slot": 1, "label": "Note", "options": ["x"]}
    assert client.post(f"{API}/custom-fields", json=text, headers=admin).status_code == 422


def test_flex_patch_cannot_break_dropdown(client, admin):
    base = {"entity_type": "work_item", "field_type": "dropdown", "slot": 1, "label": "G", "options": ["A"]}
    fid = client.post(f"{API}/custom-fields", json=base, headers=admin).json()["id"]
    assert client.patch(f"{API}/custom-fields/{fid}", json={"options": []}, headers=admin).status_code == 422
    assert client.patch(f"{API}/custom-fields/{fid}", json={"slot": 3}, headers=admin).status_code == 422
    listed = client.get(f"{API}/custom-fields?entity_type=work_item", headers=admin).json()
    assert listed[0]["options"] == ["A"]  # failed patch did not persist


# ---------- audit ----------
def test_audit_log_records_changes_with_before_after(client, admin):
    c = client.post(f"{API}/customers", json={"code": "AUD", "name": "Before"}, headers=admin).json()
    client.patch(f"{API}/customers/{c['id']}", json={"name": "After"}, headers=admin)
    client.delete(f"{API}/customers/{c['id']}", headers=admin)
    logs = client.get(f"{API}/audit-logs?entity_type=customer&entity_id={c['id']}", headers=admin).json()["items"]
    assert sorted(l["action"] for l in logs) == ["create", "delete", "update"]
    upd = next(l for l in logs if l["action"] == "update")
    assert upd["before"]["name"] == "Before" and upd["after"]["name"] == "After"
    assert all(l["user_email"] == "admin@example.com" for l in logs)


def test_login_events_audited_without_secrets(client):
    client.post(f"{API}/auth/login", json={"email": "admin@example.com", "password": "nope-nope-nope"})
    client.post(f"{API}/auth/login", json={"email": "admin@example.com", "password": "Admin-Test-Pass-1"})
    h = {"Authorization": "Bearer " + client.post(f"{API}/auth/login", json={"email": "admin@example.com", "password": "Admin-Test-Pass-1"}).json()["access_token"]}
    logs = client.get(f"{API}/audit-logs?entity_type=user", headers=h).json()["items"]
    assert {"login", "login_failed"} <= {l["action"] for l in logs}
    assert "password" not in str(logs).lower().replace("login_failed", "")


def test_user_audit_never_contains_password_hash(client, admin):
    r = client.post(
        f"{API}/users",
        json={"email": "n@x.co", "full_name": "N", "password": "Long-Enough-Pass-1", "role_code": "qa"},
        headers=admin,
    )
    assert r.status_code == 201
    logs = client.get(f"{API}/audit-logs?entity_type=user&action=create", headers=admin).json()["items"]
    assert "password_hash" not in str(logs)


def test_seed_is_idempotent():
    from app.db.session import SessionLocal
    from app.models import Permission, Role
    from app.seed import seed

    with SessionLocal() as db:
        n_roles, n_perms = db.query(Role).count(), db.query(Permission).count()
        seed(db)
        seed(db)
        assert (db.query(Role).count(), db.query(Permission).count()) == (n_roles, n_perms)
