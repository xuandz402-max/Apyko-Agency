"""Sidebar registry + grant store: 1 entry registry = 1 checkbox phân quyền
tự động, không còn cờ can_view_* tay; migration dịch cờ cũ thành grant."""

from conftest import activate, create_owner, create_staff, login, logout


def _staff(client, username, perms):
    code = create_staff(client, username, perms=perms)
    logout(client)
    activate(client, username, code)


def test_only_tiktok_grant_opens_only_tiktok(client):
    create_owner(client)
    _staff(client, "nv_tt_only", perms=("sidebar_tiktok",))
    r = client.get("/tiktok-onboard")
    assert r.status_code == 200
    # Các module khác (gác bằng grant riêng) đều chặn
    assert client.get("/gmv").status_code == 403
    assert client.get("/affiliate").status_code == 403
    assert client.get("/bao-cao").status_code == 403
    assert client.get("/dinh-gia").status_code == 403
    assert client.get("/cskh").status_code == 403
    # Sidebar: chỉ hiện mục TikTok Onboard trong nhóm module có grant riêng
    assert 'href="/tiktok-onboard"' in r.text
    assert 'href="/gmv"' not in r.text
    assert 'href="/affiliate"' not in r.text
    assert 'href="/bao-cao"' not in r.text
    assert 'href="/dinh-gia"' not in r.text
    assert 'href="/cskh"' not in r.text


def test_only_accounts_grant_opens_vault_not_login_admin(client):
    create_owner(client)
    _staff(client, "nv_kho", perms=("sidebar_accounts",))
    assert client.get("/accounts?tab=shop").status_code == 200
    assert client.get("/accounts?tab=noi-bo").status_code == 200
    assert client.get("/accounts?tab=ban-giao").status_code == 200
    # Tab đăng nhập & phân quyền vẫn chỉ dành cho chủ sở hữu
    assert client.get("/accounts?tab=dang-nhap").status_code == 403
    assert client.get("/accounts").status_code == 403
    # Sidebar có mục Quản lý tài khoản
    r = client.get("/accounts?tab=shop")
    assert 'href="/accounts?tab=shop"' in r.text


def test_products_grant_no_longer_unlocks_other_modules(client):
    create_owner(client)
    _staff(client, "nv_sp_only", perms=("sidebar_products",))
    assert client.get("/products").status_code == 200
    assert client.get("/gmv").status_code == 403
    assert client.get("/affiliate").status_code == 403
    assert client.get("/bao-cao").status_code == 403
    assert client.get("/tiktok-onboard").status_code == 403
    assert client.get("/accounts?tab=shop").status_code == 403


def test_migration_translates_old_flags_to_grants(client):
    """Mô phỏng DB trước nâng cấp (có cờ cũ, chưa có bảng grant): init_db
    phải dịch cờ thành grant rows — products -> products + analysis,
    checklist/notifications cho mọi user, chủ sở hữu đủ mọi grant."""
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
    # Mô phỏng DB trước nâng cấp: chưa có bảng grant, chưa có cờ migration
    with db.get_conn() as conn:
        conn.execute("DROP TABLE IF EXISTS user_sidebar_perms")
        conn.execute(
            "DELETE FROM app_meta WHERE key = 'sidebar_grants_migrated'"
        )
    db.init_db()

    yes = db.sidebar_grants(uid_yes)
    assert "products" in yes and "analysis" in yes
    assert "gmv" not in yes and "tiktok" not in yes
    # checklist/notifications từng mở cho mọi user -> ai cũng có
    assert "checklist" in yes and "notifications" in yes
    no = db.sidebar_grants(uid_no)
    assert "products" not in no and "analysis" not in no
    assert "checklist" in no and "notifications" in no
    # Chủ sở hữu: đủ mọi grant sau migration
    owner = db.get_user_by_username("chushop")
    from app import sidebar as sb

    assert db.sidebar_grants(owner["id"]) == set(sb.all_ids())
    # Chạy lại migration: không nhân đôi, không đổi grant
    db.init_db()
    assert db.sidebar_grants(uid_yes) == yes


def test_create_form_has_all_sidebar_labels(client):
    create_owner(client)
    r = client.get("/accounts")
    assert r.status_code == 200
    from app import sidebar as sb

    for item in sb.SIDEBAR_ITEMS:
        assert f'name="sidebar_{item["id"]}"' in r.text, item["id"]
        assert f"Xem {item['label']}" in r.text, item["label"]


def test_perms_update_persists_new_grant(client):
    create_owner(client)
    from app import database as db

    code = create_staff(client, "nv_moi", perms=())
    target = db.get_user_by_username("nv_moi")
    assert db.sidebar_grants(target["id"]) == set()
    r = client.post(
        f"/accounts/{target['id']}/perms",
        data={"sidebar_gmv": "on"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert db.sidebar_grants(target["id"]) == {"gmv"}
    # Và grant mới có hiệu lực thật khi nhân viên đăng nhập
    logout(client)
    activate(client, "nv_moi", code)
    assert client.get("/gmv").status_code == 200
    assert client.get("/affiliate").status_code == 403


def test_home_redirects_to_first_permitted_page(client):
    """Trang chủ Dashboard đã bỏ: / chuyển thẳng tới trang đầu tiên có quyền."""
    create_owner(client)
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/ceo"  # chủ shop -> Dashboard CEO

    code = create_staff(client, "nv_home_sp", perms=("sidebar_products",))
    logout(client)
    activate(client, "nv_home_sp", code)
    r = client.get("/", follow_redirects=False)
    assert r.headers["location"] == "/products"

    logout(client)
    login(client, "chushop", "matkhau123")
    code2 = create_staff(client, "nv_home_tt", perms=("sidebar_tiktok",))
    logout(client)
    activate(client, "nv_home_tt", code2)
    r = client.get("/", follow_redirects=False)
    assert r.headers["location"] == "/tiktok-onboard"
    # Sidebar không còn mục Dashboard và Thêm sản phẩm
    page = client.get("/tiktok-onboard")
    assert "📊 Dashboard" not in page.text
    assert 'href="/products/new" class="nav-item' not in page.text


def test_registry_entry_automatically_gets_permission_checkbox(client, monkeypatch):
    """BẰNG CHỨNG TÍNH TỰ ĐỘNG: chỉ thêm 1 entry vào registry (không sửa
    code nào khác) thì form phân quyền đã có checkbox của nó, cổng grant
    tôn trọng grant cho nó, và sidebar hiện nó khi được cấp."""
    from app import sidebar as sb

    fake = {"id": "fake_new", "label": "Mục Mới Thử", "route": "/fake",
            "icon": "🧪", "icon_img": "", "active": "fake_new", "default": False}
    monkeypatch.setattr(sb, "SIDEBAR_ITEMS", [*sb.SIDEBAR_ITEMS, fake])
    create_owner(client)
    # Form phân quyền tự có checkbox mới
    r = client.get("/accounts")
    assert 'name="sidebar_fake_new"' in r.text
    assert "Xem Mục Mới Thử" in r.text
    # Cổng grant: chưa cấp -> không có quyền; cấp -> có quyền + hiện sidebar
    from app import database as db

    create_staff(client, "nv_fake", perms=())
    target = db.get_user_by_username("nv_fake")
    assert not sb.has_grant(
        {"is_owner": 0, "sidebar_grants": db.sidebar_grants(target["id"])},
        "fake_new",
    )
    db.sidebar_set_grants(target["id"], ["fake_new"])
    user = {"is_owner": 0, "sidebar_grants": db.sidebar_grants(target["id"])}
    assert sb.has_grant(user, "fake_new")
    nav = sb.build_nav(user, 0)
    assert any(it["route"] == "/fake" for it in nav)
