"""Quyền xem RIÊNG từng mục sidebar: mỗi module một cờ can_view_* riêng,
không còn mượn can_view_products; migration backfill giữ quyền cho user cũ."""

from conftest import activate, create_owner, create_staff, login, logout

NEW_VIEW_FLAGS = (
    "can_view_daily",
    "can_view_pricing",
    "can_view_gmv",
    "can_view_affiliate",
    "can_view_tiktok",
    "can_view_cskh",
    "can_view_accounts",
)

NEW_LABELS = (
    "Xem Báo cáo ngày",
    "Xem Sản phẩm",
    "Xem Định giá sản phẩm",
    "Xem GMV Max Shopee",
    "Xem Affiliate",
    "Xem TikTok Onboard",
    "Xem Apyko Uni",
    "Xem Mẫu CSKH",
    "Xem Quản lý tài khoản (kho)",
)


def _staff(client, username, perms):
    code = create_staff(client, username, perms=perms)
    logout(client)
    activate(client, username, code)


def test_only_tiktok_flag_opens_only_tiktok(client):
    create_owner(client)
    _staff(client, "nv_tt_only", perms=("can_view_tiktok",))
    r = client.get("/tiktok-onboard")
    assert r.status_code == 200
    # Các module khác (gác bằng cờ riêng) đều chặn
    assert client.get("/gmv").status_code == 403
    assert client.get("/affiliate").status_code == 403
    assert client.get("/bao-cao").status_code == 403
    assert client.get("/dinh-gia").status_code == 403
    assert client.get("/cskh").status_code == 403
    # Sidebar: chỉ hiện mục TikTok Onboard trong nhóm module có cờ riêng
    assert 'href="/tiktok-onboard"' in r.text
    assert 'href="/gmv"' not in r.text
    assert 'href="/affiliate"' not in r.text
    assert 'href="/bao-cao"' not in r.text
    assert 'href="/dinh-gia"' not in r.text
    assert 'href="/cskh"' not in r.text


def test_only_accounts_flag_opens_vault_not_login_admin(client):
    create_owner(client)
    _staff(client, "nv_kho", perms=("can_view_accounts",))
    assert client.get("/accounts?tab=shop").status_code == 200
    assert client.get("/accounts?tab=noi-bo").status_code == 200
    assert client.get("/accounts?tab=ban-giao").status_code == 200
    # Tab đăng nhập & phân quyền vẫn chỉ dành cho chủ sở hữu
    assert client.get("/accounts?tab=dang-nhap").status_code == 403
    assert client.get("/accounts").status_code == 403
    # Sidebar có mục Quản lý tài khoản
    r = client.get("/accounts?tab=shop")
    assert 'href="/accounts?tab=shop"' in r.text


def test_products_flag_no_longer_unlocks_other_modules(client):
    create_owner(client)
    _staff(client, "nv_sp_only", perms=("can_view_products",))
    assert client.get("/products").status_code == 200
    assert client.get("/gmv").status_code == 403
    assert client.get("/affiliate").status_code == 403
    assert client.get("/bao-cao").status_code == 403
    assert client.get("/tiktok-onboard").status_code == 403
    assert client.get("/accounts?tab=shop").status_code == 403


def test_migration_backfills_view_flags_from_products(client):
    """DB cũ (chưa có các cột can_view_* mới): init_db phải thêm cột và
    backfill = can_view_products cho 5 cờ module, = 1 cho can_view_cskh và
    can_view_pricing (2 mục vốn mở cho mọi user đã đăng nhập)."""
    create_owner(client)
    from app import database as db

    uid_yes = db.create_user(
        {
            "username": "user_cu_co_sp",
            "display_name": "Cũ có SP",
            "password_hash": "x",
            "is_active": 1,
            "can_view_products": 1,
        }
    )
    uid_no = db.create_user(
        {
            "username": "user_cu_khong_sp",
            "display_name": "Cũ không SP",
            "password_hash": "x",
            "is_active": 1,
            "can_view_products": 0,
        }
    )
    # Mô phỏng DB trước nâng cấp: bỏ hẳn các cột mới
    with db.get_conn() as conn:
        for col in NEW_VIEW_FLAGS:
            conn.execute(f"ALTER TABLE users DROP COLUMN {col}")
    db.init_db()

    yes = db.get_user(uid_yes)
    for col in NEW_VIEW_FLAGS:
        assert yes[col] == 1, col
    no = db.get_user(uid_no)
    for col in NEW_VIEW_FLAGS:
        expected = 1 if col in ("can_view_cskh", "can_view_pricing") else 0
        assert no[col] == expected, col
    # Chủ sở hữu: mọi cờ đều 1 sau migration
    owner = db.get_user_by_username("chushop")
    for col in NEW_VIEW_FLAGS:
        assert owner[col] == 1, col


def test_create_form_has_all_sidebar_perm_labels(client):
    create_owner(client)
    r = client.get("/accounts")
    assert r.status_code == 200
    for label in NEW_LABELS:
        assert label in r.text, label


def test_perms_update_persists_new_flag(client):
    create_owner(client)
    from app import database as db

    code = create_staff(client, "nv_moi", perms=())
    target = db.get_user_by_username("nv_moi")
    assert target["can_view_gmv"] == 0
    r = client.post(
        f"/accounts/{target['id']}/perms",
        data={"can_view_gmv": "on"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    updated = db.get_user(target["id"])
    assert updated["can_view_gmv"] == 1
    # Form phân quyền thay toàn bộ: cờ không tick thì về 0
    assert updated["can_view_products"] == 0
    # Và quyền mới có hiệu lực thật khi nhân viên đăng nhập
    logout(client)
    activate(client, "nv_moi", code)
    assert client.get("/gmv").status_code == 200
    assert client.get("/affiliate").status_code == 403
    # Nhân viên mới tạo chỉ có đúng các cờ được tick lúc tạo (không mirror)
    created = db.get_user_by_username("nv_moi")
    assert created["can_view_tiktok"] == 0
    assert created["can_view_daily"] == 0


def test_home_redirects_to_first_permitted_page(client):
    """Trang chủ Dashboard đã bỏ: / chuyển thẳng tới trang đầu tiên có quyền."""
    create_owner(client)
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/ceo"  # chủ shop -> Dashboard CEO

    code = create_staff(client, "nv_home_sp", perms=("can_view_products",))
    logout(client)
    activate(client, "nv_home_sp", code)
    r = client.get("/", follow_redirects=False)
    assert r.headers["location"] == "/products"

    logout(client)
    login(client, "chushop", "matkhau123")
    code2 = create_staff(client, "nv_home_tt", perms=("can_view_tiktok",))
    logout(client)
    activate(client, "nv_home_tt", code2)
    r = client.get("/", follow_redirects=False)
    assert r.headers["location"] == "/tiktok-onboard"
    # Sidebar không còn mục Dashboard và Thêm sản phẩm
    page = client.get("/tiktok-onboard")
    assert "📊 Dashboard" not in page.text
    assert 'href="/products/new" class="nav-item' not in page.text
