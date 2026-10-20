"""Dashboard CEO — so sánh theo kỳ (ngày/tuần/tháng) + biểu đồ doanh thu 30 ngày."""

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
    _seed_up(client)
    r = client.get("/ceo")
    assert r.status_code == 200
    html = r.text
    assert "So sánh theo kỳ" in html
    assert "delta-up" in html
    assert "+20.0%" in html
    # Đồng hồ + biểu đồ 30 ngày
    assert "ceoClock" in html
    assert "giờ Việt Nam" in html
    assert "ceoRevChart" in html
    assert "Doanh thu 30 ngày gần nhất" in html


def test_ceo_route_delta_down_class(client):
    create_owner(client)
    db, cl, ceo = _db(), _cl(), _ceo()
    today = cl.today_str()
    _report(db, today, 2_000_000, 400_000, 200_000)
    _report(db, ceo._shift(today, -1), 2_500_000, 500_000, 250_000)
    r = client.get("/ceo")
    assert r.status_code == 200
    assert "delta-down" in r.text
    assert "-20.0%" in r.text


def test_ceo_route_period_switch(client):
    create_owner(client)
    _seed_up(client)
    r = client.get("/ceo?period=week")
    assert r.status_code == 200
    assert "Tuần này" in r.text
    r = client.get("/ceo?period=month")
    assert r.status_code == 200
    assert "Tháng này" in r.text
    # period bậy → mặc định day
    r = client.get("/ceo?period=quy")
    assert r.status_code == 200
    assert "Hôm nay:" in r.text


def test_ceo_route_period_forbidden_for_plain_staff(client):
    create_owner(client)
    code = create_staff(client, "nv_period", perms=("can_view_products",))
    logout(client)
    activate(client, "nv_period", code)
    assert client.get("/ceo?period=week").status_code == 403
    assert client.get("/ceo?period=month").status_code == 403


def test_ceo_route_period_ok_for_leader(client):
    create_owner(client)
    code = create_staff(
        client, "nv_lead2", perms=("can_view_products", "can_checklist_leader")
    )
    logout(client)
    activate(client, "nv_lead2", code)
    r = client.get("/ceo?period=week")
    assert r.status_code == 200
    assert "Tuần này" in r.text


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
    _report(db, "2026-09-20", 5400, 1000, 200)
    r = client.get(
        "/ceo?period=custom&from=2026-10-20&to=2026-10-20"
        "&cfrom=2026-09-20&cto=2026-09-20"
    )
    assert r.status_code == 200
    assert "Kỳ đã chọn" in r.text
    assert "kỳ so sánh đã chọn" in r.text
    assert "+3.2%" in r.text
    # 4 ô date được điền sẵn đúng giá trị đã chọn
    assert 'name="from" value="2026-10-20"' in r.text
    assert 'name="cfrom" value="2026-09-20"' in r.text


def test_ceo_route_custom_default_prev(client):
    create_owner(client)
    db = _db()
    _report(db, "2026-10-20", 6000, 1200, 500)
    _report(db, "2026-10-16", 5000, 1000, 200)
    # Không truyền cfrom/cto -> kỳ so sánh mặc định = 15/10-17/10 (liền trước, dài bằng)
    r = client.get("/ceo?period=custom&from=2026-10-18&to=2026-10-20")
    assert r.status_code == 200
    assert "Kỳ đã chọn" in r.text
    assert "+20.0%" in r.text
    assert 'name="cfrom" value="2026-10-15"' in r.text
    assert 'name="cto" value="2026-10-17"' in r.text


def test_ceo_route_custom_invalid_falls_back_to_day(client):
    create_owner(client)
    _seed_up(client)
    # to < from
    r = client.get("/ceo?period=custom&from=2026-10-20&to=2026-10-10")
    assert r.status_code == 200
    assert "Hôm nay:" in r.text
    # ngày sai định dạng
    r = client.get("/ceo?period=custom&from=abc&to=2026-10-10")
    assert r.status_code == 200
    assert "Hôm nay:" in r.text
    # khoảng dài hơn 366 ngày
    r = client.get("/ceo?period=custom&from=2024-01-01&to=2026-10-10")
    assert r.status_code == 200
    assert "Hôm nay:" in r.text
    # kỳ so sánh đảo (cto < cfrom)
    r = client.get(
        "/ceo?period=custom&from=2026-10-20&to=2026-10-20"
        "&cfrom=2026-09-20&cto=2026-09-19"
    )
    assert r.status_code == 200
    assert "Hôm nay:" in r.text


# --- chọn ngày xem ------------------------------------------------------------


def test_ceo_route_view_past_date(client):
    create_owner(client)
    db = _db()
    _report(db, "2026-09-20", 5400, 1000, 200)
    r = client.get("/ceo?date=2026-09-20")
    assert r.status_code == 200
    html = r.text
    assert "Đang xem ngày" in html
    assert "20/09/2026" in html
    assert "5,400" in html  # doanh thu của đúng ngày 20/09
    assert "Doanh thu 20/09" in html  # nhãn thẻ theo ngày xem
    assert "Doanh thu hôm nay" not in html
    assert "Về hôm nay" in html
    # Link chuyển kỳ giữ nguyên ngày đang xem
    assert "period=week&amp;date=2026-09-20" in html


def test_ceo_route_future_or_bad_date_uses_today(client):
    create_owner(client)
    _seed_up(client)
    r = client.get("/ceo?date=2999-01-01")  # tương lai -> hôm nay
    assert r.status_code == 200
    assert "Đang xem ngày" not in r.text
    assert "Doanh thu hôm nay" in r.text
    r = client.get("/ceo?date=20-09-2026")  # sai định dạng -> hôm nay
    assert r.status_code == 200
    assert "Đang xem ngày" not in r.text
    assert "Doanh thu hôm nay" in r.text


def test_ceo_route_date_custom_forbidden_for_plain_staff(client):
    create_owner(client)
    code = create_staff(client, "nv_date", perms=("can_view_products",))
    logout(client)
    activate(client, "nv_date", code)
    assert client.get("/ceo?date=2026-09-20").status_code == 403
    assert (
        client.get("/ceo?period=custom&from=2026-10-01&to=2026-10-20").status_code
        == 403
    )
