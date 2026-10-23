"""Biểu đồ GMV + cảnh báo tự động: series, totals, 4 quy tắc, dedupe thông báo, trang /gmv."""

from datetime import date

from conftest import activate, create_owner, create_staff, logout

TODAY = date(2026, 10, 20)


def _db():
    from app import database as db

    return db


def _charts():
    from app import gmv_charts

    return gmv_charts


def _product(name):
    return _db().gmv_create_product(name)


def _entry(pid, day, revenue_rm=100, ad_cost=30):
    _db().gmv_upsert_entry(
        pid,
        {
            "date": day,
            "views": 100,
            "clicks": 10,
            "conversions": 2,
            "revenue_rm": revenue_rm,
            "ad_cost": ad_cost,
            "action_note": "",
        },
        "test",
    )


def _rules(alerts):
    return {(a["product_id"], a["rule"]) for a in alerts}


# ------------------------------ build_series -------------------------------


def test_series_missing_days_are_none_not_zero(client):
    pid = _product("SP A")
    _entry(pid, "2026-10-18", revenue_rm=200, ad_cost=100)
    _entry(pid, "2026-10-20", revenue_rm=100, ad_cost=50)
    s = _charts().build_series(pid, 7, TODAY)
    assert s["labels"] == [
        "2026-10-14",
        "2026-10-15",
        "2026-10-16",
        "2026-10-17",
        "2026-10-18",
        "2026-10-19",
        "2026-10-20",
    ]
    assert s["gmv_vnd"] == [None, None, None, None, 200 * 5300, None, 100 * 5300]
    assert s["cost_vnd"] == [None, None, None, None, 100 * 5300, None, 50 * 5300]
    assert s["roas"] == [None, None, None, None, 2.0, None, 2.0]


def test_series_days_variants_and_all_products(client):
    p1 = _product("SP A")
    p2 = _product("SP B")
    _entry(p1, "2026-10-19", revenue_rm=100, ad_cost=50)
    _entry(p2, "2026-10-19", revenue_rm=50, ad_cost=25)
    _entry(p2, "2026-10-01", revenue_rm=999, ad_cost=1)

    charts = _charts()
    for days in (7, 14, 30):
        s = charts.build_series(None, days, TODAY)
        assert len(s["labels"]) == days
        assert len(s["gmv_vnd"]) == days
    s = charts.build_series(None, 7, TODAY)
    idx = s["labels"].index("2026-10-19")
    assert s["gmv_vnd"][idx] == 150 * 5300  # tổng cả 2 sản phẩm
    assert s["roas"][idx] == 2.0  # 150 / 75
    # ngày ngoài cửa sổ 7 ngày không lọt vào
    assert 999 * 5300 not in [v for v in s["gmv_vnd"] if v is not None]


def test_series_zero_cost_roas_none_but_gmv_present(client):
    pid = _product("SP FREE")
    _entry(pid, "2026-10-20", revenue_rm=10, ad_cost=0)
    s = _charts().build_series(pid, 7, TODAY)
    assert s["gmv_vnd"][-1] == 10 * 5300
    assert s["cost_vnd"][-1] == 0
    assert s["roas"][-1] is None


def test_series_accepts_string_today(client):
    pid = _product("SP A")
    _entry(pid, "2026-10-20", revenue_rm=10, ad_cost=5)
    s = _charts().build_series(pid, 7, "2026-10-20")
    assert s["labels"][-1] == "2026-10-20"
    assert s["gmv_vnd"][-1] == 10 * 5300


# ------------------------------ product_totals ------------------------------


def test_product_totals_sorted_and_windowed(client):
    p1 = _product("SP NHO")
    p2 = _product("SP LON")
    p3 = _product("SP NGOAI KY")
    _entry(p1, "2026-10-20", revenue_rm=100, ad_cost=50)
    _entry(p1, "2026-10-19", revenue_rm=100, ad_cost=50)
    _entry(p2, "2026-10-15", revenue_rm=500, ad_cost=100)
    _entry(p3, "2026-09-01", revenue_rm=9999, ad_cost=1)  # ngoài kỳ 14 ngày
    totals = _charts().product_totals(14, TODAY)
    names = [t["product_name"] for t in totals]
    assert names == ["SP LON", "SP NHO"]  # GMV giảm dần, SP ngoài kỳ bị loại
    lon, nho = totals
    assert lon["gmv_vnd"] == 500 * 5300
    assert lon["roas"] == 5.0
    assert nho["gmv_vnd"] == 200 * 5300
    assert nho["cost_vnd"] == 100 * 5300
    assert nho["entry_days"] == 2


# --------------------------------- alerts -----------------------------------


def test_alert_roas_low_fires_and_not_when_ok(client):
    bad = _product("SP ROAS THAP")
    _entry(bad, "2026-10-20", revenue_rm=100, ad_cost=100)  # ROAS 1.0 < 2.0
    good = _product("SP ROAS TOT")
    _entry(good, "2026-10-20", revenue_rm=300, ad_cost=100)  # ROAS 3.0
    alerts = _charts().gmv_alerts(TODAY)
    assert (bad, "roas_low") in _rules(alerts)
    assert (good, "roas_low") not in _rules(alerts)
    msg = next(a["message"] for a in alerts if a["rule"] == "roas_low")
    assert "chỉ đạt 1.0" in msg
    assert "dưới ngưỡng 2.0" in msg


def test_alert_stale_fires_for_old_and_never(client):
    old = _product("SP CU")
    _entry(old, "2026-10-10", revenue_rm=100, ad_cost=10)  # 10 ngày trước
    fresh = _product("SP MOI")
    _entry(fresh, "2026-10-19", revenue_rm=100, ad_cost=10)
    never = _product("SP CHUA NHAP")
    rules = _rules(_charts().gmv_alerts(TODAY))
    assert (old, "stale") in rules
    assert (never, "stale") in rules
    assert (fresh, "stale") not in rules


def test_alert_gmv_drop_fires(client):
    pid = _product("SP TUT GMV")
    # 3 ngày trước: 300/ngày; 3 ngày gần nhất: 100/ngày -> giảm 66,7%
    for d in ("2026-10-15", "2026-10-16", "2026-10-17"):
        _entry(pid, d, revenue_rm=300, ad_cost=100)
    for d in ("2026-10-18", "2026-10-19", "2026-10-20"):
        _entry(pid, d, revenue_rm=100, ad_cost=100)
    rules = _rules(_charts().gmv_alerts(TODAY))
    assert (pid, "gmv_drop") in rules
    # doanh thu giảm thật nhưng ROAS cũng giảm (3.0 -> 1.0): roas_drop cũng fire
    assert (pid, "roas_drop") in rules


def test_alert_gmv_drop_not_fire_when_stable(client):
    pid = _product("SP ON DINH")
    for d in (
        "2026-10-15",
        "2026-10-16",
        "2026-10-17",
        "2026-10-18",
        "2026-10-19",
        "2026-10-20",
    ):
        _entry(pid, d, revenue_rm=200, ad_cost=100)
    rules = _rules(_charts().gmv_alerts(TODAY))
    assert (pid, "gmv_drop") not in rules
    assert (pid, "roas_drop") not in rules


def test_alert_roas_drop_only(client):
    pid = _product("SP TUT ROAS")
    # GMV giữ nguyên 300/ngày; chi phí tăng 100 -> 300 nên ROAS 3.0 -> 1.0
    for d in ("2026-10-15", "2026-10-16", "2026-10-17"):
        _entry(pid, d, revenue_rm=300, ad_cost=100)
    for d in ("2026-10-18", "2026-10-19", "2026-10-20"):
        _entry(pid, d, revenue_rm=300, ad_cost=300)
    rules = _rules(_charts().gmv_alerts(TODAY))
    assert (pid, "roas_drop") in rules
    assert (pid, "gmv_drop") not in rules


def test_alert_drop_rules_need_min_4_data_days(client):
    pid = _product("SP IT DU LIEU")
    # Chỉ 3 ngày có số, GMV tụt mạnh nhưng chưa đủ dữ liệu để so 2 kỳ
    _entry(pid, "2026-10-18", revenue_rm=900, ad_cost=100)
    _entry(pid, "2026-10-19", revenue_rm=100, ad_cost=100)
    _entry(pid, "2026-10-20", revenue_rm=100, ad_cost=100)
    rules = _rules(_charts().gmv_alerts(TODAY))
    assert (pid, "gmv_drop") not in rules
    assert (pid, "roas_drop") not in rules


# ------------------------------ dedupe thông báo ----------------------------


def _owner_id(client):
    create_owner(client)
    users = _db().list_users()
    owner = next(u for u in users if u["is_owner"])
    return owner["id"]


def test_sync_notifications_dedupe_same_day(client):
    owner_id = _owner_id(client)
    pid = _product("SP ROAS THAP")
    _entry(pid, "2026-10-20", revenue_rm=100, ad_cost=100)  # roas_low, không stale
    charts = _charts()

    created = charts.sync_gmv_alert_notifications(TODAY)
    assert created == 1  # 1 cảnh báo x 1 người nhận (chỉ owner)
    notifs = _db().notif_list(owner_id)
    assert len(notifs) == 1
    assert "Cảnh báo GMV Max" in notifs[0]["title"]
    assert notifs[0]["link"] == "/gmv"
    assert notifs[0]["item_id"] == pid

    # chạy lại cùng ngày: không tạo thêm
    assert charts.sync_gmv_alert_notifications(TODAY) == 0
    assert charts.sync_gmv_alert_notifications(TODAY) == 0
    assert len(_db().notif_list(owner_id)) == 1

    # sang ngày mới: được tạo lại (entry mới nhất vẫn ROAS thấp)
    created = charts.sync_gmv_alert_notifications(date(2026, 10, 21))
    assert created >= 1
    assert len(_db().notif_list(owner_id)) >= 2


def test_sync_notifications_recipients_include_gmv_viewers(client):
    owner_id = _owner_id(client)
    code = create_staff(client, "nv_xem", perms=("can_view_gmv",))
    code2 = create_staff(client, "nv_khong_xem", perms=("can_view_uni",))
    logout(client)
    activate(client, "nv_xem", code)
    logout(client)
    activate(client, "nv_khong_xem", code2)
    users = {u["username"]: u for u in _db().list_users()}

    pid = _product("SP CANH BAO")
    _entry(pid, "2026-10-20", revenue_rm=100, ad_cost=100)
    created = _charts().sync_gmv_alert_notifications(TODAY)
    assert created == 2  # owner + nv_xem
    assert len(_db().notif_list(owner_id)) == 1
    assert len(_db().notif_list(users["nv_xem"]["id"])) == 1
    assert len(_db().notif_list(users["nv_khong_xem"]["id"])) == 0


def test_sync_no_alerts_creates_nothing(client):
    _owner_id(client)
    pid = _product("SP TOT")
    _entry(pid, "2026-10-20", revenue_rm=300, ad_cost=100)
    assert _charts().sync_gmv_alert_notifications(TODAY) == 0


# -------------------------------- trang /gmv --------------------------------


def test_gmv_page_has_chart_and_alerts(client):
    create_owner(client)
    pid = _product("SP TRANG")
    _entry(pid, "2026-10-20", revenue_rm=100, ad_cost=100)
    r = client.get("/gmv")
    assert r.status_code == 200
    html = r.text
    assert "📊 Biểu đồ GMV" in html
    assert "⚠️ Cảnh báo" in html
    assert "chartMoney" in html
    assert "chartRoas" in html
    # dữ liệu series được nhúng vào trang (labels ngày + dãy GMV)
    assert '"labels"' in html
    assert '"gmv_vnd"' in html
    # cảnh báo ROAS thấp hiển thị
    assert "chỉ đạt 1.0" in html
    # bảng cũ vẫn còn
    assert "gmvTable" in html


def test_gmv_page_query_validation(client):
    create_owner(client)
    pid = _product("SP TRANG")
    _entry(pid, "2026-10-20", revenue_rm=100, ad_cost=30)
    # days bậy -> mặc định 14; product bậy -> tất cả; vẫn 200
    r = client.get("/gmv?days=99&product=xyz")
    assert r.status_code == 200
    r = client.get("/gmv?days=7&product=999999")
    assert r.status_code == 200
    r = client.get(f"/gmv?days=30&product={pid}")
    assert r.status_code == 200
    assert '"days": 30' in r.text


def test_gmv_page_forbidden_without_view_perm(client):
    create_owner(client)
    code = create_staff(client, "nv_uni", perms=("can_view_uni",))
    logout(client)
    activate(client, "nv_uni", code)
    assert client.get("/gmv").status_code == 403
