"""Bộ chọn khoảng ngày kiểu Shopee Ads (app/rangeview.py) + 4 trang dùng:
Dashboard CEO, GMV Max, KPI, Báo cáo ngày — cùng 1 hợp đồng ?from&to."""

import csv
import io
from datetime import datetime, timedelta

from conftest import create_owner, create_staff


def _db():
    from app import database as db

    return db


def _cl():
    from app import checklist

    return checklist


def _rv():
    from app import rangeview

    return rangeview


def _d(iso):
    return datetime.strptime(iso, "%Y-%m-%d").date()


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


# --- resolve_range: preset + khoảng liền trước ---------------------------------


def test_preset_resolution_math(client):
    rv = _rv()
    today = "2026-10-23"
    cases = {
        "today": (("2026-10-23", "2026-10-23"), ("2026-10-22", "2026-10-22"), 1),
        "yesterday": (("2026-10-22", "2026-10-22"), ("2026-10-21", "2026-10-21"), 1),
        "last7": (("2026-10-17", "2026-10-23"), ("2026-10-10", "2026-10-16"), 7),
        "last30": (("2026-09-24", "2026-10-23"), ("2026-08-25", "2026-09-23"), 30),
        "last90": (("2026-07-26", "2026-10-23"), ("2026-04-27", "2026-07-25"), 90),
    }
    for key, (cur, prev, days) in cases.items():
        rng = rv.resolve_range({"from": cur[0], "to": cur[1]}, today)
        assert rng["preset"] == key, key
        assert rng["preset_label"] is not None
        assert (rng["cur_start"], rng["cur_end"]) == cur
        assert (rng["prev_start"], rng["prev_end"]) == prev
        assert rng["days"] == days
        assert rng["num_days"] == days


def test_last7_prev_block_across_month_boundary(client):
    rv = _rv()
    # 02/11/2026: 7 ngày qua vắt qua ranh giới tháng (27/10 - 02/11),
    # khoảng liền trước cũng trọn 7 ngày 20/10 - 26/10.
    rng = rv.resolve_range({}, "2026-11-02")  # không param -> mặc định last7
    assert rng["preset"] == "last7"
    assert (rng["cur_start"], rng["cur_end"]) == ("2026-10-27", "2026-11-02")
    assert (rng["prev_start"], rng["prev_end"]) == ("2026-10-20", "2026-10-26")
    assert rng["days"] == 7
    # Nhãn kiểu Shopee trên nút chọn
    assert rng["label_cur"] == "27/10 - 02/11/2026"
    assert rng["label_prev"] == "20/10 - 26/10/2026"


def test_resolve_range_custom(client):
    rv = _rv()
    rng = rv.resolve_range(
        {"from": "2026-10-01", "to": "2026-10-10"}, "2026-10-23"
    )
    assert rng["preset"] == "custom"
    assert rng["preset_label"] is None
    assert rng["cur_name"] == "Kỳ đã chọn"
    assert rng["days"] == 10
    assert (rng["prev_start"], rng["prev_end"]) == ("2026-09-21", "2026-09-30")
    assert rng["label_cur"] == "01/10 - 10/10/2026"
    # Khoảng 1 ngày -> nhãn chỉ 1 ngày đầy đủ
    rng1 = rv.resolve_range({"from": "2026-10-05", "to": "2026-10-05"}, "2026-10-23")
    assert rng1["label_cur"] == "05/10/2026"
    assert rng1["days"] == 1
    # Danh sách preset cho panel chọn nhanh: đủ 5 mốc, đúng thứ tự
    keys = [p["key"] for p in rng["presets"]]
    assert keys == ["today", "yesterday", "last7", "last30", "last90"]
    labels = [p["label"] for p in rng["presets"]]
    assert labels == ["Hôm nay", "Hôm qua", "7 ngày qua", "30 ngày qua", "90 ngày qua"]


def test_resolve_range_invalid_falls_back_to_default(client):
    rv = _rv()
    cases = [
        {"from": "2026-10-20", "to": "2026-10-10"},  # to < from
        {"from": "abc", "to": "2026-10-10"},  # sai định dạng
        {"from": "2026-13-01", "to": "2026-10-10"},  # tháng 13
        {"from": "2026-10-01"},  # thiếu to
        {"to": "2026-10-10"},  # thiếu from
        {},  # không param nào
        None,
        {"from": "2025-01-01", "to": "2026-10-23"},  # dài hơn 366 ngày
    ]
    for params in cases:
        rng = rv.resolve_range(params, "2026-10-23")
        assert rng["preset"] == "last7", params
        assert (rng["cur_start"], rng["cur_end"]) == ("2026-10-17", "2026-10-23")
    # Mặc định riêng của Báo cáo ngày: 30 ngày qua
    rng = rv.resolve_range(None, "2026-10-23", default="last30")
    assert rng["preset"] == "last30"
    assert (rng["cur_start"], rng["cur_end"]) == ("2026-09-24", "2026-10-23")
    # Đúng 366 ngày vẫn hợp lệ (không bị coi là sai)
    rng = rv.resolve_range({"from": "2025-10-23", "to": "2026-10-23"}, "2026-10-23")
    assert rng["preset"] == "custom"
    assert rng["days"] == 366


# --- markup bộ chọn trên cả 4 trang --------------------------------------------


def test_picker_markup_on_all_pages(client):
    create_owner(client)
    for url in ("/ceo", "/gmv", "/kpi", "/bao-cao"):
        r = client.get(url)
        assert r.status_code == 200, url
        html = r.text
        assert "data-rp" in html, url
        assert "data-rp-panel" in html, url
        assert 'data-rp-apply' in html, url
        for label in ("Hôm nay", "Hôm qua", "7 ngày qua", "30 ngày qua", "90 ngày qua"):
            assert label in html, (url, label)
        assert "Áp dụng" in html, url
        assert "Đóng" in html, url


def test_gmv_picker_preserves_product_filter(client):
    create_owner(client)
    db = _db()
    pid = db.gmv_create_product("SP RP")
    r = client.get(f"/gmv?product_id={pid}")
    assert r.status_code == 200
    # Bộ chọn mang theo product_id đang xem khi chuyển khoảng
    assert f"product_id={pid}" in r.text
    assert "data-rp" in r.text


def test_kpi_export_link_carries_range(client):
    create_owner(client)
    r = client.get("/kpi?from=2026-10-05&to=2026-10-06")
    assert r.status_code == 200
    assert 'href="/kpi/export?from=2026-10-05&amp;to=2026-10-06"' in r.text or (
        'href="/kpi/export?from=2026-10-05&to=2026-10-06"' in r.text
    )


# --- hành vi theo khoảng trên từng trang ---------------------------------------


def test_ceo_default_range_renders_delta_for_seeded_data(client):
    create_owner(client)
    db, cl = _db(), _cl()
    today = cl.today_str()
    d = _d(today)
    # 7 ngày qua: mỗi ngày 1.000.000đ; 7 ngày liền trước: mỗi ngày 500.000đ
    for i in range(7):
        _report(db, (d - timedelta(days=i)).isoformat(), 1_000_000, 100_000, 50_000)
        _report(
            db, (d - timedelta(days=7 + i)).isoformat(), 500_000, 50_000, 50_000
        )
    r = client.get("/ceo")  # mặc định 7 ngày qua
    assert r.status_code == 200
    assert "7,000,000" in r.text  # tổng doanh thu cả khoảng
    assert "+100.0%" in r.text
    assert "delta-up" in r.text


def test_daily_page_range_totals_only_count_inside_range(client):
    create_owner(client)
    db = _db()
    _report(db, "2026-10-05", 1_000_000, 200_000, 100_000)  # trong khoảng
    _report(db, "2026-10-06", 3_000_000, 600_000, 200_000)  # trong khoảng
    _report(db, "2026-10-20", 9_000_000, 900_000, 100_000)  # ngoài khoảng
    r = client.get("/bao-cao?from=2026-10-01&to=2026-10-10")
    assert r.status_code == 200
    html = r.text
    # Tổng khoảng: doanh thu 4.000.000đ, chi phí 300.000đ, ROAS = 800k/300k = 2.67
    assert "4.000.000đ" in html
    assert "300.000đ" in html
    assert "2.67" in html
    # Ngày ngoài khoảng không xuất hiện trong danh sách
    assert "9.000.000" not in html
    assert "20/10/2026" not in html


def test_kpi_csv_respects_range(client):
    create_owner(client)
    db, cl = _db(), _cl()
    create_staff(client, "nv_rp", perms=("can_view_products",))
    staff = db.get_user_by_username("nv_rp")
    # Chỉ giữ 1 mẫu việc của nv_rp để số liệu gọn
    for t in db.cl_template_list():
        db.cl_template_update(t["id"], {"is_active": 0})
    db.cl_template_create(
        {
            "group_name": "Test",
            "title": "Việc RP",
            "sort": 10,
            "due_time": "09:00",
            "assignee_id": staff["id"],
            "shop_id": None,
            "is_active": 1,
        }
    )
    for day in ("2026-10-05", "2026-10-06"):
        cl.generate_for_date(day)
    items = db.cl_item_list("2026-10-05", assignee_id=staff["id"])
    assert len(items) == 1
    db.cl_item_update(items[0]["id"], {"status": "done", "completed_by": "test"})

    def _csv_rows(url):
        r = client.get(url)
        assert r.status_code == 200
        text = r.content.decode("utf-8-sig")
        return {row[0]: row for row in csv.reader(io.StringIO(text)) if row}

    # Chỉ ngày 05/10: 1 việc, xong 1 -> 100%
    rows = _csv_rows("/kpi/export?from=2026-10-05&to=2026-10-05")
    assert rows["nv_rp"][1:4] == ["1", "1", "100.0"]
    # Chỉ ngày 06/10: 1 việc, xong 0 -> 0%
    rows = _csv_rows("/kpi/export?from=2026-10-06&to=2026-10-06")
    assert rows["nv_rp"][1:4] == ["1", "0", "0.0"]
    # Khoảng không có việc nào: toàn team 0 việc
    rows = _csv_rows("/kpi/export?from=2026-11-01&to=2026-11-07")
    assert rows["TOÀN TEAM"][1] == "0"
    # Trang KPI cũng theo đúng khoảng
    r = client.get("/kpi?from=2026-10-05&to=2026-10-05")
    assert r.status_code == 200
    assert "100.0%" in r.text
