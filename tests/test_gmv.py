"""GMV Max Shopee: công thức, CRUD, UNIQUE(product_id, date), phân quyền, seed."""

from app.gmv import GMV_SEED_PRODUCTS, calc_gmv, validate_gmv_entry
from conftest import activate, create_owner, create_staff, login, logout


def test_calc_formulas():
    c = calc_gmv(
        {"views": 1000, "clicks": 50, "conversions": 10,
         "revenue_vnd": 530000, "ad_cost": 159000}
    )
    assert c["ctr"] == 5.0
    assert c["cir"] == 30.0
    assert c["roas"] == 3.33
    assert c["cpc"] == 3180
    assert c["cr"] == 20.0
    assert c["aov"] == 53000


def test_calc_divide_by_zero_is_none():
    c = calc_gmv({"views": 0, "clicks": 0, "conversions": 0, "revenue_vnd": 0, "ad_cost": 0})
    assert c["ctr"] is None
    assert c["cir"] is None
    assert c["cpc"] is None
    assert c["cr"] is None
    assert c["aov"] is None
    assert c["roas"] is None


def test_validate_entry():
    clean, errors = validate_gmv_entry(
        {
            "date": "2026-10-19",
            "views": "10",
            "clicks": 5,
            "conversions": 2,
            "revenue_vnd": "530000",
            "ad_cost": 30,
            "action_note": "  tăng ngân sách ",
        }
    )
    assert errors == {}
    assert clean["views"] == 10
    assert clean["revenue_vnd"] == 530000
    assert clean["action_note"] == "tăng ngân sách"

    _, errors = validate_gmv_entry({"date": "19/10/2026", "views": -1, "clicks": "abc"})
    assert "date" in errors
    assert "views" in errors
    assert "clicks" in errors


def test_validate_bad_date_rejected():
    _, errors = validate_gmv_entry({"date": "2026-02-30"})
    assert "date" in errors


def _entry(date="2026-10-19", **kw):
    d = {
        "date": date,
        "views": 1000,
        "clicks": 50,
        "conversions": 10,
        "revenue_vnd": 530000,
        "ad_cost": 159000,
        "action_note": "ghi chú",
    }
    d.update(kw)
    return d


def _make_product(client, name="ỐC NỞ"):
    r = client.post("/api/gmv/products", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def test_product_crud(client):
    create_owner(client)
    p = _make_product(client, "LIỀM")
    r = client.get("/api/gmv/products")
    assert r.status_code == 200
    assert any(x["name"] == "LIỀM" for x in r.json()["products"])

    r = client.post("/api/gmv/products", json={"name": "LIỀM"})
    assert r.status_code == 409  # trùng tên

    r = client.patch(f"/api/gmv/products/{p['id']}", json={"name": "LIỀM MỚI"})
    assert r.status_code == 200
    assert r.json()["name"] == "LIỀM MỚI"

    r = client.delete(f"/api/gmv/products/{p['id']}")
    assert r.status_code == 204
    r = client.get(f"/api/gmv/products/{p['id']}/entries")
    assert r.status_code == 404


def test_entry_upsert_same_date_updates(client):
    create_owner(client)
    p = _make_product(client)
    r = client.post(f"/api/gmv/products/{p['id']}/entries", json=_entry())
    assert r.status_code == 201
    r = client.post(f"/api/gmv/products/{p['id']}/entries", json=_entry(views=2000))
    assert r.status_code == 200  # ngày trùng → cập nhật, không tạo dòng mới
    data = client.get(f"/api/gmv/products/{p['id']}/entries").json()
    assert len(data["entries"]) == 1
    assert data["entries"][0]["views"] == 2000
    assert data["entries"][0]["calc"]["ctr"] == 2.5
    assert data["entries"][0]["updated_by"] == "Chủ Shop"
    assert data["last_updated"]


def test_entry_update_date_conflict_409(client):
    create_owner(client)
    p = _make_product(client)
    client.post(f"/api/gmv/products/{p['id']}/entries", json=_entry("2026-10-19"))
    r = client.post(f"/api/gmv/products/{p['id']}/entries", json=_entry("2026-10-20"))
    eid = r.json()["id"]
    r = client.put(f"/api/gmv/entries/{eid}", json=_entry("2026-10-19"))
    assert r.status_code == 409


def test_entry_crud_and_cascade(client):
    create_owner(client)
    p = _make_product(client)
    r = client.post(f"/api/gmv/products/{p['id']}/entries", json=_entry())
    eid = r.json()["id"]
    r = client.put(f"/api/gmv/entries/{eid}", json=_entry(ad_cost=318000))
    assert r.status_code == 200
    assert r.json()["calc"]["roas"] == 1.67
    r = client.delete(f"/api/gmv/entries/{eid}")
    assert r.status_code == 204
    assert client.get(f"/api/gmv/products/{p['id']}/entries").json()["entries"] == []
    # xóa sản phẩm → cascade xóa dòng
    r = client.post(f"/api/gmv/products/{p['id']}/entries", json=_entry())
    assert r.status_code == 201
    client.delete(f"/api/gmv/products/{p['id']}")
    from app import database as db

    assert db.gmv_list_entries(p["id"]) == []


def test_entry_validation_errors(client):
    create_owner(client)
    p = _make_product(client)
    r = client.post(f"/api/gmv/products/{p['id']}/entries", json=_entry(views=-5))
    assert r.status_code == 422
    r = client.post(f"/api/gmv/products/{p['id']}/entries", json=_entry(date="not-a-date"))
    assert r.status_code == 422
    r = client.post("/api/gmv/products/999999/entries", json=_entry())
    assert r.status_code == 404


def test_server_recomputes_ignores_client_values(client):
    create_owner(client)
    p = _make_product(client)
    payload = _entry()
    payload.update({"ctr": 999, "roas": 123, "cir": -50})
    r = client.post(f"/api/gmv/products/{p['id']}/entries", json=payload)
    assert r.status_code == 201
    calc = r.json()["calc"]
    assert calc["ctr"] == 5.0
    assert calc["roas"] == 3.33
    assert calc["cpc"] == 3180
    assert calc["aov"] == 53000


def test_fail_closed_no_login(client):
    create_owner(client)
    logout(client)
    r = client.get("/gmv", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/login" in r.headers["location"]
    assert client.get("/api/gmv/products").status_code == 401
    assert client.post("/api/gmv/products", json={"name": "X"}).status_code == 401


def test_view_only_cannot_write(client):
    create_owner(client)
    prod = _make_product(client, "XÀ BÔNG NGHỆ")
    code = create_staff(client, "nv_gmv", perms=("sidebar_gmv",))
    logout(client)
    activate(client, "nv_gmv", code)

    assert client.get("/gmv").status_code == 200
    assert client.get("/api/gmv/products").status_code == 200
    assert client.get(f"/api/gmv/products/{prod['id']}/entries").status_code == 200
    assert client.post("/api/gmv/products", json={"name": "Y"}).status_code == 403
    assert client.post(f"/api/gmv/products/{prod['id']}/entries", json=_entry()).status_code == 403
    assert client.delete(f"/api/gmv/products/{prod['id']}").status_code == 403


def test_delete_needs_delete_perm(client):
    create_owner(client)
    code = create_staff(client, "nv_sua", perms=("sidebar_gmv", "can_add_edit_products"))
    logout(client)
    activate(client, "nv_sua", code)
    logout(client)
    login(client, "chushop", "matkhau123")
    prod = _make_product(client, "ĐEN TÓC")
    r = client.post(f"/api/gmv/products/{prod['id']}/entries", json=_entry())
    eid = r.json()["id"]
    logout(client)
    login(client, "nv_sua", "matkhau123")

    assert client.delete(f"/api/gmv/entries/{eid}").status_code == 403
    assert client.delete(f"/api/gmv/products/{prod['id']}").status_code == 403
    # nhưng được thêm/sửa
    assert client.post(f"/api/gmv/products/{prod['id']}/entries", json=_entry()).status_code in (
        200,
        201,
    )


def test_seed_only_when_empty(client):
    create_owner(client)
    from app import database as db

    assert db.gmv_seed_defaults() == 5
    names = [p["name"] for p in db.gmv_list_products()]
    assert names == GMV_SEED_PRODUCTS
    # không seed lại khi đã có dữ liệu
    assert db.gmv_seed_defaults() == 0
    assert len(db.gmv_list_products()) == 5
    # sheet trống, chưa có dòng dữ liệu
    assert db.gmv_list_entries(db.gmv_list_products()[0]["id"]) == []
    # thêm sản phẩm rồi seed → vẫn không seed
    db.gmv_create_product("SẢN PHẨM MỚI")
    assert db.gmv_seed_defaults() == 0
    assert len(db.gmv_list_products()) == 6
