"""Dashboard CEO: quyền xem, trạng thái chưa có dữ liệu, tổng hợp số thật."""

from conftest import activate, create_owner, create_staff, logout


def _db():
    from app import database as db

    return db


def _cl():
    from app import checklist

    return checklist


def _ceo():
    from app import ceo

    return ceo


def _report(db, date, total, ad_gmv, ad_cost):
    clean = {
        "date": date,
        "rev_product": total,
        "rev_live": 0,
        "rev_video": 0,
        "rev_aff_link": 0,
        "rev_affiliate": 0,
        "ad_gmv": ad_gmv,
        "ad_cost": ad_cost,
        "aov": 0,
        "conv_rate": 0,
        "note": "",
    }
    db.daily_upsert(clean, "test")


# --- quyền xem ---------------------------------------------------------------


def test_owner_can_open_ceo_without_data(client):
    create_owner(client)
    r = client.get("/ceo")
    assert r.status_code == 200
    html = r.text
    assert "Dashboard CEO" in html
    # Chưa nhập Báo cáo ngày hôm nay → thẻ hiển thị "No Data", không crash
    assert "No Data" in html
    assert "Chưa nhập Báo cáo ngày hôm nay" in html
    # Bảng 7 ngày vẫn render đủ 7 dòng (thiếu dữ liệu → "—")
    assert "Doanh thu 7 ngày gần nhất" in html
    assert "Nhân viên hôm nay" in html


def test_staff_without_leader_flag_blocked(client):
    create_owner(client)
    code = create_staff(client, "nv_thuong", perms=("sidebar_products",))
    logout(client)
    activate(client, "nv_thuong", code)
    r = client.get("/ceo")
    assert r.status_code == 403
    # Sidebar của nhân viên thường không có mục CEO
    assert "Dashboard CEO" not in client.get("/checklist").text


def test_staff_with_leader_flag_can_open(client):
    create_owner(client)
    code = create_staff(client, "nv_leader", perms=("sidebar_products", "can_checklist_leader"))
    logout(client)
    activate(client, "nv_leader", code)
    r = client.get("/ceo")
    assert r.status_code == 200
    assert "Dashboard CEO" in r.text


def test_anonymous_redirected_to_login(client):
    create_owner(client)
    logout(client)
    r = client.get("/ceo", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login")


# --- tổng hợp số thật --------------------------------------------------------


def test_ceo_page_with_data(client):
    create_owner(client)
    db, cl, ceo = _db(), _cl(), _ceo()
    today = cl.today_str()
    yesterday = ceo._shift(today, -1)

    # Báo cáo ngày: hôm nay 3.000.000đ (ROAS 3.0), hôm qua 2.500.000đ → +20%
    _report(db, today, 3_000_000, 900_000, 300_000)
    _report(db, yesterday, 2_500_000, 750_000, 250_000)

    # GMV: sản phẩm mới có entry hôm nay, ROAS = 100/100 = 1.0 < 2.0
    pid = db.gmv_create_product("SP CEO TEST")
    db.gmv_upsert_entry(
        pid,
        {
            "date": today,
            "views": 1000,
            "clicks": 100,
            "conversions": 5,
            "revenue_vnd": 530000,
            "ad_cost": 530000,
            "action_note": "",
        },
        "test",
    )

    # Checklist: nhân viên được giao 2 việc — 1 xong, 1 quá hạn (hạn 00:01)
    create_staff(client, "nv_ceo", perms=("sidebar_products",))
    staff = db.get_user_by_username("nv_ceo")
    cl.seed_defaults()
    cl.generate_for_date(today)
    items = db.cl_item_list(today)
    db.cl_item_update(
        items[0]["id"],
        {
            "assignee_id": staff["id"],
            "status": "done",
            "completed_by": "nv_ceo",
        },
    )
    db.cl_item_update(items[1]["id"], {"assignee_id": staff["id"]})
    # due_time không nằm trong CL_ITEM_UPDATE_COLUMNS (việc đã tạo không sửa
    # giờ hạn qua helper) nên test đặt thẳng SQL — nếu không, test chỉ pass
    # khi chạy sau giờ hạn gốc 08:30 của mẫu.
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE checklist_items SET due_time = '00:01' WHERE id = ?",
            (items[1]["id"],),
        )

    r = client.get(f"/ceo?from={today}&to={today}")
    assert r.status_code == 200
    html = r.text

    # Thẻ doanh thu + % thay đổi (khoảng 1 ngày hôm nay vs hôm qua)
    assert "3,000,000₫" in html
    assert "+20.0%" in html
    assert "2,500,000₫" in html  # xuất hiện ở bảng 7 ngày

    # Thẻ GMV: doanh thu 530.000₫
    assert "530,000₫" in html

    # Cảnh báo ROAS thấp có tên sản phẩm
    assert "SP CEO TEST" in html
    assert "ROAS" in html

    # Checklist: thẻ tính toàn hệ thống (20 việc, 1 xong) → "1/20 xong";
    # dòng của nv_ceo: 2 được giao, 1 xong, 1 quá hạn → mục Cần chú ý
    assert "1/20 xong" in html
    assert "còn 1 việc quá hạn" in html
    assert "nv_ceo" in html
    # Link xem việc của nhân viên
    assert f"/checklist?date={today}&amp;assignee={staff['id']}" in html or (
        f"/checklist?date={today}&assignee={staff['id']}" in html
    )


def test_overview_rev_change_none_when_yesterday_zero(client):
    create_owner(client)
    db, cl, ceo = _db(), _cl(), _ceo()
    today = cl.today_str()
    yesterday = ceo._shift(today, -1)
    _report(db, today, 1_000_000, 100_000, 50_000)
    _report(db, yesterday, 0, 0, 0)
    ov = ceo.ceo_overview(today)
    assert ov["has_report_today"] is True
    assert ov["revenue_today"]["total_rev"] == 1_000_000
    assert ov["revenue_yesterday_total"] == 0
    assert ov["rev_change_pct"] is None  # hôm qua = 0 → không chia
    assert len(ov["revenue_7d"]) == 7
    assert ov["revenue_7d"][-1]["total_rev"] == 1_000_000
    assert ov["revenue_7d"][-2]["total_rev"] == 0
    assert ov["revenue_7d"][0]["total_rev"] is None  # thiếu → None, không phải 0


def test_overview_no_report_today_alert(client):
    create_owner(client)
    cl, ceo = _cl(), _ceo()
    ov = ceo.ceo_overview(cl.today_str())
    assert ov["has_report_today"] is False
    assert ov["rev_change_pct"] is None
    titles = [a["title"] for a in ov["alerts"]]
    assert any("Chưa nhập Báo cáo ngày hôm nay" in t for t in titles)
    # GMV hôm nay trống → không cộng dồn thành số giả
    assert ov["gmv_today"]["entry_count"] == 0
    assert ov["gmv_today"]["revenue_vnd"] == 0
    assert ov["gmv_today"]["roas"] is None


def test_overview_gmv_stale_and_roas_alerts(client):
    create_owner(client)
    db, cl, ceo = _db(), _cl(), _ceo()
    today = cl.today_str()
    # Sản phẩm có entry cũ (10 ngày trước) → cảnh báo hết hạn dữ liệu
    pid_old = db.gmv_create_product("SP CU")
    db.gmv_upsert_entry(
        pid_old,
        {
            "date": ceo._shift(today, -10),
            "views": 10,
            "clicks": 1,
            "conversions": 0,
            "revenue_vnd": 265000,
            "ad_cost": 10,
            "action_note": "",
        },
        "test",
    )
    # Sản phẩm có entry hôm nay ROAS tốt (5.0) → không cảnh báo
    pid_ok = db.gmv_create_product("SP TOT")
    db.gmv_upsert_entry(
        pid_ok,
        {
            "date": today,
            "views": 10,
            "clicks": 1,
            "conversions": 1,
            "revenue_vnd": 2650000,
            "ad_cost": 530000,
            "action_note": "",
        },
        "test",
    )
    ov = ceo.ceo_overview(today)
    names = {a["product_name"] for a in ov["product_alerts"]}
    assert "SP CU" in names
    assert "SP TOT" not in names
    stale = next(a for a in ov["product_alerts"] if a["product_name"] == "SP CU")
    assert stale["note"] == "chưa có dữ liệu gần đây"
    # GMV tổng hôm nay chỉ tính entry hôm nay của SP TOT: 2.650.000₫
    assert ov["gmv_today"]["revenue_vnd"] == 500 * 5300
    assert ov["gmv_today"]["roas"] == 5.0
