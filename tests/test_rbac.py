"""Phân quyền: từng quyền bị chặn đúng chỗ (fail-closed), cả HTML lẫn API."""

import pytest
from conftest import activate, create_owner, create_staff, login, logout, product_payload


@pytest.fixture()
def staff_view_only(client):
    """Nhân sự chỉ có quyền xem sản phẩm + xem Uni."""
    create_owner(client)
    code = create_staff(client, "nv_xem", perms=("can_view_products", "can_view_uni"))
    logout(client)
    activate(client, "nv_xem", code)
    return client


def test_view_only_cannot_create_product_page(staff_view_only):
    r = staff_view_only.get("/products/new", follow_redirects=False)
    assert r.status_code == 403


def test_view_only_cannot_create_product_api(staff_view_only):
    r = staff_view_only.post("/api/products", json=product_payload())
    assert r.status_code == 403


def test_view_only_can_list_products(staff_view_only):
    assert staff_view_only.get("/products").status_code == 200
    assert staff_view_only.get("/api/products").status_code == 200


def test_no_uni_perm_blocked(staff_view_only):
    # Thu hồi quyền Uni rồi thử lại
    staff_view_only.get("/logout")
    login(staff_view_only, "chushop", "matkhau123")
    from app import database as db

    target = db.get_user_by_username("nv_xem")
    staff_view_only.post(f"/accounts/{target['id']}/perms", data={})  # bỏ hết quyền
    staff_view_only.get("/logout")
    login(staff_view_only, "nv_xem", "matkhau123")
    assert staff_view_only.get("/uni", follow_redirects=False).status_code == 403
    assert staff_view_only.get("/api/uni").status_code == 403


def test_non_owner_cannot_manage_accounts(staff_view_only):
    r = staff_view_only.get("/accounts", follow_redirects=False)
    assert r.status_code == 403
    r = staff_view_only.post("/accounts/create", data={"username": "x"})
    assert r.status_code == 403
    r = staff_view_only.get("/api/accounts")
    assert r.status_code == 403


def test_owner_can_manage_accounts(client):
    create_owner(client)
    r = client.get("/accounts")
    assert r.status_code == 200
    assert "chushop" in r.text
    r = client.get("/api/accounts")
    assert r.status_code == 200
    assert any(u["username"] == "chushop" for u in r.json()["users"])
    # password_hash không bao giờ lộ qua API
    assert all("password_hash" not in u for u in r.json()["users"])


def test_delete_requires_delete_perm(client):
    create_owner(client)
    code = create_staff(client, "nv_sua", perms=("can_view_products", "can_add_edit_products"))
    # Owner tạo 1 sản phẩm
    r = client.post("/api/products", json=product_payload())
    pid = r.json()["product"]["id"]
    logout(client)
    activate(client, "nv_sua", code)
    # Có quyền sửa nhưng không có quyền xóa → 403
    assert client.delete(f"/api/products/{pid}").status_code == 403
    r = client.post(f"/products/{pid}/delete", follow_redirects=False)
    assert r.status_code == 403
    # Owner cấp thêm quyền xóa → được
    client.get("/logout")
    login(client, "chushop", "matkhau123")
    from app import database as db

    target = db.get_user_by_username("nv_sua")
    client.post(
        f"/accounts/{target['id']}/perms",
        data={
            "can_view_products": "on",
            "can_add_edit_products": "on",
            "can_delete_products": "on",
        },
    )
    client.get("/logout")
    login(client, "nv_sua", "matkhau123")
    assert client.delete(f"/api/products/{pid}").status_code == 204
