"""Tính năng pro: Sao lưu & Khôi phục, KPI nhân viên, Mẫu trả lời CSKH."""

import os

import pytest
from conftest import activate, create_owner, create_staff, logout


def _db():
    from app import database as db

    return db


def _backup():
    from app import backup

    return backup


def _cl():
    from app import checklist

    return checklist


# ------------------------------ sao lưu & khôi phục ---------------------------


def test_backup_create_list_and_page(client):
    create_owner(client)
    backup = _backup()
    name = backup.create_backup("manual")
    assert name is not None and name.endswith("-manual.db")
    names = [b["name"] for b in backup.list_backups()]
    assert name in names
    r = client.get("/sao-luu")
    assert r.status_code == 200
    assert name in r.text
    assert "SQLite local" in r.text
    # Nút "Sao lưu ngay" tạo thêm được 1 bản qua route
    r = client.post("/sao-luu/tao", follow_redirects=False)
    assert r.status_code == 303


def test_backup_download_route(client):
    create_owner(client)
    backup = _backup()
    name = backup.create_backup("manual")
    r = client.get(f"/sao-luu/tai/{name}")
    assert r.status_code == 200
    assert len(r.content) > 0
    # Tên không đúng định dạng -> 404, không lộ file
    assert client.get("/sao-luu/tai/filela.db").status_code == 404


def test_backup_prune_keeps_30(client):
    create_owner(client)
    backup = _backup()
    folder = backup.backups_dir()
    os.makedirs(folder, exist_ok=True)
    for i in range(31):
        with open(os.path.join(folder, f"apyko-20260101-0000{i:02d}-auto.db"), "wb") as f:
            f.write(b"dummy")
    backup.create_backup("manual")
    names = [b["name"] for b in backup.list_backups()]
    assert len(names) == 30
    assert "apyko-20260101-000000-auto.db" not in names
    assert "apyko-20260101-000001-auto.db" not in names


def test_restore_roundtrip(client):
    create_owner(client)
    db, backup = _db(), _backup()
    name = backup.create_backup("manual")
    # Ghi thêm dữ liệu SAU khi sao lưu
    db.daily_upsert(
        {
            "date": "2026-10-19",
            "rev_product": 1000000,
            "rev_live": 0,
            "rev_video": 0,
            "rev_aff_link": 0,
            "rev_affiliate": 0,
            "ad_gmv": 0,
            "ad_cost": 0,
            "aov": 0,
            "conv_rate": 0,
            "note": "",
        },
        "test",
    )
    assert len(db.daily_list()) == 1
    r = client.post(f"/sao-luu/khoi-phuc/{name}", follow_redirects=False)
    assert r.status_code == 303
    assert "restored=1" in r.headers["location"]
    # Dữ liệu quay về trạng thái lúc sao lưu + có bản pre-restore
    assert db.daily_list() == []
    names = [b["name"] for b in backup.list_backups()]
    assert any(n.endswith("-pre-restore.db") for n in names)
    r = client.get("/sao-luu?restored=1")
    assert r.status_code == 200
    assert "tắt app và mở lại" in r.text


def test_restore_path_traversal_blocked(client):
    create_owner(client)
    backup = _backup()
    with pytest.raises(ValueError):
        backup.restore_backup("../t.db")
    with pytest.raises(ValueError):
        backup.restore_backup("..\\t.db")
    with pytest.raises(ValueError):
        backup.backup_path("apyko-20260101-000000-auto.db")  # chưa tồn tại
    # Route: tên bậy -> chuyển về trang kèm lỗi, không khôi phục gì
    r = client.post("/sao-luu/khoi-phuc/filela.db", follow_redirects=False)
    assert r.status_code == 303
    assert "err=" in r.headers["location"]


def test_maybe_daily_backup_once_per_day(client):
    create_owner(client)
    backup = _backup()
    first = backup.maybe_daily_backup()
    second = backup.maybe_daily_backup()
    assert first is not None and first.endswith("-auto.db")
    assert second is None
    autos = [b for b in backup.list_backups() if b["name"].endswith("-auto.db")]
    assert len(autos) == 1


def test_backup_delete_route_and_safety(client):
    create_owner(client)
    backup = _backup()
    name = backup.create_backup("manual")
    assert name in [b["name"] for b in backup.list_backups()]
    r = client.post(f"/sao-luu/xoa/{name}", follow_redirects=False)
    assert r.status_code == 303
    assert "msg=" in r.headers["location"]
    assert name not in [b["name"] for b in backup.list_backups()]
    # Xoá tên không tồn tại / tên bậy -> quay về trang kèm lỗi, không crash
    r = client.post("/sao-luu/xoa/apyko-20260101-000000-auto.db", follow_redirects=False)
    assert r.status_code == 303
    assert "err=" in r.headers["location"]
    with pytest.raises(ValueError):
        backup.delete_backup("../t.db")


def test_backup_delete_forbidden_for_staff(client):
    create_owner(client)
    backup = _backup()
    name = backup.create_backup("manual")
    code = create_staff(client, "nv_xoa", perms=("can_view_products",))
    logout(client)
    activate(client, "nv_xoa", code)
    assert client.post(f"/sao-luu/xoa/{name}").status_code == 403
    # File vẫn còn nguyên
    assert name in [b["name"] for b in backup.list_backups()]


def test_backup_forbidden_for_staff_and_menu_hidden(client):
    create_owner(client)
    code = create_staff(client, "nv_thuong", perms=("can_view_products",))
    logout(client)
    activate(client, "nv_thuong", code)
    assert client.get("/sao-luu").status_code == 403
    assert client.post("/sao-luu/tao").status_code == 403
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/sao-luu"' not in r.text
    assert 'href="/kpi"' not in r.text


# ------------------------------ KPI nhân viên ---------------------------------

CUR_FROM, CUR_TO = "2026-10-05", "2026-10-06"
KPI_QS = f"from={CUR_FROM}&to={CUR_TO}"


def _complete(db, date_str, user_id, count):
    items = db.cl_item_list(date_str, assignee_id=user_id)
    for item in items[:count]:
        db.cl_item_update(item["id"], {"status": "done", "completed_by": "test"})


def _seed_kpi(client):
    """2 nhân viên x 2 mẫu việc; 2 ngày kỳ này + 2 ngày kỳ trước liền kề.

    Kỳ này: A xong 4/4 (100%), B xong 1/4 (25%).
    Kỳ trước: A xong 2/4 (50%), B xong 3/4 (75%).
    -> Delta: A +50.0 điểm %, B -50.0 điểm %; hạng A trên B.
    """
    db, cl = _db(), _cl()
    # Tắt 20 mẫu mặc định để số liệu chỉ gồm mẫu test
    for t in db.cl_template_list():
        db.cl_template_update(t["id"], {"is_active": 0})
    users = {u["username"]: u["id"] for u in db.list_users()}
    for uname in ("nv_a", "nv_b"):
        for i in range(2):
            db.cl_template_create(
                {
                    "group_name": "Test",
                    "title": f"Việc {uname} {i}",
                    "sort": 10 + i,
                    "due_time": "09:00",
                    "assignee_id": users[uname],
                    "shop_id": None,
                    "is_active": 1,
                }
            )
    for day in ("2026-10-03", "2026-10-04", CUR_FROM, CUR_TO):
        cl.generate_for_date(day)
    a, b = users["nv_a"], users["nv_b"]
    for day in (CUR_FROM, CUR_TO):
        _complete(db, day, a, 2)
    _complete(db, CUR_FROM, b, 1)
    _complete(db, "2026-10-03", a, 2)
    _complete(db, "2026-10-04", b, 2)
    _complete(db, "2026-10-03", b, 1)


def _make_kpi_staff(client):
    create_staff(client, "nv_a", perms=("can_view_products",))
    create_staff(client, "nv_b", perms=("can_view_products",))


def test_kpi_ranking_and_delta(client):
    create_owner(client)
    _make_kpi_staff(client)
    _seed_kpi(client)
    r = client.get(f"/kpi?{KPI_QS}")
    assert r.status_code == 200
    html = r.text
    assert "100.0%" in html
    assert "25.0%" in html
    assert "+50.0 điểm %" in html
    assert "-50.0 điểm %" in html
    assert "delta-up" in html and "delta-down" in html
    # Hạng: A (100%) đứng trên B (25%)
    assert html.index("nv_a") < html.index("nv_b")
    # Hàng tổng team: 5/8 xong -> 62.5%
    assert "TOÀN TEAM" in html
    assert "62.5%" in html


def test_kpi_csv_export(client):
    create_owner(client)
    _make_kpi_staff(client)
    _seed_kpi(client)
    r = client.get(f"/kpi/export?{KPI_QS}")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    text = r.content.decode("utf-8-sig")
    assert "Nhân viên" in text
    assert "nv_a" in text and "100.0" in text
    assert "TOÀN TEAM" in text


def test_kpi_forbidden_for_plain_staff(client):
    create_owner(client)
    code = create_staff(client, "nv_thuong", perms=("can_view_products",))
    logout(client)
    activate(client, "nv_thuong", code)
    assert client.get("/kpi").status_code == 403
    assert client.get("/kpi/export").status_code == 403


# ------------------------------ mẫu trả lời CSKH ------------------------------


def test_cskh_seed_and_page(client):
    create_owner(client)
    db = _db()
    items = db.cskh_list()
    assert len(items) == 6
    r = client.get("/cskh")
    assert r.status_code == 200
    assert "Xin đánh giá 5 sao" in r.text
    assert "Hẹn giao lại" in r.text
    assert "cskh-copy" in r.text  # nút Sao chép (JS phía client)
    assert "Sao chép" in r.text
    assert "{ten_khach}" in r.text  # biến giữ chỗ còn nguyên để nhân viên tự thay


def test_cskh_search_filters(client):
    create_owner(client)
    r = client.get("/cskh", params={"q": "đánh giá"})
    assert r.status_code == 200
    assert "Xin đánh giá 5 sao" in r.text
    assert "Hẹn giao lại" not in r.text


def test_cskh_create_edit_delete_as_owner(client):
    create_owner(client)
    db = _db()
    r = client.post(
        "/cskh",
        data={
            "title": "Mẫu test mới",
            "category": "Test",
            "content": "Nội dung cho đơn {ma_don}",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    found = [i for i in db.cskh_list() if i["title"] == "Mẫu test mới"]
    assert len(found) == 1
    item_id = found[0]["id"]
    r = client.post(
        f"/cskh/{item_id}/edit",
        data={"title": "Mẫu test đã sửa", "category": "Test", "content": "Nội dung mới"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert db.cskh_get(item_id)["title"] == "Mẫu test đã sửa"
    r = client.post(f"/cskh/{item_id}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert db.cskh_get(item_id) is None


def test_cskh_permissions(client):
    create_owner(client)
    db = _db()
    seed_id = db.cskh_list()[0]["id"]
    code_view = create_staff(
        client, "nv_xem", perms=("can_view_products", "can_view_cskh")
    )
    code_edit = create_staff(
        client,
        "nv_sua",
        perms=("can_view_products", "can_add_edit_products", "can_view_cskh"),
    )
    # Nhân viên chỉ xem: xem được trang nhưng thêm/xóa đều 403
    logout(client)
    activate(client, "nv_xem", code_view)
    assert client.get("/cskh").status_code == 200
    r = client.post(
        "/cskh",
        data={"title": "X", "category": "", "content": "Y"},
        follow_redirects=False,
    )
    assert r.status_code == 403
    assert client.post(f"/cskh/{seed_id}/delete", follow_redirects=False).status_code == 403
    # Nhân viên có quyền sửa: thêm được, nhưng xóa vẫn 403 (thiếu quyền xóa)
    logout(client)
    activate(client, "nv_sua", code_edit)
    r = client.post(
        "/cskh",
        data={"title": "Mẫu của nv_sua", "category": "", "content": "Nội dung"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert client.post(f"/cskh/{seed_id}/delete", follow_redirects=False).status_code == 403
