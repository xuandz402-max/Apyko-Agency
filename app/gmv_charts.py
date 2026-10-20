"""Biểu đồ GMV Max + cảnh báo tự động (logic thuần trên dữ liệu gmv_*).

- build_series(): dữ liệu vẽ biểu đồ theo ngày. Ngày KHÔNG có entry -> None
  (khoảng trống trên biểu đồ), tuyệt đối không điền 0 — tránh hiểu nhầm
  "không chạy quảng cáo" thành "chạy mà không ra GMV".
- product_totals(): tổng GMV / chi phí / ROAS theo sản phẩm trong kỳ.
- gmv_alerts(): cảnh báo theo 4 quy tắc, ngưỡng lấy từ app/ceo.py
  (ROAS_WARN = 2.0, STALE_DAYS = 3) để 2 nơi không lệch nhau.
- sync_gmv_alert_notifications(): đẩy cảnh báo vào bảng notifications
  (cùng cơ chế với Daily Checklist), chống spam bằng bảng phụ trợ
  gmv_alert_log: mỗi (sản phẩm, quy tắc) tối đa 1 thông báo / ngày.

Quy tắc 3 & 4 (gmv_drop / roas_drop) so 2 cửa sổ NGÀY-CÓ-SỐ liên tiếp:
3 ngày có số gần nhất vs tối đa 3 ngày có số liền trước. Chỉ tính khi sản
phẩm có tối thiểu 4 ngày có số (đủ cửa sổ gần nhất + ít nhất 1 ngày trước)
và mẫu số của cửa sổ trước > 0.
"""

from datetime import date, datetime, timedelta, timezone

from . import database as db
from .ceo import ROAS_WARN, STALE_DAYS
from .gmv import RM_VND_RATE, calc_gmv

# Ngưỡng giảm (%) cho quy tắc gmv_drop / roas_drop: giảm trên mức này mới báo.
DROP_PCT = 30.0

# Thứ tự hiển thị cảnh báo theo quy tắc (cảnh báo tiền bạc lên trước).
_RULE_ORDER = {"roas_low": 0, "gmv_drop": 1, "roas_drop": 2, "stale": 3}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_date(today) -> date:
    """Chấp nhận date / datetime / chuỗi 'YYYY-MM-DD' -> datetime.date."""
    if isinstance(today, datetime):
        return today.date()
    if isinstance(today, date):
        return today
    return datetime.strptime(str(today), "%Y-%m-%d").date()


def _fmt_vnd(amount) -> str:
    """Định dạng tiền kiểu Việt Nam: 1234567 -> '1.234.567'."""
    return f"{int(round(amount)):,}".replace(",", ".")


def _entries_by_product() -> dict:
    """Toàn bộ entry GMV gom theo sản phẩm (1 query, date ASC như ceo.py)."""
    grouped: dict[int, list] = {}
    for entry in db.gmv_all_entries():
        grouped.setdefault(entry["product_id"], []).append(entry)
    return grouped


def _day_sums(entries: list) -> dict:
    """{date_str: (revenue_rm, ad_cost_rm)} cộng dồn theo ngày."""
    sums: dict[str, tuple] = {}
    for e in entries:
        rev, cost = sums.get(e["date"], (0.0, 0.0))
        sums[e["date"]] = (
            rev + float(e.get("revenue_rm") or 0),
            cost + float(e.get("ad_cost") or 0),
        )
    return sums


# ------------------------------ biểu đồ -----------------------------------


def build_series(product_id, days: int, today) -> dict:
    """Dữ liệu biểu đồ `days` ngày gần nhất tính đến `today`.

    product_id=None -> tổng mọi sản phẩm (ngày có ít nhất 1 sản phẩm có số
    thì có tổng). Ngày không có entry -> None ở cả 3 dãy (không điền 0).
    ROAS ngày = tổng GMV / tổng chi phí của ngày đó; chi phí 0 -> None.
    """
    end = _as_date(today)
    labels = [(end - timedelta(days=back)).isoformat() for back in range(days - 1, -1, -1)]
    grouped = _entries_by_product()
    if product_id is None:
        scoped = [e for entries in grouped.values() for e in entries]
    else:
        scoped = grouped.get(product_id, [])
    sums = _day_sums(scoped)
    gmv_vnd: list = []
    cost_vnd: list = []
    roas: list = []
    for day in labels:
        if day not in sums:
            gmv_vnd.append(None)
            cost_vnd.append(None)
            roas.append(None)
            continue
        rev_rm, cost_rm = sums[day]
        gmv_vnd.append(round(rev_rm * RM_VND_RATE))
        cost_vnd.append(round(cost_rm * RM_VND_RATE))
        roas.append(round(rev_rm / cost_rm, 2) if cost_rm != 0 else None)
    return {
        "product_id": product_id,
        "days": days,
        "labels": labels,
        "gmv_vnd": gmv_vnd,
        "cost_vnd": cost_vnd,
        "roas": roas,
    }


def product_totals(days: int, today) -> list:
    """Tổng GMV/chi phí/ROAS theo sản phẩm trong `days` ngày gần nhất.

    Chỉ gồm sản phẩm có ít nhất 1 entry trong kỳ; sắp xếp GMV giảm dần.
    """
    end = _as_date(today)
    start = (end - timedelta(days=days - 1)).isoformat()
    end_s = end.isoformat()
    grouped = _entries_by_product()
    totals = []
    for product in db.gmv_list_products():
        entries = [
            e
            for e in grouped.get(product["id"], [])
            if start <= e["date"] <= end_s
        ]
        if not entries:
            continue
        rev_rm = sum(float(e.get("revenue_rm") or 0) for e in entries)
        cost_rm = sum(float(e.get("ad_cost") or 0) for e in entries)
        totals.append(
            {
                "product_id": product["id"],
                "product_name": product["name"],
                "gmv_vnd": round(rev_rm * RM_VND_RATE),
                "cost_vnd": round(cost_rm * RM_VND_RATE),
                "roas": round(rev_rm / cost_rm, 2) if cost_rm != 0 else None,
                "entry_days": len({e["date"] for e in entries}),
            }
        )
    totals.sort(key=lambda t: (-t["gmv_vnd"], t["product_name"]))
    return totals


# ------------------------------ cảnh báo -----------------------------------


def _window(entries: list, start: int, stop: int) -> tuple:
    """(doanh thu RM, chi phí RM) của 1 cửa sổ entry."""
    part = entries[start:stop]
    rev = sum(float(e.get("revenue_rm") or 0) for e in part)
    cost = sum(float(e.get("ad_cost") or 0) for e in part)
    return rev, cost


def gmv_alerts(today) -> list:
    """Cảnh báo GMV hiện tại theo 4 quy tắc (xem docstring đầu file)."""
    end = _as_date(today)
    stale_cutoff = (end - timedelta(days=STALE_DAYS - 1)).isoformat()
    grouped = _entries_by_product()
    alerts = []
    for product in db.gmv_list_products():
        pid = product["id"]
        name = product["name"]
        entries = grouped.get(pid, [])
        latest = entries[-1] if entries else None

        # Quy tắc 2 — stale: không entry nào trong STALE_DAYS ngày gần nhất.
        if latest is None or latest["date"] < stale_cutoff:
            if latest is None:
                message = (
                    f"{name} chưa có số liệu quảng cáo nào"
                    " — hãy nhập số liệu GMV Max."
                )
            else:
                message = (
                    f"{name} chưa có số liệu {STALE_DAYS} ngày gần nhất"
                    f" (mới nhất: {latest['date']})."
                )
            alerts.append(
                {
                    "product_id": pid,
                    "product_name": name,
                    "rule": "stale",
                    "message": message,
                    "severity": "medium",
                }
            )

        if latest is not None:
            # Quy tắc 1 — ROAS của ngày có số mới nhất dưới ngưỡng.
            roas = calc_gmv(latest)["roas"]
            if roas is not None and roas < ROAS_WARN:
                alerts.append(
                    {
                        "product_id": pid,
                        "product_name": name,
                        "rule": "roas_low",
                        "message": (
                            f"ROAS hôm nay của {name} chỉ đạt {roas}"
                            f" — dưới ngưỡng {ROAS_WARN}."
                        ),
                        "severity": "high",
                    }
                )

        # Quy tắc 3 & 4 — so 2 cửa sổ ngày-có-số (tối thiểu 4 ngày có số).
        if len(entries) >= 4:
            rev_recent, cost_recent = _window(entries, -3, None)
            rev_prev, cost_prev = _window(entries, -6, -3)
            if rev_prev > 0:
                drop = (rev_prev - rev_recent) / rev_prev * 100
                if drop > DROP_PCT:
                    alerts.append(
                        {
                            "product_id": pid,
                            "product_name": name,
                            "rule": "gmv_drop",
                            "message": (
                                f"GMV 3 ngày gần nhất của {name} giảm"
                                f" {drop:.0f}% so với kỳ trước"
                                f" ({_fmt_vnd(rev_recent * RM_VND_RATE)}đ"
                                f" so với {_fmt_vnd(rev_prev * RM_VND_RATE)}đ)."
                            ),
                            "severity": "high",
                        }
                    )
            roas_recent = rev_recent / cost_recent if cost_recent != 0 else None
            roas_prev = rev_prev / cost_prev if cost_prev != 0 else None
            if roas_recent is not None and roas_prev is not None and roas_prev > 0:
                drop = (roas_prev - roas_recent) / roas_prev * 100
                if drop > DROP_PCT:
                    alerts.append(
                        {
                            "product_id": pid,
                            "product_name": name,
                            "rule": "roas_drop",
                            "message": (
                                f"ROAS trung bình 3 ngày gần nhất của {name}"
                                f" giảm {drop:.0f}% (từ {roas_prev:.2f}"
                                f" xuống {roas_recent:.2f})."
                            ),
                            "severity": "medium",
                        }
                    )

    alerts.sort(
        key=lambda a: (a["product_name"], _RULE_ORDER.get(a["rule"], 99))
    )
    return alerts


# --------------------- đẩy cảnh báo vào thông báo --------------------------


def _alert_recipients() -> list:
    """Người nhận cảnh báo GMV: owner + user đang bật có quyền xem GMV.

    Module GMV dùng chung quyền xem Sản phẩm (can_view_products — chính là
    quyền gác trang /gmv), nên người nhận là owner và mọi tài khoản đang
    hoạt động có can_view_products.
    """
    return [
        u
        for u in db.list_users()
        if u.get("is_active") and (u.get("is_owner") or u.get("can_view_products"))
    ]


def sync_gmv_alert_notifications(today) -> int:
    """Tạo thông báo trong app cho các cảnh báo GMV của ngày `today`.

    Chống spam: khóa dedupe `gmv:{product_id}:{rule}:{YYYY-MM-DD}` trong
    bảng gmv_alert_log — INSERT OR IGNORE trúng (rowcount = 1) mới tạo
    thông báo, cùng 1 transaction với các INSERT notifications, nên chạy
    lại bao nhiêu lần trong ngày (scheduler 60s + mở trang) cũng không
    nhân đôi. Trả về số thông báo (bản ghi notifications) mới tạo.
    """
    day = _as_date(today)
    alerts = gmv_alerts(day)
    if not alerts:
        return 0
    recipients = _alert_recipients()
    if not recipients:
        return 0
    created = 0
    now_iso = _utcnow()
    for alert in alerts:
        key = f"gmv:{alert['product_id']}:{alert['rule']}:{day.isoformat()}"
        with db.get_conn() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO gmv_alert_log (dedupe_key, created_at)"
                " VALUES (?, ?)",
                (key, now_iso),
            )
            if cur.rowcount != 1:
                continue
            for user in recipients:
                conn.execute(
                    "INSERT INTO notifications (user_id, item_id, title, body,"
                    " link, is_read, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
                    (
                        user["id"],
                        alert["product_id"],
                        f"⚠️ Cảnh báo GMV Max: {alert['product_name']}",
                        alert["message"],
                        "/gmv",
                        now_iso,
                    ),
                )
                created += 1
    return created
