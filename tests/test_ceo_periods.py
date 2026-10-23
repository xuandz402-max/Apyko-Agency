"""Dashboard CEO — so sánh theo kỳ (hàm thuần) + bộ chọn khoảng ngày kiểu
Shopee Ads ở route /ceo (?from&to, mặc định 7 ngày qua)."""

from datetime import datetime, timedelta

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
    db.daily_upsert(
        {
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
        },
        "test",
    )


def _gmv(db, pid, date, revenue_rm, ad_cost_rm):
    db.gmv_upsert_entry(
        pid,
        {
            "date": date,
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


# --- toán khoảng kỳ ----------------------------------------------------------


def test_period_ranges_day(client):
    ceo = _ceo()
    cur, prev = ceo.period_ranges("2026-10-20", "day")
    assert cur == ("2026-10-20", "2026-10-20")
    assert prev == ("2026-10-19", "2026-10-19")
    # Qua ranh giới tháng
    cur, prev = ceo.period_ranges("2026-11-01", "day")
    assert cur == ("2026-11-01", "2026-11-01")
    assert prev == ("2026-10-31", "2026-10-31")


def test_period_ranges_week(client):
    ceo = _ceo()
    # Thứ Ba 20/10/2026: TRỌN tuần thứ Hai 19/10 -> Chủ Nhật 25/10
    cur, prev = ceo.period_ranges("2026-10-20", "week")
    assert cur == ("2026-10-19", "2026-10-25")
    assert prev == ("2026-10-12", "2026-10-18")
    # Đúng thứ Hai: vẫn trọn tuần
    cur, prev = ceo.period_ranges("2026-10-19", "week")
    assert cur == ("2026-10-19", "2026-10-25")
    assert prev == ("2026-10-12", "2026-10-18")
    # Chủ Nhật: cùng tuần đó
    cur, prev = ceo.period_ranges("2026-10-25", "week")
    assert cur == ("2026-10-19", "2026-10-25")
    assert prev == ("2026-10-12", "2026-10-18")
    # Tuần vắt qua 2 tháng (thứ Tư 04/11/2026, thứ Hai là 02/11)
    cur, prev = ceo.period_ranges("2026-11-04", "week")
    assert cur == ("2026-11-02", "2026-11-08")
    assert prev == ("2026-10-26", "2026-11-01")


def test_period_ranges_month(client):
    ceo = _ceo()
    # TRỌN tháng lịch: 01/10 -> 31/10, kỳ trước trọn tháng 9
    cur, prev = ceo.period_ranges("2026-10-20", "month")
    assert cur == ("2026-10-01", "2026-10-31")
    assert prev == ("2026-09-01", "2026-09-30")
    # Ngày 1 đầu tháng: vẫn trọn tháng
    cur, prev = ceo.period_ranges("2026-11-01", "month")
    assert cur == ("2026-11-01", "2026-11-30")
    assert prev == ("2026-10-01", "2026-10-31")
    # Qua ranh giới năm
    cur, prev = ceo.period_ranges("2026-01-15", "month")
    assert cur == ("2026-01-01", "2026-01-31")
    assert prev == ("2025-12-01", "2025-12-31")
    # Tháng trước ngắn hơn (tháng 2/2026 có 28 ngày)
    cur, prev = ceo.period_ranges("2026-03-31", "month")
    assert cur == ("2026-03-01", "2026-03-31")
    assert prev == ("2026-02-01", "2026-02-28")
    # 31/05 so với tháng 4 (30 ngày)
    cur, prev = ceo.period_ranges("2026-05-31", "month")
    assert cur == ("2026-05-01", "2026-05-31")
    assert prev == ("2026-04-01", "2026-04-30")


def test_period_ranges_invalid_falls_back_to_day(client):
    ceo = _ceo()
    assert ceo.period_ranges("2026-10-20", "quarter") == ceo.period_ranges(
        "2026-10-20", "day"
    )
    assert ceo.period_ranges("2026-10-20", "")[0] == ("2026-10-20", "2026-10-20")


# --- so sánh chỉ số ----------------------------------------------------------


def test_period_compare_day_up(client):
    create_owner(client)
    db, cl, ceo = _db(), _cl(), _ceo()
    today = cl.today_str()
    yesterday = ceo._shift(today, -1)
    _report(db, today, 3_000_000, 900_000, 300_000)  # ROAS 3.0
    _report(db, yesterday, 2_500_000, 500_000, 250_000)  # ROAS 2.0
    pid = db.gmv_create_product("SP PERIOD")
    _gmv(db, pid, today, 100, 40)
    _gmv(db, pid, yesterday, 50, 25)

    cmp = ceo.period_compare(today, "day")
    assert cmp["period"] == "day"
    assert cmp["cur_label"] == f"{today[8:10]}/{today[5:7]}"
    m = cmp["metrics"]
    assert m["revenue"] == {"cur": 3_000_000, "prev": 2_500_000, "delta_pct": 20.0}
    assert m["ads_cost"] == {"cur": 300_000, "prev": 250_000, "delta_pct": 20.0}
    assert m["roas"] == {"cur": 3.0, "prev": 2.0, "delta_pct": 50.0}
    assert m["gmv_vnd"] == {"cur": 530_000, "prev": 265_000, "delta_pct": 100.0}


def test_period_compare_day_down(client):
    create_owner(client)
    db, cl, ceo = _db(), _cl(), _ceo()
    today = cl.today_str()
    yesterday = ceo._shift(today, -1)
    _report(db, today, 2_000_000, 400_000, 200_000)  # ROAS 2.0
    _report(db, yesterday, 2_500_000, 500_000, 250_000)  # ROAS 2.0
    pid = db.gmv_create_product("SP XUONG")
    _gmv(db, pid, today, 40, 10)
    _gmv(db, pid, yesterday, 50, 10)

    m = ceo.period_compare(today, "day")["metrics"]
    assert m["revenue"]["delta_pct"] == -20.0
    assert m["ads_cost"]["delta_pct"] == -20.0
    assert m["roas"]["delta_pct"] == 0.0  # ROAS bằng nhau → 0%
    assert m["gmv_vnd"] == {"cur": 212_000, "prev": 265_000, "delta_pct": -20.0}


def test_period_compare_prev_zero_gives_no_delta(client):
    create_owner(client)
    db, cl, ceo = _db(), _cl(), _ceo()
    today = cl.today_str()
    yesterday = ceo._shift(today, -1)
    _report(db, today, 1_000_000, 100_000, 50_000)
    _report(db, yesterday, 0, 0, 0)  # có báo cáo nhưng toàn 0

    m = ceo.period_compare(today, "day")["metrics"]
    assert m["revenue"]["cur"] == 1_000_000
    assert m["revenue"]["prev"] == 0
    assert m["revenue"]["delta_pct"] is None  # kỳ trước = 0 → không bịa %
    assert m["ads_cost"]["prev"] == 0
    assert m["ads_cost"]["delta_pct"] is None
    assert m["roas"]["prev"] is None  # hôm qua chi phí 0 → ROAS không tính được
    assert m["roas"]["delta_pct"] is None
    assert m["gmv_vnd"]["cur"] is None  # chưa có entry GMV nào
    assert m["gmv_vnd"]["delta_pct"] is None


def test_period_compare_missing_data(client):
    create_owner(client)
    db, cl, ceo = _db(), _cl(), _ceo()
    today = cl.today_str()
    # Không có dữ liệu gì
    m = ceo.period_compare(today, "day")["metrics"]
    for key in ("revenue", "ads_cost", "roas", "gmv_vnd"):
        assert m[key] == {"cur": None, "prev": None, "delta_pct": None}
    # Chỉ có hôm nay, kỳ trước thiếu hẳn → prev None, delta None
    _report(db, today, 500_000, 50_000, 25_000)
    m = ceo.period_compare(today, "day")["metrics"]
    assert m["revenue"]["cur"] == 500_000
    assert m["revenue"]["prev"] is None
    assert m["revenue"]["delta_pct"] is None


def test_period_compare_week(client):
    create_owner(client)
    db, cl, ceo = _db(), _cl(), _ceo()
    today = cl.today_str()
    d = _d(today)
    monday = d - timedelta(days=d.weekday())
    n = d.weekday() + 1  # số ngày đã qua của tuần này (kể cả hôm nay)
    for i in range(n):
        _report(db, (monday + timedelta(days=i)).isoformat(), 1_000_000, 100_000, 50_000)
        _report(
            db,
            (monday - timedelta(days=7) + timedelta(days=i)).isoformat(),
            500_000,
            50_000,
            50_000,
        )
    cmp = ceo.period_compare(today, "week")
    assert cmp["cur_start"] == monday.isoformat()
    assert cmp["cur_end"] == (monday + timedelta(days=6)).isoformat()
    m = cmp["metrics"]
    assert m["revenue"]["cur"] == n * 1_000_000
    assert m["revenue"]["prev"] == n * 500_000
    assert m["revenue"]["delta_pct"] == 100.0
    assert m["roas"] == {"cur": 2.0, "prev": 1.0, "delta_pct": 100.0}


def test_period_compare_month(client):
    create_owner(client)
    db, cl, ceo = _db(), _cl(), _ceo()
    today = cl.today_str()
    d = _d(today)
    first = d.replace(day=1)
    prev_first = (first - timedelta(days=1)).replace(day=1)
    m_days = min(d.day, 28)  # seed đủ cho cả 2 tháng, tránh ca tháng ngắn
    for i in range(m_days):
        _report(db, (first + timedelta(days=i)).isoformat(), 100_000, 10_000, 5_000)
        _report(db, (prev_first + timedelta(days=i)).isoformat(), 50_000, 5_000, 5_000)
    cmp = ceo.period_compare(today, "month")
    assert cmp["cur_start"] == first.isoformat()
    rev = cmp["metrics"]["revenue"]
    assert rev["cur"] == m_days * 100_000
    assert rev["prev"] == m_days * 50_000
    assert rev["delta_pct"] == 100.0


def test_revenue_series_gaps(client):
    create_owner(client)
    db, cl, ceo = _db(), _cl(), _ceo()
    today = cl.today_str()
    _report(db, today, 3_000_000, 900_000, 300_000)
    _report(db, ceo._shift(today, -5), 1_000_000, 100_000, 50_000)
    s = ceo.revenue_series(today)
    assert len(s["labels"]) == 30
    assert len(s["revenue"]) == 30
    assert s["labels"][-1] == today
    assert s["labels"][0] == ceo._shift(today, -29)
    assert s["revenue"][-1] == 3_000_000
    assert s["revenue"][-6] == 1_000_000
    assert s["revenue"][-2] is None  # ngày chưa nhập → None, không phải 0
    assert sum(1 for v in s["revenue"] if v is not None) == 2


def test_cached_variants(client):
    create_owner(client)
    db, cl, ceo = _db(), _cl(), _ceo()
    today = cl.today_str()
    _report(db, today, 700_000, 70_000, 35_000)
    a = ceo.cached_period_compare(today, "week")
    b = ceo.cached_period_compare(today, "week")
    assert a == b
    assert a["metrics"]["revenue"]["cur"] is not None
    assert ceo.cached_period_compare(today, "xyz")["period"] == "day"
    s = ceo.cached_revenue_series(today)
    assert s["revenue"][-1] == 700_000


# --- route /ceo ---------------------------------------------------------------


def _seed_up(client):
    db, cl, ceo = _db(), _cl(), _ceo()
    today = cl.today_str()
    _report(db, today, 3_000_000, 900_000, 300_000)
    _report(db, ceo._shift(today, -1), 2_500_000, 500_000, 250_000)
    return today


def test_ceo_route_default_day_with_delta_up(client):
    create_owner(client)
    today = _seed_up(client)
    # Khoảng 1 ngày (from=to=hôm nay) -> so với hôm qua: +20.0%
    r = client.get(f"/ceo?from={today}&to={today}")
    assert r.status_code == 200
    html = r.text
    assert "Doanh thu trong khoảng" in html
    assert "delta-up" in html
    assert "+20.0%" in html
    # Đồng hồ giờ Việt Nam (khối biểu đồ 30 ngày đã bỏ theo yêu cầu tối giản)
    assert "ceoClock" in html
    assert "giờ Việt Nam" in html
    assert "ceoRevChart" not in html
    assert "Doanh thu 30 ngày gần nhất" not in html


def test_ceo_route_delta_down_class(client):
    create_owner(client)
    db, cl, ceo = _db(), _cl(), _ceo()
    today = cl.today_str()
    _report(db, today, 2_000_000, 400_000, 200_000)
    _report(db, ceo._shift(today, -1), 2_500_000, 500_000, 250_000)
    r = client.get(f"/ceo?from={today}&to={today}")
    assert r.status_code == 200
    assert "delta-down" in r.text
    assert "-20.0%" in r.text


def test_ceo_route_range_switch(client):
    create_owner(client)
    cl, ceo = _cl(), _ceo()
    today = cl.today_str()
    _seed_up(client)
    # Khoảng trùng preset 7 ngày qua -> preset đó active trên bộ chọn
    f7 = ceo._shift(today, -6)
    r = client.get(f"/ceo?from={f7}&to={today}")
    assert r.status_code == 200
    assert "7 ngày qua" in r.text
    assert "rp-preset active" in r.text
    # Khoảng trùng preset 30 ngày qua
    f30 = ceo._shift(today, -29)
    r = client.get(f"/ceo?from={f30}&to={today}")
    assert r.status_code == 200
    assert "30 ngày qua" in r.text
    assert "rp-preset active" in r.text
    # Param ngày bậy -> mặc định 7 ngày qua, không lỗi
    r = client.get("/ceo?from=abc&to=def")
    assert r.status_code == 200
    assert "rp-preset active" in r.text


def test_ceo_route_period_forbidden_for_plain_staff(client):
    create_owner(client)
    code = create_staff(client, "nv_period", perms=("can_view_products",))
    logout(client)
    activate(client, "nv_period", code)
    assert client.get("/ceo").status_code == 403
    assert client.get("/ceo?from=2026-10-01&to=2026-10-07").status_code == 403


def test_ceo_route_period_ok_for_leader(client):
    create_owner(client)
    code = create_staff(
        client, "nv_lead2", perms=("can_view_products", "can_checklist_leader")
    )
    logout(client)
    activate(client, "nv_lead2", code)
    r = client.get("/ceo?from=2026-10-01&to=2026-10-07")
    assert r.status_code == 200
    assert "Dashboard CEO" in r.text


def test_period_compare_day_fallback_to_latest_data_day(client):
    db, ceo = _db(), _ceo()
    _report(db, "2026-09-20", 5400, 1000, 200)
    _report(db, "2026-10-20", 5574, 1200, 500)
    cmp = ceo.period_compare("2026-10-20", "day")
    assert cmp["prev_fallback"] is True
    assert cmp["prev_start"] == "2026-09-20"
    assert cmp["prev_end"] == "2026-09-20"
    assert cmp["metrics"]["revenue"]["prev"] == 5400
    assert cmp["metrics"]["revenue"]["delta_pct"] == 3.2


def test_period_compare_day_no_fallback_when_yesterday_has_data(client):
    db, ceo = _db(), _ceo()
    _report(db, "2026-10-19", 5000, 1000, 200)
    _report(db, "2026-10-20", 6000, 1200, 240)
    cmp = ceo.period_compare("2026-10-20", "day")
    assert cmp["prev_fallback"] is False
    assert cmp["prev_start"] == "2026-10-19"
    assert cmp["metrics"]["revenue"]["delta_pct"] == 20.0


def test_overview_revenue_fallback(client):
    db, ceo = _db(), _ceo()
    _report(db, "2026-09-20", 5400, 1000, 200)
    _report(db, "2026-10-20", 5574, 1200, 500)
    ov = ceo.ceo_overview("2026-10-20")
    assert ov["rev_prev_fallback"] is True
    assert ov["rev_prev_date"] == "2026-09-20"
    assert ov["rev_change_pct"] == 3.2


# --- tự chọn 2 khoảng (period_compare_custom) ---------------------------------


def test_period_compare_custom_ranges(client):
    create_owner(client)
    db, ceo = _db(), _ceo()
    _report(db, "2026-10-20", 5574, 1200, 500)
    _report(db, "2026-09-20", 5400, 1000, 200)
    cmp = ceo.period_compare_custom(
        "2026-10-20", ("2026-10-20", "2026-10-20"), ("2026-09-20", "2026-09-20")
    )
    assert cmp["period"] == "custom"
    assert cmp["prev_fallback"] is False
    assert cmp["cur_name"] == "Kỳ đã chọn"
    assert cmp["prev_name"] == "kỳ so sánh đã chọn"
    assert cmp["cur_label"] == "20/10"
    assert cmp["prev_label"] == "20/09"
    assert cmp["metrics"]["revenue"] == {"cur": 5574, "prev": 5400, "delta_pct": 3.2}


def test_period_compare_custom_span_and_empty_prev(client):
    create_owner(client)
    db, ceo = _db(), _ceo()
    _report(db, "2026-10-19", 1000, 100, 50)
    _report(db, "2026-10-20", 2000, 200, 100)
    # Kỳ xem 2 ngày; kỳ so sánh không có dữ liệu -> prev/delta None
    cmp = ceo.period_compare_custom(
        "2026-10-20", ("2026-10-19", "2026-10-20"), ("2026-08-01", "2026-08-05")
    )
    assert cmp["metrics"]["revenue"]["cur"] == 3000
    assert cmp["metrics"]["revenue"]["prev"] is None
    assert cmp["metrics"]["revenue"]["delta_pct"] is None
    # cached variant: khoá gồm cả 2 khoảng, 2 khoảng khác nhau -> kết quả khác nhau
    a = ceo.cached_period_compare_custom(
        ("2026-10-19", "2026-10-20"), ("2026-08-01", "2026-08-05")
    )
    b = ceo.cached_period_compare_custom(
        ("2026-10-20", "2026-10-20"), ("2026-10-19", "2026-10-19")
    )
    assert a["metrics"]["revenue"]["cur"] == 3000
    assert b["metrics"]["revenue"] == {"cur": 2000, "prev": 1000, "delta_pct": 100.0}


def test_default_prev_range(client):
    ceo = _ceo()
    assert ceo.default_prev_range(("2026-10-20", "2026-10-20")) == (
        "2026-10-19",
        "2026-10-19",
    )
    assert ceo.default_prev_range(("2026-10-18", "2026-10-20")) == (
        "2026-10-15",
        "2026-10-17",
    )
    # Qua ranh giới tháng
    assert ceo.default_prev_range(("2026-11-01", "2026-11-02")) == (
        "2026-10-30",
        "2026-10-31",
    )


def test_ceo_route_custom_compare(client):
    create_owner(client)
    db = _db()
    _report(db, "2026-10-20", 5574, 1200, 500)
    _report(db, "2026-10-19", 5400, 1000, 200)
    # Bộ chọn khoảng mới: khoảng so sánh LUÔN là khoảng liền trước dài
    # bằng nhau (ở đây là chính ngày 19/10) — không còn ô chọn kỳ so
    # sánh riêng như chế độ Tự chọn cũ.
    r = client.get("/ceo?from=2026-10-20&to=2026-10-20")
    assert r.status_code == 200
    assert "+3.2%" in r.text
    assert "20/10/2026" in r.text  # nhãn khoảng trên nút chọn
    assert "19/10/2026" in r.text  # nhãn khoảng liền trước


def test_ceo_route_range_default_prev(client):
    create_owner(client)
    db = _db()
    _report(db, "2026-10-20", 6000, 1200, 500)
    _report(db, "2026-10-16", 5000, 1000, 200)
    # Khoảng xem 18/10-20/10 -> so sánh = 15/10-17/10 (liền trước, dài bằng)
    r = client.get("/ceo?from=2026-10-18&to=2026-10-20")
    assert r.status_code == 200
    assert "+20.0%" in r.text
    assert "15/10 - 17/10/2026" in r.text  # nhãn khoảng liền trước


def test_ceo_route_range_invalid_falls_back_to_default(client):
    create_owner(client)
    _seed_up(client)  # hôm nay 3tr + hôm qua 2.5tr -> mặc định 7 ngày qua tổng 5,500,000
    # to < from
    r = client.get("/ceo?from=2026-10-20&to=2026-10-10")
    assert r.status_code == 200
    assert "5,500,000" in r.text
    # ngày sai định dạng
    r = client.get("/ceo?from=abc&to=2026-10-10")
    assert r.status_code == 200
    assert "5,500,000" in r.text
    # khoảng dài hơn 366 ngày
    r = client.get("/ceo?from=2024-01-01&to=2026-10-10")
    assert r.status_code == 200
    assert "5,500,000" in r.text


# --- xem 1 ngày quá khứ = khoảng from=to -------------------------------------


def test_ceo_route_view_past_date(client):
    create_owner(client)
    db = _db()
    _report(db, "2026-09-20", 5400, 1000, 200)
    # Xem 1 ngày quá khứ = khoảng from=to=ngày đó (bộ chọn mới không còn
    # ô ?date= riêng; bảng 7 ngày neo tại ngày cuối khoảng = 20/09).
    r = client.get("/ceo?from=2026-09-20&to=2026-09-20")
    assert r.status_code == 200
    html = r.text
    assert "20/09/2026" in html  # nhãn khoảng trên nút chọn
    assert "5,400" in html  # doanh thu của đúng ngày 20/09
    assert "Doanh thu trong khoảng" in html


def test_ceo_route_future_or_bad_range_no_crash(client):
    create_owner(client)
    _seed_up(client)
    # Khoảng ở tương lai: không có dữ liệu -> thẻ hiện "No Data", không crash
    r = client.get("/ceo?from=2999-01-01&to=2999-01-07")
    assert r.status_code == 200
    assert "No Data" in r.text
    # Sai định dạng -> mặc định 7 ngày qua (tổng 3tr + 2.5tr)
    r = client.get("/ceo?from=20-09-2026&to=x")
    assert r.status_code == 200
    assert "5,500,000" in r.text


def test_ceo_route_date_custom_forbidden_for_plain_staff(client):
    create_owner(client)
    code = create_staff(client, "nv_date", perms=("can_view_products",))
    logout(client)
    activate(client, "nv_date", code)
    assert client.get("/ceo?from=2026-09-20&to=2026-09-20").status_code == 403
    assert client.get("/ceo?from=2026-10-01&to=2026-10-20").status_code == 403


# --- xem theo khoảng (range mode -> nay là cách xem duy nhất) ------------------


def test_range_headline_totals_and_delta(client):
    create_owner(client)
    db, ceo = _db(), _ceo()
    _report(db, "2026-08-15", 2000, 500, 100)  # nằm trong khoảng liền trước
    _report(db, "2026-09-20", 5400, 1000, 200)
    _report(db, "2026-10-20", 5574, 1200, 500)
    h = ceo.range_headline("2026-09-01", "2026-10-31")
    m = h["metrics"]
    assert m["revenue"]["cur"] == 10974  # 5.400 + 5.574
    assert m["ads_cost"]["cur"] == 700  # 200 + 500
    assert m["revenue"]["prev"] == 2000
    assert m["revenue"]["delta_pct"] == 448.7  # (10974-2000)/2000
    # Khoảng liền trước dài bằng nhau (61 ngày): 02/07 - 31/08
    assert (h["prev_start"], h["prev_end"]) == ("2026-07-02", "2026-08-31")
    assert h["prev_label"] == "02/07 – 31/08"  # noqa: RUF001
    for key in ("total", "tasks", "done", "pct", "overdue"):
        assert key in h["checklist"]


def test_range_headline_no_prev_data(client):
    create_owner(client)
    db, ceo = _db(), _ceo()
    _report(db, "2026-09-20", 5400, 1000, 200)
    _report(db, "2026-10-20", 5574, 1200, 500)
    h = ceo.range_headline("2026-09-01", "2026-10-31")
    assert h["metrics"]["revenue"]["cur"] == 10974
    assert h["metrics"]["revenue"]["prev"] is None
    assert h["metrics"]["revenue"]["delta_pct"] is None
    # Bản cached cho cùng kết quả
    h2 = ceo.cached_range_headline("2026-09-01", "2026-10-31")
    assert h2["metrics"]["revenue"]["cur"] == 10974
    assert h2["checklist"]["done"] == h["checklist"]["done"]


def test_ceo_route_range_mode(client):
    create_owner(client)
    db = _db()
    _report(db, "2026-09-20", 5400, 1000, 200)
    _report(db, "2026-10-20", 5574, 1200, 500)
    r = client.get("/ceo?from=2026-09-01&to=2026-10-31")
    assert r.status_code == 200
    html = r.text
    assert "01/09 - 31/10/2026" in html  # nhãn khoảng trên nút chọn
    assert "Doanh thu trong khoảng" in html
    assert "Chi phí ads trong khoảng" in html
    assert "Checklist trong khoảng" in html
    assert "10,974" in html  # tổng doanh thu cả khoảng: 5.400 + 5.574


def test_ceo_route_range_future_end_still_counts_today(client):
    create_owner(client)
    db, cl, ceo = _db(), _cl(), _ceo()
    today = cl.today_str()
    _report(db, today, 1_234_000, 100_000, 50_000)
    # Ngày kết thúc ở tương lai gần (khoảng vẫn <= 366 ngày): phần tương
    # lai chưa có số, tổng vẫn gồm đúng dữ liệu đã nhập tới hôm nay.
    r = client.get(f"/ceo?from={ceo._shift(today, -9)}&to={ceo._shift(today, 30)}")
    assert r.status_code == 200
    assert "1,234,000" in r.text


def test_ceo_route_range_invalid_falls_back(client):
    create_owner(client)
    cl, ceo = _cl(), _ceo()
    today = cl.today_str()
    urls = [
        "/ceo?from=2026-10-31&to=2026-09-01",  # to < from
        "/ceo?from=abc&to=2026-09-01",  # sai định dạng
        "/ceo?from=2026-09-01",  # thiếu to
        f"/ceo?from={ceo._shift(today, -400)}&to={today}",  # dài > 366 ngày
    ]
    for url in urls:
        r = client.get(url)
        assert r.status_code == 200, url
        # Rơi về mặc định 7 ngày qua: preset last7 active trên bộ chọn
        assert "rp-preset active" in r.text, url
        assert "Doanh thu trong khoảng" in r.text, url


def test_ceo_route_range_forbidden_for_plain_staff(client):
    create_owner(client)
    code = create_staff(client, "nv_range", perms=("can_view_products",))
    logout(client)
    activate(client, "nv_range", code)
    assert client.get("/ceo?from=2026-09-01&to=2026-10-31").status_code == 403


# --- nút chọn nhanh (preset) ---------------------------------------------------


def test_ceo_route_presets_present(client):
    create_owner(client)
    cl, ceo = _cl(), _ceo()
    today = cl.today_str()
    r = client.get("/ceo")
    assert r.status_code == 200
    html = r.text
    # 5 link preset với đúng ngày tính theo HÔM NAY thật
    assert f"/ceo?from={today}&to={today}" in html  # Hôm nay
    y = ceo._shift(today, -1)
    assert f"/ceo?from={y}&to={y}" in html  # Hôm qua
    assert f"/ceo?from={ceo._shift(today, -6)}&to={today}" in html  # 7 ngày qua
    assert f"/ceo?from={ceo._shift(today, -29)}&to={today}" in html  # 30 ngày qua
    assert f"/ceo?from={ceo._shift(today, -89)}&to={today}" in html  # 90 ngày qua
    for label in ("Hôm nay", "Hôm qua", "7 ngày qua", "30 ngày qua", "90 ngày qua"):
        assert label in html
    # Mặc định không có param -> preset 7 ngày qua đang active
    assert "rp-preset active" in html


def test_ceo_route_preset_last7_totals(client):
    create_owner(client)
    db, cl, ceo = _db(), _cl(), _ceo()
    today = cl.today_str()
    _report(db, today, 1_000_000, 100_000, 50_000)
    _report(db, ceo._shift(today, -3), 2_000_000, 200_000, 100_000)
    _report(db, ceo._shift(today, -10), 9_000_000, 900_000, 100_000)  # ngoài 7 ngày
    f7 = ceo._shift(today, -6)
    r = client.get(f"/ceo?from={f7}&to={today}")
    assert r.status_code == 200
    html = r.text
    assert "Doanh thu trong khoảng" in html
    assert "3,000,000" in html  # chỉ cộng 2 ngày trong 7 ngày qua
    # Preset "7 ngày qua" đang active trên bộ chọn
    assert "rp-preset active" in html
    assert f'href="/ceo?from={f7}&to={today}"' in html
