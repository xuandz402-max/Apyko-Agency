"""Chọn khoảng thời gian dùng chung: resolve_period, delta + 3 trang dùng."""

from datetime import date, datetime, timedelta

from conftest import activate, create_owner, create_staff, logout

EN = "\u2013"  # en-dash trong nhãn khoảng ngày, khớp app/periods.py


def _db():
    from app import database as db

    return db


def _cl():
    from app import checklist

    return checklist


def _periods():
    from app import periods

    return periods


def _report(db, date_str, total, ad_gmv, ad_cost):
    db.daily_upsert(
        {
            "date": date_str,
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
        },
        "test",
    )


def _gmv(db, pid, date_str, revenue_rm, ad_cost_rm):
    db.gmv_upsert_entry(
        pid,
        {
            "date": date_str,
            "views": 100,
            "clicks": 10,
            "conversions": 1,
            "revenue_rm": revenue_rm,
            "ad_cost": ad_cost_rm,
            "action_note": "",
        },
        "test",
    )


def _d(iso):
    return datetime.strptime(iso, "%Y-%m-%d").date()


def _span(info, key_start, key_end):
    return (_d(info[key_end]) - _d(info[key_start])).days


# --- resolve_period ----------------------------------------------------------


def test_resolve_day(client):
    p = _periods()
    info = p.resolve_period({"period": "day"}, "2026-10-20")
    assert info["period"] == "day"
    assert (info["cur_start"], info["cur_end"]) == ("2026-10-20", "2026-10-20")
    assert (info["prev_start"], info["prev_end"]) == ("2026-10-19", "2026-10-19")
    assert info["label_cur"] == "20/10"
    assert info["label_prev"] == "19/10"
    assert info["num_days"] == 1
    assert (info["from"], info["to"]) == ("2026-10-20", "2026-10-20")


def test_resolve_week(client):
    p = _periods()
    # Thứ Ba 20/10/2026: TRỌN tuần 19/10-25/10, kỳ trước trọn tuần 12/10-18/10
    info = p.resolve_period({"period": "week"}, "2026-10-20")
    assert (info["cur_start"], info["cur_end"]) == ("2026-10-19", "2026-10-25")
    assert (info["prev_start"], info["prev_end"]) == ("2026-10-12", "2026-10-18")
    assert info["label_cur"] == f"19/10 {EN} 25/10"
    assert info["label_prev"] == f"12/10 {EN} 18/10"
    assert _span(info, "cur_start", "cur_end") == _span(info, "prev_start", "prev_end")


def test_resolve_month_and_edge(client):
    p = _periods()
    # TRỌN tháng lịch: 01/10-31/10 so với trọn tháng 9 (01/09-30/09)
    info = p.resolve_period({"period": "month"}, "2026-10-20")
    assert (info["cur_start"], info["cur_end"]) == ("2026-10-01", "2026-10-31")
    assert (info["prev_start"], info["prev_end"]) == ("2026-09-01", "2026-09-30")
    # Tháng trước ngắn hơn (tháng 2/2026 có 28 ngày) -> trọn tháng 2
    info = p.resolve_period({"period": "month"}, "2026-03-31")
    assert (info["prev_start"], info["prev_end"]) == ("2026-02-01", "2026-02-28")


def test_resolve_custom(client):
    p = _periods()
    info = p.resolve_period(
        {"period": "custom", "from": "2026-10-01", "to": "2026-10-10"},
        "2026-10-20",
    )
    assert info["period"] == "custom"
    assert (info["cur_start"], info["cur_end"]) == ("2026-10-01", "2026-10-10")
    # Kỳ trước: 10 ngày liền trước 01/10 -> 21/09 - 30/09
    assert (info["prev_start"], info["prev_end"]) == ("2026-09-21", "2026-09-30")
    assert info["num_days"] == 10
    assert info["label_cur"] == f"01/10 {EN} 10/10"
    assert info["cur_name"] == "Kỳ đã chọn"


def test_resolve_custom_invalid_falls_back_to_day(client):
    p = _periods()
    cases = [
        {"period": "custom", "from": "2026-10-10", "to": "2026-10-01"},  # to < from
        {"period": "custom", "from": "2026-13-01", "to": "2026-10-01"},  # tháng 13
        {"period": "custom", "from": "10/10/2026", "to": "2026-10-20"},  # sai format
        {"period": "custom", "from": "2026-10-01"},  # thiếu to
        {"period": "custom"},  # thiếu cả 2
        {"period": "quy"},  # period lạ
        {"period": ""},
        {},
        None,
    ]
    for params in cases:
        info = p.resolve_period(params, "2026-10-20")
        assert info["period"] == "day", params
        assert (info["cur_start"], info["cur_end"]) == ("2026-10-20", "2026-10-20")


def test_cap_period(client):
    p = _periods()
    info = p.resolve_period(
        {"period": "custom", "from": "2026-09-01", "to": "2026-10-20"},
        "2026-10-20",
    )
    assert info["num_days"] == 50
    capped = p.cap_period(info, max_days=31)
    assert capped["capped"] is True
    # Giữ 31 ngày gần nhất: 20/09 - 20/10; kỳ trước liền kề 20/08 - 19/09
    assert (capped["cur_start"], capped["cur_end"]) == ("2026-09-20", "2026-10-20")
    assert (capped["prev_start"], capped["prev_end"]) == ("2026-08-20", "2026-09-19")
    short = p.cap_period(p.resolve_period({"period": "week"}, "2026-10-20"))
    assert short["capped"] is False
    assert short["cur_start"] == "2026-10-19"


# --- delta_pct ---------------------------------------------------------------


def test_delta_pct(client):
    p = _periods()
    assert p.delta_pct(120, 100) == 20.0
    assert p.delta_pct(80, 100) == -20.0
    assert p.delta_pct(100, 100) == 0.0
    assert p.delta_pct(0, 100) == -100.0
    assert p.delta_pct(100, 0) is None  # kỳ trước = 0 -> không bịa %
    assert p.delta_pct(None, 100) is None
    assert p.delta_pct(100, None) is None
    assert p.delta_pct(None, None) is None


# --- /bao-cao ------------------------------------------------------------------


def _seed_two_weeks(client):
    """Báo cáo tuần này + tuần trước (mỗi ngày 1 báo cáo, số tròn dễ kiểm)."""
    db, cl = _db(), _cl()
    today = cl.today_str()
    d = _d(today)
    monday = d - timedelta(days=d.weekday())
    n = d.weekday() + 1
    for i in range(n):
        _report(db, (monday + timedelta(days=i)).isoformat(), 1_000_000, 200_000, 100_000)
        _report(
            db,
            (monday - timedelta(days=7) + timedelta(days=i)).isoformat(),
            500_000,
            50_000,
            100_000,
        )
    # 1 báo cáo rất cũ, ngoài cả kỳ tháng — không được lọt vào danh sách tuần
    _report(db, (d - timedelta(days=60)).isoformat(), 7_777_000, 0, 0)
    return today, n


def test_daily_page_week_totals_and_delta(client):
    create_owner(client)
    today, n = _seed_two_weeks(client)
    d = _d(today)
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    # Khoảng xem = trọn tuần này (thứ Hai -> Chủ Nhật) để khoảng liền
    # trước dài bằng nhau trùng đúng tuần trước đã seed.
    r = client.get(f"/bao-cao?from={monday.isoformat()}&to={sunday.isoformat()}")
    assert r.status_code == 200
    html = r.text
    assert "Tổng theo kỳ" in html
    # Tổng doanh thu kỳ này = n * 1.000.000đ, gấp đôi kỳ trước -> +100.0%
    expected = f"{n * 1_000_000:,.0f}".replace(",", ".") + "đ"
    assert expected in html
    assert "+100.0%" in html
    assert "delta-up" in html
    # Báo cáo cũ 60 ngày không nằm trong danh sách của khoảng
    assert "7.777.000" not in html
    # Danh sách có ngày hôm nay dạng dd/mm/yyyy
    assert f"{d.day:02d}/{d.month:02d}/{d.year}" in html


def test_daily_page_default_last30(client):
    create_owner(client)
    db, cl = _db(), _cl()
    today = cl.today_str()
    yesterday = (_d(today) - timedelta(days=1)).isoformat()
    old = (_d(today) - timedelta(days=60)).isoformat()
    _report(db, today, 3_000_000, 900_000, 300_000)
    _report(db, yesterday, 9_999_000, 0, 0)
    _report(db, old, 8_888_000, 0, 0)
    r = client.get("/bao-cao")
    assert r.status_code == 200
    # Mặc định trang Báo cáo ngày = 30 ngày qua: hôm nay + hôm qua đều có
    assert "3.000.000đ" in r.text
    assert "9.999.000" in r.text
    # Báo cáo 60 ngày trước nằm ngoài khoảng mặc định
    assert "8.888.000" not in r.text


def test_daily_page_empty_period_message(client):
    create_owner(client)
    r = client.get("/bao-cao?from=2020-01-01&to=2020-01-07")
    assert r.status_code == 200
    assert "Chưa có báo cáo nào trong kỳ này" in r.text


# --- /gmv ----------------------------------------------------------------------


def test_gmv_page_period_compare(client):
    create_owner(client)
    db, cl = _db(), _cl()
    today = cl.today_str()
    d = _d(today)
    monday = d - timedelta(days=d.weekday())
    prev_monday = monday - timedelta(days=7)
    pid = db.gmv_create_product("SP KY")
    _gmv(db, pid, monday.isoformat(), 100, 50)  # kỳ này: 100 RM
    _gmv(db, pid, prev_monday.isoformat(), 50, 50)  # kỳ trước: 50 RM
    # Khoảng xem = trọn tuần này (thứ Hai -> Chủ Nhật); khoảng liền trước
    # dài bằng nhau chứa đúng thứ Hai tuần trước.
    sunday = (monday + timedelta(days=6)).isoformat()
    r = client.get(f"/gmv?from={monday.isoformat()}&to={sunday}")
    assert r.status_code == 200
    html = r.text
    assert "So sánh theo kỳ" in html
    assert "530.000đ" in html  # 100 RM x 5300
    assert "+100.0%" in html  # GMV gấp đôi kỳ trước
    assert "delta-up" in html


def test_gmv_page_period_no_entries(client):
    create_owner(client)
    r = client.get("/gmv?from=2020-01-01&to=2020-01-31")
    assert r.status_code == 200
    assert "So sánh theo kỳ" in r.text
    assert "Chưa có dòng số liệu GMV nào trong kỳ này" in r.text
    assert "—" in r.text


# --- /checklist/board ------------------------------------------------------------

MON = "2026-10-19"  # Thứ 2
TUE = "2026-10-20"  # Thứ 3
PREV_MON = "2026-10-12"
PREV_TUE = "2026-10-13"


def _complete_first(db, date_str, count):
    items = db.cl_item_list(date_str)
    for item in items[:count]:
        db.cl_item_update(item["id"], {"status": "done", "completed_by": "test"})


def _seed_board_two_weeks(client):
    db, cl = _db(), _cl()
    cl.seed_defaults()
    for day in (MON, TUE, PREV_MON, PREV_TUE):
        cl.generate_for_date(day)
    _complete_first(db, MON, 10)
    _complete_first(db, TUE, 10)  # kỳ này: 20/40 xong -> 50%
    _complete_first(db, PREV_MON, 5)
    _complete_first(db, PREV_TUE, 5)  # kỳ trước: 10/40 xong -> 25%


def test_board_page_week_aggregation(client):
    create_owner(client)
    _seed_board_two_weeks(client)
    r = client.get(f"/checklist/board?date={TUE}&period=week")
    assert r.status_code == 200
    html = r.text
    assert "Tổng quan theo kỳ" in html
    assert "50.0%" in html  # % hoàn thành kỳ này
    assert "+25.0 điểm %" in html  # 50% - 25% = +25 điểm %
    assert "delta-up" in html


def test_board_page_default_day_unchanged(client):
    create_owner(client)
    db, cl = _db(), _cl()
    cl.seed_defaults()
    cl.generate_for_date(MON)
    _complete_first(db, MON, 4)
    r = client.get(f"/checklist/board?date={MON}")
    assert r.status_code == 200
    assert "Tổng số công việc" in r.text
    # Mặc định Ngày: chỉ ngày neo, tổng 20 việc
    stats_html = r.text
    assert '<div class="stat-value">20</div>' in stats_html


def test_board_page_week_forbidden_for_plain_staff(client):
    create_owner(client)
    code = create_staff(client, "nv_board", perms=("can_view_products",))
    logout(client)
    activate(client, "nv_board", code)
    assert client.get("/checklist/board?period=week").status_code == 403
    custom = "/checklist/board?period=custom&from=2026-10-01&to=2026-10-07"
    assert client.get(custom).status_code == 403


def test_board_range_stats_unit(client):
    create_owner(client)
    _seed_board_two_weeks(client)
    cl = _cl()
    stats = cl.board_range_stats(MON, TUE)
    assert stats["total"] == 40
    assert stats["done"] == 20
    assert stats["pct"] == 50.0
    assert stats["days"] == 2
    prev = cl.board_range_stats(PREV_MON, PREV_TUE)
    assert prev["done"] == 10
    assert prev["pct"] == 25.0


# --- query param bậy: các trang đều 200 với khoảng mặc định ---------------------


def test_bad_params_fall_back_to_default_range(client):
    create_owner(client)
    # /bao-cao + /gmv: param from/to bậy -> preset mặc định của trang
    r = client.get("/bao-cao?period=xyz&from=abc&to=def")
    assert r.status_code == 200
    assert "Tổng theo kỳ" in r.text
    assert "rp-preset active" in r.text

    r = client.get("/gmv?period=nope&from=2026-13-99&to=x")
    assert r.status_code == 200
    assert "So sánh theo kỳ" in r.text
    assert "rp-preset active" in r.text

    # Bảng Leader giữ nguyên cơ chế kỳ riêng (không đổi ở đợt này)
    r = client.get("/checklist/board?period=q&from=bad&to=worse")
    assert r.status_code == 200
    assert "Tổng quan theo kỳ" in r.text

    r = client.get(f"/bao-cao?from={date.today().isoformat()}&to=2020-01-01")
    assert r.status_code == 200  # to < from -> quay về mặc định, không lỗi
