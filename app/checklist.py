"""Daily Checklist — checklist vận hành Shopee đầu ngày.

Logic nghiệp vụ của module (lưu trữ ở app/database.py):
- seed_defaults(): shop mặc định, 20 mẫu việc đầu ngày, cài đặt nhắc mặc định.
- generate_for_date(): tạo việc trong ngày từ mẫu đang bật (không trùng).
- display_state(): trạng thái hiển thị theo hạn chót (giờ Việt Nam).
- process_reminders(): tạo thông báo đến hạn / nhắc lại quá hạn trong giờ
  làm việc, chống trùng bằng UPDATE có điều kiện (compare-and-swap).
- board_stats(): số liệu cho dashboard Leader.

Mọi mốc thời gian của module dùng múi giờ Asia/Ho_Chi_Minh.
"""

import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from . import database as db

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

DEFAULT_SHOP_NAME = "Mặc định"

DEFAULT_SETTINGS = {
    "work_start": "08:00",
    "work_end": "17:30",
    "work_days": "1,2,3,4,5,6",  # ISO weekday: T2..T7
    "reminder_interval_min": "30",
    "due_soon_min": "30",
}

# (nhóm, tên việc, giờ đến hạn mặc định) — checklist đầu ngày Shopee.
_A = "A. Tình trạng shop"
_B = "B. Đơn hàng"
_C = "C. Tin nhắn và đánh giá khách hàng"
_D = "D. Tồn kho và sản phẩm"
_E = "E. Voucher và khuyến mãi"
_F = "F. Quảng cáo và báo cáo"
DEFAULT_TEMPLATES = [
    (_A, "Kiểm tra tình trạng hoạt động của shop và cảnh báo từ Shopee", "08:30"),
    (_A, "Kiểm tra thông báo vi phạm, điểm phạt và cảnh báo hiệu suất shop", "08:30"),
    (_B, "Kiểm tra đơn hàng mới và đơn cần xử lý", "09:00"),
    (_B, "Kiểm tra đơn hàng có nguy cơ giao trễ", "09:00"),
    (_B, "Kiểm tra yêu cầu hủy đơn, trả hàng/hoàn tiền cần xử lý", "09:00"),
    (_C, "Kiểm tra tin nhắn mới và tin nhắn chưa phản hồi", "10:00"),
    (_C, "Phản hồi khách hàng theo quy trình chăm sóc khách hàng của shop", "10:00"),
    (_C, "Kiểm tra đánh giá mới, ưu tiên đánh giá 1–3 sao", "10:00"),  # noqa: RUF001
    (
        _C,
        "Phản hồi đánh giá khách hàng lịch sự, đúng tình huống" " và theo mẫu được duyệt",
        "10:30",
    ),
    (_C, "Báo Leader các khiếu nại nghiêm trọng hoặc đánh giá cần xử lý đặc biệt", "10:30"),
    (_D, "Kiểm tra tồn kho và sản phẩm hết hàng", "11:00"),
    (_D, "Kiểm tra sản phẩm tồn kho thấp hoặc có số lượng bất thường", "11:00"),
    (_D, "Kiểm tra sản phẩm bị ẩn, lỗi hiển thị hoặc thông tin sản phẩm bất thường", "11:00"),
    (_D, "Kiểm tra giá bán và thông tin sản phẩm chủ lực", "11:30"),
    (_E, "Kiểm tra các gói voucher còn thời hạn, sắp hết hạn hoặc đã hết hạn", "14:00"),
    (_E, "Kiểm tra các chương trình khuyến mãi đang chạy và thời gian kết thúc", "14:00"),
    (_E, "Kiểm tra điều kiện áp dụng voucher và giá sau ưu đãi", "14:00"),
    (_F, "Kiểm tra ngân sách, chi tiêu và cảnh báo quảng cáo", "16:00"),
    (_F, "Ghi nhận các vấn đề phát sinh, xác định hướng xử lý và báo Leader", "16:30"),
    (_F, "Cập nhật tình trạng shop vào báo cáo đầu ngày", "16:30"),
]

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_vn() -> datetime:
    return datetime.now(VN_TZ)


def today_str(now: datetime | None = None) -> str:
    return (now or now_vn()).date().isoformat()


def valid_hhmm(value) -> bool:
    return isinstance(value, str) and bool(_HHMM_RE.match(value.strip()))


def _parse_hhmm(value: str) -> time:
    hh, mm = value.strip().split(":")
    return time(int(hh), int(mm))


def due_datetime(date_str: str, due_time: str) -> datetime:
    """Mốc đến hạn (aware, giờ VN) của một việc: ngày + giờ hạn."""
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    return datetime.combine(d, _parse_hhmm(due_time), tzinfo=VN_TZ)


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=VN_TZ)
    return dt


# ------------------------------ seed -------------------------------------


def seed_defaults() -> None:
    """Seed shop mặc định, cài đặt và 20 mẫu việc — chỉ khi bảng đang trống."""
    now = _utcnow()
    with db.get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM shops").fetchone()
        if row["c"] == 0:
            conn.execute(
                "INSERT OR IGNORE INTO shops (name, created_at) VALUES (?, ?)",
                (DEFAULT_SHOP_NAME, now),
            )
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO checklist_settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        row = conn.execute("SELECT COUNT(*) AS c FROM checklist_templates").fetchone()
        if row["c"] == 0:
            for i, (group, title, due) in enumerate(DEFAULT_TEMPLATES, start=1):
                conn.execute(
                    "INSERT INTO checklist_templates (group_name, title, sort, due_time,"
                    " assignee_id, shop_id, is_active, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, NULL, NULL, 1, ?, ?)",
                    (group, title, i * 10, due, now, now),
                )


# ----------------------------- settings -----------------------------------


def get_settings() -> dict:
    """Cài đặt hiệu dụng (đã parse kiểu): giờ làm việc, chu kỳ nhắc..."""
    raw = dict(DEFAULT_SETTINGS)
    raw.update(db.cl_setting_get_all())
    try:
        interval = int(raw.get("reminder_interval_min") or 30)
    except (TypeError, ValueError):
        interval = 30
    try:
        due_soon = int(raw.get("due_soon_min") or 30)
    except (TypeError, ValueError):
        due_soon = 30
    days = set()
    for part in str(raw.get("work_days") or "").split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= 7:
            days.add(int(part))
    if not days:
        days = {1, 2, 3, 4, 5, 6}
    return {
        "work_start": raw.get("work_start") or "08:00",
        "work_end": raw.get("work_end") or "17:30",
        "work_days": days,
        "reminder_interval_min": max(5, interval),
        "due_soon_min": max(0, due_soon),
    }


def in_work_hours(now: datetime, settings: dict) -> bool:
    if now.isoweekday() not in settings["work_days"]:
        return False
    start = _parse_hhmm(settings["work_start"])
    end = _parse_hhmm(settings["work_end"])
    return start <= now.time() <= end


# ----------------------------- generate -----------------------------------


def generate_for_date(date_str: str) -> int:
    """Tạo việc cho 1 ngày từ các mẫu đang bật. Trả về số việc mới tạo.

    Chống trùng bằng UNIQUE(date, template_id) + INSERT OR IGNORE: chạy
    lại bao nhiêu lần (scheduler, mở trang, khởi động lại) vẫn không
    nhân đôi bản ghi.
    """
    templates = [t for t in db.cl_template_list() if t.get("is_active")]
    created = 0
    now = _utcnow()
    with db.get_conn() as conn:
        for t in templates:
            cur = conn.execute(
                "INSERT OR IGNORE INTO checklist_items (date, template_id, group_name,"
                " title, sort, due_time, assignee_id, shop_id, status, note,"
                " completed_by, completed_at, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', '', '', '', ?, ?)",
                (
                    date_str,
                    t["id"],
                    t["group_name"],
                    t["title"],
                    t["sort"],
                    t["due_time"],
                    t.get("assignee_id"),
                    t.get("shop_id"),
                    now,
                    now,
                ),
            )
            created += cur.rowcount or 0
    return created


# --------------------------- display state --------------------------------


def display_state(item: dict, now: datetime, due_soon_min: int | None = None) -> str:
    """Trạng thái hiển thị: done | cancelled | overdue | due | pending."""
    status = item.get("status") or "pending"
    if status in ("done", "cancelled"):
        return status
    if due_soon_min is None:
        due_soon_min = get_settings()["due_soon_min"]
    due_at = due_datetime(item["date"], item["due_time"])
    if now > due_at:
        return "overdue"
    if due_at - now <= timedelta(minutes=due_soon_min):
        return "due"
    return "pending"


# ---------------------------- reminders -----------------------------------


def _notif_content(item: dict, repeat: bool) -> tuple:
    assignee = db.get_user(item["assignee_id"]) if item.get("assignee_id") else None
    staff_name = ""
    if assignee:
        staff_name = assignee.get("display_name") or assignee.get("username") or ""
    shop_name = "Chưa gán shop"
    if item.get("shop_id"):
        shop = db.shop_get(item["shop_id"])
        if shop:
            shop_name = shop["name"]
    label = "Nhắc lại — việc quá hạn" if repeat else "Việc đến hạn"
    title = f"{label}: {item['title']}"
    body = (
        f"Nhân viên: {staff_name} · Việc: {item['title']} · Shop: {shop_name}"
        f" · Hạn chót: {item['due_time']} ngày {item['date']}"
    )
    link = f"/checklist?date={item['date']}"
    return title, body, link


def process_reminders(now: datetime) -> int:
    """Quét việc pending đã đến hạn và tạo thông báo nhắc. Trả số thông báo mới.

    Chống gửi trùng khi nhiều luồng chạy đồng thời: mỗi lần gửi đi kèm một
    UPDATE có điều kiện (compare-and-swap trên due_notified_at /
    last_reminder_at đã đọc). Chỉ luồng nào UPDATE trúng đúng 1 dòng mới
    được INSERT thông báo — cùng một transaction nên không thể trùng.
    Việc đã hoàn thành / đã hủy không còn trong tập pending nên tự dừng nhắc.
    """
    settings = get_settings()
    interval = timedelta(minutes=settings["reminder_interval_min"])
    now_iso = now.isoformat()
    created = 0
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM checklist_items WHERE status = 'pending'"
            " AND assignee_id IS NOT NULL ORDER BY id ASC"
        ).fetchall()
        items = [dict(r) for r in rows]
    for item in items:
        due_at = due_datetime(item["date"], item["due_time"])
        if now < due_at:
            continue
        if not item.get("due_notified_at"):
            title, body, link = _notif_content(item, repeat=False)
            with db.get_conn() as conn:
                cur = conn.execute(
                    "UPDATE checklist_items SET due_notified_at = ?,"
                    " last_reminder_at = ?, reminder_count = 1, updated_at = ?"
                    " WHERE id = ? AND status = 'pending' AND due_notified_at IS NULL",
                    (now_iso, now_iso, _utcnow(), item["id"]),
                )
                if cur.rowcount == 1:
                    conn.execute(
                        "INSERT INTO notifications (user_id, item_id, title, body,"
                        " link, is_read, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
                        (item["assignee_id"], item["id"], title, body, link, _utcnow()),
                    )
                    created += 1
            continue
        # Đã báo lần đầu: nhắc lại theo chu kỳ, chỉ trong giờ làm việc.
        last = _parse_ts(item.get("last_reminder_at"))
        if last is None or now - last < interval:
            continue
        if not in_work_hours(now, settings):
            continue  # ngoài giờ: lần tick trong giờ làm việc kế tiếp sẽ nhắc
        title, body, link = _notif_content(item, repeat=True)
        with db.get_conn() as conn:
            cur = conn.execute(
                "UPDATE checklist_items SET last_reminder_at = ?,"
                " reminder_count = reminder_count + 1, updated_at = ?"
                " WHERE id = ? AND status = 'pending' AND last_reminder_at = ?",
                (now_iso, _utcnow(), item["id"], item["last_reminder_at"]),
            )
            if cur.rowcount == 1:
                conn.execute(
                    "INSERT INTO notifications (user_id, item_id, title, body,"
                    " link, is_read, created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
                    (item["assignee_id"], item["id"], title, body, link, _utcnow()),
                )
                created += 1
    return created


# ------------------------------ board -------------------------------------


def board_stats(
    date_str: str,
    assignee_id: int | None = None,
    shop_id: int | None = None,
    now: datetime | None = None,
) -> dict:
    """Thống kê ngày cho Leader: tổng/hoàn thành/quá hạn + theo nhân viên."""
    now = now or now_vn()
    settings = get_settings()
    items = db.cl_item_list(date_str, assignee_id=assignee_id, shop_id=shop_id)
    users = {u["id"]: u for u in db.list_users()}

    total = len(items)
    done = sum(1 for it in items if it["status"] == "done")
    cancelled = sum(1 for it in items if it["status"] == "cancelled")
    overdue = 0
    per_user: dict[int, dict] = {}
    for it in items:
        state = display_state(it, now, settings["due_soon_min"])
        if state == "overdue":
            overdue += 1
        uid = it.get("assignee_id")
        if uid is None:
            continue
        bucket = per_user.setdefault(
            uid,
            {
                "user_id": uid,
                "name": (users.get(uid) or {}).get("display_name")
                or (users.get(uid) or {}).get("username")
                or f"#{uid}",
                "total": 0,
                "done": 0,
                "overdue": 0,
            },
        )
        if it["status"] != "cancelled":
            bucket["total"] += 1
        if it["status"] == "done":
            bucket["done"] += 1
        if state == "overdue":
            bucket["overdue"] += 1
    per_user_list = []
    for bucket in per_user.values():
        bucket["pct"] = round(bucket["done"] * 100 / bucket["total"], 1) if bucket["total"] else 0.0
        per_user_list.append(bucket)
    per_user_list.sort(key=lambda b: (b["pct"], b["name"]))
    return {
        "date": date_str,
        "total": total,
        "done": done,
        "cancelled": cancelled,
        "unfinished": total - done - cancelled,
        "overdue": overdue,
        "per_user": per_user_list,
        "overdue_users": [b for b in per_user_list if b["overdue"] > 0],
    }


# ---------------------------- validation ----------------------------------


def validate_template_payload(data: dict, partial: bool = False) -> tuple:
    """Validate payload mẫu việc. Trả về (clean, errors)."""
    if not isinstance(data, dict):
        return {}, {"body": "Body phải là một object JSON."}
    errors: dict = {}
    clean: dict = {}

    if not partial or "title" in data:
        title = data.get("title")
        title = title.strip() if isinstance(title, str) else ""
        if not title:
            errors["title"] = "Tên công việc không được trống."
        else:
            clean["title"] = title
    if not partial or "group_name" in data:
        group = data.get("group_name")
        clean["group_name"] = group.strip() if isinstance(group, str) else ""
    if not partial or "due_time" in data:
        due = data.get("due_time")
        if not valid_hhmm(due if isinstance(due, str) else ""):
            errors["due_time"] = "Giờ đến hạn phải đúng định dạng HH:MM."
        else:
            clean["due_time"] = due.strip()
    if not partial or "sort" in data:
        try:
            sort_val = int(data.get("sort") or 0)
        except (TypeError, ValueError):
            sort_val = -1
        if sort_val < 0:
            errors["sort"] = "Thứ tự phải là số nguyên >= 0."
        else:
            clean["sort"] = sort_val
    for field, getter, label in (
        ("assignee_id", db.get_user, "Nhân viên phụ trách"),
        ("shop_id", db.shop_get, "Shop"),
    ):
        if not partial or field in data:
            raw = data.get(field)
            if raw is None or raw == "":
                clean[field] = None
            else:
                try:
                    ref_id = int(raw)
                except (TypeError, ValueError):
                    errors[field] = f"{label} không hợp lệ."
                    continue
                if getter(ref_id) is None:
                    errors[field] = f"{label} không tồn tại."
                else:
                    clean[field] = ref_id
    if not partial or "is_active" in data:
        clean["is_active"] = 1 if data.get("is_active", True) else 0
    return clean, errors


def validate_settings_payload(data: dict) -> tuple:
    """Validate payload cài đặt. Trả về (clean_dict_str, errors)."""
    if not isinstance(data, dict):
        return {}, {"body": "Body phải là một object JSON."}
    errors: dict = {}
    clean: dict = {}
    for field, label in (
        ("work_start", "Giờ bắt đầu làm việc"),
        ("work_end", "Giờ kết thúc làm việc"),
    ):
        value = data.get(field)
        if not valid_hhmm(value if isinstance(value, str) else ""):
            errors[field] = f"{label} phải đúng định dạng HH:MM."
        else:
            clean[field] = value.strip()
    days_raw = data.get("work_days")
    days: list[int] = []
    if isinstance(days_raw, list):
        candidates = days_raw
    elif isinstance(days_raw, str):
        candidates = [p.strip() for p in days_raw.split(",") if p.strip()]
    else:
        candidates = []
    for c in candidates:
        try:
            d = int(c)
        except (TypeError, ValueError):
            d = -1
        if d < 1 or d > 7:
            errors["work_days"] = "Thứ làm việc phải thuộc 1..7 (T2=1 … CN=7)."
            break
        if d not in days:
            days.append(d)
    if "work_days" not in errors:
        if not days:
            errors["work_days"] = "Phải chọn ít nhất 1 ngày làm việc."
        else:
            clean["work_days"] = ",".join(str(d) for d in sorted(days))
    try:
        interval = int(data.get("reminder_interval_min"))
    except (TypeError, ValueError):
        interval = -1
    if interval < 5:
        errors["reminder_interval_min"] = "Chu kỳ nhắc phải là số nguyên >= 5 phút."
    else:
        clean["reminder_interval_min"] = str(interval)
    try:
        due_soon = int(data.get("due_soon_min"))
    except (TypeError, ValueError):
        due_soon = -1
    if due_soon < 0 or due_soon > 480:
        errors["due_soon_min"] = "Ngưỡng 'sắp đến hạn' phải là số nguyên 0..480 phút."
    else:
        clean["due_soon_min"] = str(due_soon)
    return clean, errors
