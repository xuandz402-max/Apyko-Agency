"""Kho tài khoản (vault) trong trang Quản lý tài khoản: tab shop / nội bộ /
bàn giao — quyền xem, che mật khẩu, cổng sửa/xóa, tìm kiếm và bản bàn giao."""

from conftest import activate, create_owner, create_staff, login, logout

SECRET = "MatKhauSieuBiMat123"
SHOP_SECRET = "ShopPw!123"


def _create_shop(client, **over):
    data = {
        "category": "shop",
        "kind": "Shopee",
        "label": "APYKO Official",
        "account_holder": "Tài khoản chính",
        "username": "apyko.shop",
        "password": SHOP_SECRET,
        "url": "https://seller.shopee.vn",
        "assignee": "Lan Anh",
        "note": "Shop chính",
    }
    data.update(over)
    return client.post("/accounts/vault/create", data=data, follow_redirects=False)


def _create_noibo(client, **over):
    data = {
        "category": "noi_bo",
        "kind": "Shopee",
        "label": "Shopee shop chính",
        "username": "apyko.shop",
        "password": SECRET,
        "url": "https://seller.shopee.vn",
        "assignee": "Lan Anh",
        "bank_name": "",
        "account_number": "",
        "account_holder": "",
        "note": "",
    }
    data.update(over)
    return client.post("/accounts/vault/create", data=data, follow_redirects=False)


def _login_staff(client, username, perms):
    code = create_staff(client, username, perms=perms)
    logout(client)
    activate(client, username, code)


def test_vault_tabs_require_view_perm(client):
    create_owner(client)
    _login_staff(client, "nv_khongquyen", perms=())
    for tab in ("shop", "noi-bo", "ban-giao"):
        r = client.get(f"/accounts?tab={tab}", follow_redirects=False)
        assert r.status_code == 403, tab


def test_viewer_opens_vault_tabs_but_not_login_admin(client):
    create_owner(client)
    _login_staff(client, "nv_xem", perms=("can_view_products",))
    for tab in ("shop", "noi-bo", "ban-giao"):
        assert client.get(f"/accounts?tab={tab}").status_code == 200, tab
    r = client.get("/accounts?tab=dang-nhap", follow_redirects=False)
    assert r.status_code == 403
    # /accounts không có ?tab= vẫn là trang cũ: nhân sự bị chặn như trước
    r = client.get("/accounts", follow_redirects=False)
    assert r.status_code == 403


def test_owner_bare_accounts_still_login_admin(client):
    create_owner(client)
    r = client.get("/accounts")
    assert r.status_code == 200
    assert "Danh sách tài khoản" in r.text
    assert "chushop" in r.text
    # Thanh tab của hub vẫn hiện cho chủ sở hữu
    assert "Tài khoản shop" in r.text
    assert "Đăng nhập" in r.text


def test_password_not_in_html_for_viewer(client):
    create_owner(client)
    assert _create_noibo(client).status_code == 303
    assert _create_shop(client).status_code == 303
    # Chủ sở hữu thấy mật khẩu thật ở cả 2 tab
    assert SECRET in client.get("/accounts?tab=noi-bo").text
    assert SHOP_SECRET in client.get("/accounts?tab=shop").text
    _login_staff(client, "nv_xem", perms=("can_view_products",))
    for tab in ("noi-bo", "shop"):
        r = client.get(f"/accounts?tab={tab}")
        assert r.status_code == 200
        assert SECRET not in r.text
        assert SHOP_SECRET not in r.text
        assert "••••••" in r.text
    # Ở tab bàn giao: mật khẩu bị thay bằng dòng liên hệ quản lý
    r = client.get("/accounts", params={"tab": "ban-giao", "assignee": "Lan Anh"})
    assert r.status_code == 200
    assert SECRET not in r.text
    assert SHOP_SECRET not in r.text
    assert "(liên hệ quản lý để nhận)" in r.text


def test_editor_sees_password(client):
    create_owner(client)
    assert _create_noibo(client).status_code == 303
    _login_staff(
        client, "nv_sua", perms=("can_view_products", "can_add_edit_products")
    )
    r = client.get("/accounts?tab=noi-bo")
    assert r.status_code == 200
    assert SECRET in r.text


def test_vault_post_permission_gates(client):
    from app import database as db

    create_owner(client)
    assert _create_noibo(client).status_code == 303
    item = db.vault_list("noi_bo")[0]
    upd = {
        "kind": "Shopee",
        "label": "Shopee shop phụ",
        "username": "apyko.shop",
        "password": SECRET,
        "url": "",
        "assignee": "Lan Anh",
        "bank_name": "",
        "account_number": "",
        "account_holder": "",
        "note": "",
    }
    # Người chỉ xem: không tạo / sửa / xóa được
    _login_staff(client, "nv_xem", perms=("can_view_products",))
    assert _create_noibo(client).status_code == 403
    r = client.post(f"/accounts/vault/{item['id']}/update", data=upd)
    assert r.status_code == 403
    r = client.post(f"/accounts/vault/{item['id']}/delete")
    assert r.status_code == 403
    # Người sửa: tạo + sửa được, xóa thì không (về tài khoản chủ để tạo nhân sự)
    logout(client)
    login(client, "chushop", "matkhau123")
    _login_staff(
        client, "nv_sua", perms=("can_view_products", "can_add_edit_products")
    )
    assert _create_shop(client).status_code == 303
    r = client.post(
        f"/accounts/vault/{item['id']}/update", data=upd, follow_redirects=False
    )
    assert r.status_code == 303
    assert db.vault_get(item["id"])["label"] == "Shopee shop phụ"
    r = client.post(f"/accounts/vault/{item['id']}/delete")
    assert r.status_code == 403
    # Chủ sở hữu: xóa được
    logout(client)
    login(client, "chushop", "matkhau123")
    r = client.post(f"/accounts/vault/{item['id']}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert db.vault_get(item["id"]) is None


def test_shop_create_and_search(client):
    create_owner(client)
    assert _create_shop(client).status_code == 303
    r = client.get("/accounts?tab=shop")
    assert r.status_code == 200
    assert "APYKO Official" in r.text
    assert "apyko.shop" in r.text
    assert "Tài khoản chính" in r.text
    # Text chép nhanh: shop + đăng nhập + mật khẩu (chủ sở hữu xem được)
    assert (
        f"Shop: APYKO Official (Shopee)\nTài khoản: apyko.shop\n"
        f"Mật khẩu: {SHOP_SECRET}"
    ) in r.text
    # Tìm theo tên đăng nhập (khẳng định theo dòng dữ liệu trong bảng,
    # tránh trùng chữ ví dụ trong placeholder của form thêm mới)
    r = client.get("/accounts", params={"tab": "shop", "q": "apyko.shop"})
    assert "<strong>APYKO Official</strong>" in r.text
    r = client.get("/accounts", params={"tab": "shop", "q": "khong-co-dau-nay"})
    assert "<strong>APYKO Official</strong>" not in r.text


def test_handover_groups_items_by_assignee(client):
    create_owner(client)
    assert _create_noibo(client).status_code == 303
    assert _create_noibo(
        client,
        kind="Email",
        label="Email hỗ trợ",
        username="hotro@apyko.vn",
        password="EmailPw456",
        url="",
    ).status_code == 303
    assert _create_shop(client).status_code == 303
    assert _create_noibo(
        client,
        label="TK của người khác",
        username="minh@apyko.vn",
        password="PwKhac789",
        assignee="Minh",
    ).status_code == 303

    r = client.get("/accounts", params={"tab": "ban-giao", "assignee": "Lan Anh"})
    assert r.status_code == 200
    assert "Shopee shop chính" in r.text
    assert "Email hỗ trợ" in r.text
    assert "APYKO Official" in r.text
    assert "TK của người khác" not in r.text
    # Bản chép bàn giao (chủ sở hữu): đủ 2 mục + mật khẩu thật
    assert "THÔNG TIN BÀN GIAO TÀI KHOẢN" in r.text
    assert "Nhân sự: Lan Anh" in r.text
    assert "A. TÀI KHOẢN NỘI BỘ" in r.text
    assert "B. TÀI KHOẢN SHOP PHỤ TRÁCH" in r.text
    assert f"Mật khẩu: {SECRET}" in r.text
    assert f"Mật khẩu: {SHOP_SECRET}" in r.text
    assert "Loại tài khoản: Tài khoản chính" in r.text
