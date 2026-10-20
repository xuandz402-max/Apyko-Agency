"""Dashboard CEO — tổng hợp 1 màn hình từ các module hiện có.

Chỉ đọc số thật đã được nhân sự nhập ở các module khác, không có bảng riêng:
- Doanh thu / chi phí ads / ROAS: Báo cáo ngày (daily_reports, qua calc_daily).
- GMV quảng cáo: GMV Max Shopee (gmv_entries, qua calc_gmv; VNĐ = RM x 5300).
- Checklist hôm nay: Daily Checklist (checklist.board_stats).

Ngưỡng cảnh báo mặc định (chỉnh trong code này):
- ROAS_WARN = 2.0: entry GMV mới nhất có ROAS dưới mức này → cảnh báo.
- STALE_DAYS = 3: sản phẩm không có entry nào trong 3 ngày gần nhất → cảnh báo.

Tốc độ: toàn bộ dữ liệu nạp bằng 5 câu query cố định (báo cáo ngày 1 query
cho mọi ngày cần xem, entry GMV 1 query cho mọi sản phẩm, checklist qua
board_stats). cached_overview() nhớ kết quả 60 giây vì trang chỉ đọc.
"""

import threading
import time
from datetime import datetime, timedelta

from . import checklist
from . import database as db
from .daily import calc_daily
from .gmv import RM_VND_RATE, calc_gmv

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
    gmv_rev_rm = 0.0
    gmv_cost_rm = 0.0
    gmv_entries_today = 0
    product_alerts = []
    entries_by_product: dict[int, list] = {}
    for entry in db.gmv_all_entries():
        entries_by_product.setdefault(entry["product_id"], []).append(entry)
    for product in db.gmv_list_products():
        entries = entries_by_product.get(product["id"], [])
        for entry in entries:
            if entry["date"] == today:
                gmv_rev_rm += float(entry.get("revenue_rm") or 0)
                gmv_cost_rm += float(entry.get("ad_cost") or 0)
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
        "revenue_rm": round(gmv_rev_rm, 2),
        "ad_cost_rm": round(gmv_cost_rm, 2),
        "revenue_vnd": round(gmv_rev_rm * RM_VND_RATE),
        "ad_cost_vnd": round(gmv_cost_rm * RM_VND_RATE),
        "roas": round(gmv_rev_rm / gmv_cost_rm, 2) if gmv_cost_rm != 0 else None,
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
