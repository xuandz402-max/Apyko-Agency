"""Dashboard CEO — tổng hợp 1 màn hình từ các module hiện có.

Chỉ đọc số thật đã được nhân sự nhập ở các module khác, không có bảng riêng:
- Doanh thu / chi phí ads / ROAS: Báo cáo ngày (daily_reports, qua calc_daily).
- GMV quảng cáo: GMV Max Shopee (gmv_entries, qua calc_gmv; toàn bộ tiền tệ bằng VNĐ).
- Checklist hôm nay: Daily Checklist (checklist.board_stats).

Ngưỡng cảnh báo mặc định (chỉnh trong code này):
- ROAS_WARN = 2.0: entry GMV mới nhất có ROAS dưới mức này → cảnh báo.
- STALE_DAYS = 3: sản phẩm không có entry nào trong 3 ngày gần nhất → cảnh báo.

Tốc độ: toàn bộ dữ liệu nạp bằng 5 câu query cố định (báo cáo ngày 1 query
cho mọi ngày cần xem, entry GMV 1 query cho mọi sản phẩm, checklist qua
board_stats). cached_overview() nhớ kết quả 60 giây vì trang chỉ đọc.

So sánh theo kỳ (period_compare): Doanh thu / Chi phí ads / ROAS (từ Báo
cáo ngày) và GMV quảng cáo VNĐ (từ GMV Max) của kỳ này so với kỳ trước —
Ngày: hôm nay vs hôm qua (hôm qua trống số thì lùi về ngày có số gần
nhất); Tuần: TRỌN tuần lịch thứ Hai -> Chủ Nhật vs trọn tuần liền trước;
Tháng: TRỌN tháng lịch vs trọn tháng liền trước. Chế độ Tự chọn
(period_compare_custom): 2 khoảng ngày tùy ý do người dùng điền. Kỳ
trước = 0 hoặc thiếu dữ liệu -> delta = None (giao diện hiện "—", không
bịa %). % tăng/giảm trên trang dùng màu xanh lá #15803D / đỏ #DC2626
(class .delta-up/.delta-down) — ngoại lệ màu duy nhất ngoài theme đen
trắng, do chủ shop chốt riêng cho số tăng/giảm.

Xem theo khoảng tự do (range_headline): người dùng chọn Từ ngày - Đến
ngày bất kỳ -> 4 thẻ chính hiện TỔNG cả khoảng (delta % so với khoảng
liền trước dài bằng nhau), thẻ checklist cộng dồn cả khoảng qua
checklist.board_range_stats.
"""

import threading
import time
from datetime import datetime, timedelta

from . import checklist
from . import database as db
from .daily import calc_daily
from .gmv import calc_gmv

ROAS_WARN = 2.0
STALE_DAYS = 3

OVERVIEW_CACHE_TTL = 60  # giây — dữ liệu tổng hợp chấp nhận trễ tối đa 1 phút
_overview_cache: dict[str, tuple[float, dict]] = {}
_overview_lock = threading.Lock()


def _shift(date_str: str, days: int) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d").date() + timedelta(days=days)
    return d.isoformat()


def _summary_from(report: dict | None, date_str: str) -> dict | None:
    """Tóm tắt 1 ngày từ dòng Báo cáo ngày đã nạp sẵn; None nếu chưa nhập."""
    if report is None:
        return None
    calc = calc_daily(report)
    return {
        "date": date_str,
        "total_rev": calc["total_rev"],
        "ads_cost": round(float(report.get("ad_cost") or 0)),
        "roas": calc["roas"],
    }


def ceo_overview(today: str) -> dict:
    """Tổng hợp toàn cảnh cho ngày `today` ('YYYY-MM-DD', giờ Việt Nam)."""
    # ----- doanh thu (Báo cáo ngày): 1 query cho mọi ngày cần xem -----
    reports = {r["date"]: r for r in db.daily_list()}
    rev_today = _summary_from(reports.get(today), today)
    yesterday = _shift(today, -1)
    rev_yesterday = _summary_from(reports.get(yesterday), yesterday)
    rev_prev_date = yesterday
    rev_prev_fallback = False
    if rev_yesterday is None and rev_today is not None:
        # Hôm qua chưa nhập -> lùi về ngày có báo cáo gần nhất trước hôm nay
        # để vẫn so sánh được (giao diện ghi rõ là ngày có số gần nhất).
        earlier = [d for d in reports if d < today]
        if earlier:
            rev_prev_date = max(earlier)
            rev_yesterday = _summary_from(reports.get(rev_prev_date), rev_prev_date)
            rev_prev_fallback = True
    rev_change_pct = None
    if rev_today is not None and rev_yesterday is not None and rev_yesterday["total_rev"] != 0:
        rev_change_pct = round(
            (rev_today["total_rev"] - rev_yesterday["total_rev"])
            / rev_yesterday["total_rev"]
            * 100,
            1,
        )
    revenue_7d = []
    for back in range(6, -1, -1):
        day = _shift(today, -back)
        summary = _summary_from(reports.get(day), day)
        if summary is None:
            summary = {
                "date": day,
                "total_rev": None,
                "ads_cost": None,
                "roas": None,
            }
        revenue_7d.append(summary)

    # ----- GMV Max: tổng hợp hôm nay + cảnh báo theo sản phẩm -----
    # 1 query entry cho mọi sản phẩm (thay cho query lặp theo sản phẩm);
    # gmv_all_entries đã sắp date ASC trong từng sản phẩm như gmv_list_entries.
    stale_cutoff = _shift(today, -(STALE_DAYS - 1))  # ngày cũ nhất còn "gần đây"
    gmv_rev = 0.0
    gmv_cost = 0.0
    gmv_entries_today = 0
    product_alerts = []
    entries_by_product: dict[int, list] = {}
    for entry in db.gmv_all_entries():
        entries_by_product.setdefault(entry["product_id"], []).append(entry)
    for product in db.gmv_list_products():
        entries = entries_by_product.get(product["id"], [])
        for entry in entries:
            if entry["date"] == today:
                gmv_rev += float(entry.get("revenue_vnd") or 0)
                gmv_cost += float(entry.get("ad_cost") or 0)
                gmv_entries_today += 1
        latest = entries[-1] if entries else None
        if latest is None or latest["date"] < stale_cutoff:
            product_alerts.append(
                {
                    "product_name": product["name"],
                    "note": "chưa có dữ liệu gần đây",
                    "roas": None,
                    "entry_date": latest["date"] if latest else None,
                }
            )
        else:
            roas = calc_gmv(latest)["roas"]
            if roas is not None and roas < ROAS_WARN:
                product_alerts.append(
                    {
                        "product_name": product["name"],
                        "note": f"ROAS dưới ngưỡng {ROAS_WARN:g}",
                        "roas": roas,
                        "entry_date": latest["date"],
                    }
                )
    gmv_today = {
        "entry_count": gmv_entries_today,
        "revenue_vnd": round(gmv_rev, 2),
        "ad_cost_vnd": round(gmv_cost, 2),
        "roas": round(gmv_rev / gmv_cost, 2) if gmv_cost != 0 else None,
    }

    # ----- checklist hôm nay -----
    stats = checklist.board_stats(today)
    tasks = stats["total"] - stats["cancelled"]  # việc thực tế cần làm
    checklist_today = {
        "total": stats["total"],
        "tasks": tasks,
        "done": stats["done"],
        "unfinished": stats["unfinished"],
        "overdue": stats["overdue"],
        "pct": round(stats["done"] * 100 / tasks, 1) if tasks > 0 else 0.0,
        "per_user": stats["per_user"],
        "overdue_users": stats["overdue_users"],
    }

    # ----- cảnh báo gộp -----
    alerts = []
    for u in stats["overdue_users"]:
        alerts.append(
            {
                "level": "red",
                "title": f"{u['name']} còn {u['overdue']} việc quá hạn",
                "detail": "Việc checklist hôm nay chưa hoàn thành đúng hạn.",
                "link": f"/checklist?date={today}&assignee={u['user_id']}",
            }
        )
    for alert in product_alerts:
        if alert["roas"] is not None:
            detail = (
                f"ROAS {alert['roas']} ở entry ngày {alert['entry_date']} — "
                f"dưới ngưỡng cảnh báo {ROAS_WARN:g}."
            )
        elif alert["entry_date"]:
            detail = (
                f"Entry gần nhất từ ngày {alert['entry_date']} — "
                f"chưa có dữ liệu trong {STALE_DAYS} ngày gần nhất."
            )
        else:
            detail = f"Chưa từng có dữ liệu quảng cáo trong {STALE_DAYS} ngày gần nhất."
        alerts.append(
            {
                "level": "amber",
                "title": f"GMV Max: {alert['product_name']} — {alert['note']}",
                "detail": detail,
                "link": "/gmv",
            }
        )
    if rev_today is None:
        alerts.append(
            {
                "level": "amber",
                "title": "Chưa nhập Báo cáo ngày hôm nay",
                "detail": "Doanh thu hôm nay chưa được cập nhật vào Báo cáo ngày.",
                "link": "/bao-cao",
            }
        )

    return {
        "today": today,
        "has_report_today": rev_today is not None,
        "revenue_today": rev_today,
        "revenue_yesterday_total": (
            rev_yesterday["total_rev"] if rev_yesterday is not None else None
        ),
        "rev_change_pct": rev_change_pct,
        "rev_prev_date": rev_prev_date,
        "rev_prev_fallback": rev_prev_fallback,
        "revenue_7d": revenue_7d,
        "gmv_today": gmv_today,
        "product_alerts": product_alerts,
        "checklist_today": checklist_today,
        "alerts": alerts,
    }


def cached_overview(today: str) -> dict:
    """ceo_overview() với bộ nhớ đệm in-process 60 giây.

    Trang /ceo chỉ đọc dữ liệu tổng hợp của NGÀY (không phân biệt người xem
    — owner/leader/admin checklist đều thấy cùng số liệu), nên trễ tối đa
    60 giây là chấp nhận được và giảm mạnh số vòng hỏi DB khi mở lại trang.
    Thread-safe: lock bao quanh đọc/ghi cache.
    """
    now = time.monotonic()
    with _overview_lock:
        entry = _overview_cache.get(today)
        if entry is not None and entry[0] > now:
            return entry[1]
    data = ceo_overview(today)
    with _overview_lock:
        _overview_cache[today] = (now + OVERVIEW_CACHE_TTL, data)
        for key, (exp, _) in list(_overview_cache.items()):
            if key != today and exp <= now:
                del _overview_cache[key]
    return data


# -------------------- so sánh theo kỳ + doanh thu 30 ngày --------------------

PERIODS = ("day", "week", "month")
_PERIOD_NAMES = {
    "day": ("Hôm nay", "hôm qua"),
    "week": ("Tuần này", "tuần trước"),
    "month": ("Tháng này", "tháng trước"),
}

_period_cache: dict[tuple, tuple[float, dict]] = {}
_period_lock = threading.Lock()


def _to_date(date_str: str):
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def period_ranges(today: str, period: str) -> tuple[tuple[str, str], tuple[str, str]]:
    """Khoảng ((kỳ này), (kỳ trước)) cho day/week/month.

    - day:   hôm nay vs hôm qua.
    - week:  TRỌN tuần lịch thứ Hai -> Chủ Nhật của tuần chứa hôm nay vs
             trọn tuần liền trước (ngày chưa tới trong tuần này chưa có số
             thì tổng chỉ gồm các ngày đã nhập — đúng ý user chốt 20/10).
    - month: TRỌN tháng lịch ngày 1 -> cuối tháng vs trọn tháng liền trước.
    period không hợp lệ -> day.
    """
    if period not in PERIODS:
        period = "day"
    d = _to_date(today)
    if period == "week":
        monday = d - timedelta(days=d.weekday())
        sunday = monday + timedelta(days=6)
        prev_monday = monday - timedelta(days=7)
        prev_sunday = prev_monday + timedelta(days=6)
        cur = (monday.isoformat(), sunday.isoformat())
        prev = (prev_monday.isoformat(), prev_sunday.isoformat())
        return cur, prev
    if period == "month":
        first = d.replace(day=1)
        next_first = (first + timedelta(days=32)).replace(day=1)
        last = next_first - timedelta(days=1)
        prev_last = first - timedelta(days=1)
        prev_first = prev_last.replace(day=1)
        cur = (first.isoformat(), last.isoformat())
        prev = (prev_first.isoformat(), prev_last.isoformat())
        return cur, prev
    prev_day = d - timedelta(days=1)
    return (d.isoformat(), d.isoformat()), (prev_day.isoformat(), prev_day.isoformat())


def _fmt_dm(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}"


def _range_label(start: str, end: str) -> str:
    return _fmt_dm(start) if start == end else f"{_fmt_dm(start)} – {_fmt_dm(end)}"  # noqa: RUF001


def _aggregate(reports: dict, entries: list, start: str, end: str) -> dict:
    """Cộng dồn 1 khoảng ngày từ báo cáo ngày + entry GMV đã nạp sẵn.

    Ngày không có báo cáo thì bỏ qua (không tính là 0); cả khoảng không có
    ngày nào có báo cáo -> revenue/ads_cost/roas = None. GMV tương tự:
    không entry nào trong khoảng -> None.
    """
    revenue = 0
    ads_cost = 0.0
    ad_gmv = 0.0
    has_report = False
    day = _to_date(start)
    last = _to_date(end)
    while day <= last:
        report = reports.get(day.isoformat())
        if report is not None:
            has_report = True
            revenue += calc_daily(report)["total_rev"]
            ads_cost += float(report.get("ad_cost") or 0)
            ad_gmv += float(report.get("ad_gmv") or 0)
        day += timedelta(days=1)
    gmv_vnd_sum = 0.0
    has_gmv = False
    for entry in entries:
        if start <= entry["date"] <= end:
            has_gmv = True
            gmv_vnd_sum += float(entry.get("revenue_vnd") or 0)
    return {
        "revenue": revenue if has_report else None,
        "ads_cost": round(ads_cost) if has_report else None,
        "roas": round(ad_gmv / ads_cost, 2) if has_report and ads_cost != 0 else None,
        "gmv_vnd": round(gmv_vnd_sum) if has_gmv else None,
    }


def _with_delta(cur, prev) -> dict:
    """% thay đổi; kỳ trước = 0 hoặc thiếu 1 trong 2 kỳ -> None (hiện "—")."""
    delta = None
    if cur is not None and prev is not None and prev != 0:
        delta = round((cur - prev) / prev * 100, 1)
    return {"cur": cur, "prev": prev, "delta_pct": delta}


def period_compare(today: str, period: str) -> dict:
    """So sánh 4 chỉ số giữa kỳ này và kỳ trước (nạp dữ liệu 1 lần)."""
    if period not in PERIODS:
        period = "day"
    cur_range, prev_range = period_ranges(today, period)
    reports = {r["date"]: r for r in db.daily_list()}
    entries = db.gmv_all_entries()
    cur = _aggregate(reports, entries, *cur_range)
    prev = _aggregate(reports, entries, *prev_range)
    prev_fallback = False
    if period == "day" and prev["revenue"] is None and prev["gmv_vnd"] is None:
        # Hôm qua không có bất kỳ số nào -> lùi về ngày có số gần nhất trước
        # kỳ này (báo cáo ngày hoặc entry GMV) để vẫn có mốc so sánh.
        data_dates = {d for d in reports if d < cur_range[0]}
        data_dates |= {e["date"] for e in entries if e["date"] < cur_range[0]}
        if data_dates:
            fb_day = max(data_dates)
            prev_range = (fb_day, fb_day)
            prev = _aggregate(reports, entries, *prev_range)
            prev_fallback = True
    cur_name, prev_name = _PERIOD_NAMES[period]
    if prev_fallback:
        prev_name = "(ngày có số gần nhất)"
    return {
        "period": period,
        "cur_start": cur_range[0],
        "cur_end": cur_range[1],
        "prev_start": prev_range[0],
        "prev_end": prev_range[1],
        "cur_name": cur_name,
        "prev_name": prev_name,
        "cur_label": _range_label(*cur_range),
        "prev_label": _range_label(*prev_range),
        "prev_fallback": prev_fallback,
        "metrics": {
            key: _with_delta(cur[key], prev[key])
            for key in ("revenue", "ads_cost", "roas", "gmv_vnd")
        },
    }


def default_prev_range(cur_range: tuple[str, str]) -> tuple[str, str]:
    """Khoảng liền trước DÀI BẰNG cur_range, kết thúc ngay trước cur_start.

    Dùng làm kỳ so sánh mặc định cho chế độ Tự chọn ở Dashboard CEO khi
    người dùng chưa tự điền kỳ so sánh.
    """
    start = _to_date(cur_range[0])
    length = (_to_date(cur_range[1]) - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    return prev_start.isoformat(), prev_end.isoformat()


def period_compare_custom(today: str, cur_range, prev_range) -> dict:
    """So sánh 4 chỉ số giữa 2 khoảng ngày TÙY Ý (chế độ Tự chọn).

    `today` là ngày neo (giữ chữ ký đồng nhất với period_compare) — hai
    khoảng là tuyệt đối và đã được validate ở route (định dạng, thứ tự,
    độ dài). KHÔNG áp fallback "ngày có số gần nhất": fallback chỉ dành
    cho kỳ Ngày. Ngày trong khoảng chưa có số thì bỏ qua như _aggregate.
    """
    reports = {r["date"]: r for r in db.daily_list()}
    entries = db.gmv_all_entries()
    cur = _aggregate(reports, entries, *cur_range)
    prev = _aggregate(reports, entries, *prev_range)
    return {
        "period": "custom",
        "cur_start": cur_range[0],
        "cur_end": cur_range[1],
        "prev_start": prev_range[0],
        "prev_end": prev_range[1],
        "cur_name": "Kỳ đã chọn",
        "prev_name": "kỳ so sánh đã chọn",
        "cur_label": _range_label(*cur_range),
        "prev_label": _range_label(*prev_range),
        "prev_fallback": False,
        "metrics": {
            key: _with_delta(cur[key], prev[key])
            for key in ("revenue", "ads_cost", "roas", "gmv_vnd")
        },
    }


def revenue_series(today: str, days: int = 30) -> dict:
    """Doanh thu từng ngày trong `days` ngày gần nhất (gồm hôm nay).

    Ngày chưa nhập Báo cáo ngày -> None (biểu đồ để trống, không vẽ 0).
    """
    reports = {r["date"]: r for r in db.daily_list()}
    labels: list[str] = []
    values: list[int | None] = []
    d0 = _to_date(today)
    for back in range(days - 1, -1, -1):
        day = (d0 - timedelta(days=back)).isoformat()
        labels.append(day)
        report = reports.get(day)
        values.append(calc_daily(report)["total_rev"] if report is not None else None)
    return {"labels": labels, "revenue": values}


def invalidate_caches() -> None:
    """Xoá mọi cache tổng hợp CEO — gọi sau khi ghi Báo cáo ngày / GMV để
    trang CEO phản ánh số liệu mới ngay, không đợi hết TTL 60 giây."""
    with _overview_lock:
        _overview_cache.clear()
    with _period_lock:
        _period_cache.clear()


def _ttl_get(key: tuple, producer) -> dict:
    """Cache TTL dùng chung cho so sánh kỳ + series (khoá theo (loại, ngày, kỳ))."""
    now = time.monotonic()
    with _period_lock:
        entry = _period_cache.get(key)
        if entry is not None and entry[0] > now:
            return entry[1]
    data = producer()
    with _period_lock:
        _period_cache[key] = (now + OVERVIEW_CACHE_TTL, data)
        for k, (exp, _) in list(_period_cache.items()):
            if k != key and exp <= now:
                del _period_cache[k]
    return data


def cached_period_compare(today: str, period: str) -> dict:
    """period_compare() với cache 60 giây, khoá theo (ngày, kỳ)."""
    if period not in PERIODS:
        period = "day"
    return _ttl_get(
        ("period", today, period), lambda: period_compare(today, period)
    )


def cached_period_compare_custom(cur_range, prev_range) -> dict:
    """period_compare_custom() với cache 60 giây, khoá gồm cả 2 khoảng."""
    key = ("period_custom", cur_range[0], cur_range[1], prev_range[0], prev_range[1])
    return _ttl_get(
        key, lambda: period_compare_custom(cur_range[0], cur_range, prev_range)
    )


def cached_revenue_series(today: str) -> dict:
    """revenue_series(30 ngày) với cache 60 giây, khoá theo ngày."""
    return _ttl_get(("series30", today), lambda: revenue_series(today))


# -------------------- xem theo khoảng tự do (range mode) --------------------


def range_headline(vfrom: str, vto: str) -> dict:
    """Tổng các thẻ chính cho chế độ "Xem khoảng" tự do của /ceo.

    Doanh thu / chi phí ads / ROAS / GMV quảng cáo VNĐ lấy từ
    period_compare_custom với kỳ so sánh = khoảng liền trước DÀI BẰNG
    khoảng xem (default_prev_range) — delta % so với khoảng liền trước.
    Checklist lấy từ checklist.board_range_stats của cả khoảng: tasks =
    total - cancelled (cùng công thức thẻ checklist của ceo_overview).
    Ngày trong khoảng chưa có số thì bỏ qua như _aggregate.
    """
    prev_range = default_prev_range((vfrom, vto))
    cmp_data = period_compare_custom(vfrom, (vfrom, vto), prev_range)
    stats = checklist.board_range_stats(vfrom, vto)
    return {
        "start": vfrom,
        "end": vto,
        "prev_start": prev_range[0],
        "prev_end": prev_range[1],
        "prev_label": _range_label(*prev_range),
        "metrics": cmp_data["metrics"],
        "checklist": {
            "total": stats["total"],
            "tasks": stats["total"] - stats["cancelled"],
            "done": stats["done"],
            "pct": stats["pct"],
            "overdue": stats["overdue"],
        },
    }


def cached_range_headline(vfrom: str, vto: str) -> dict:
    """range_headline() với cache 60 giây, khoá theo (vfrom, vto)."""
    return _ttl_get(
        ("range_headline", vfrom, vto), lambda: range_headline(vfrom, vto)
    )
