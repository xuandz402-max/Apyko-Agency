"""Shopee Onboard — lộ trình 7 giai đoạn + 43 đầu việc onboarding Shopee.

Danh mục (giai đoạn + việc + các sheet tham khảo) là dữ liệu TĨNH trích
NGUYÊN VĂN từ file Shopee_Onboarding_Muse_Ready.xlsx của chủ shop, lưu ở
app/data/shopee_onboard.json — module chỉ nạp + trả nguyên trạng, tuyệt
đối không sửa/tóm tắt chữ.

Tiến độ của từng việc lưu ở DB (bảng sp_progress / sp_history trong
app/database.py), mirror đúng mẫu tt_progress / tt_history của TikTok
Onboard. Quy tắc validate (giống TikTok):
- Trạng thái "Hoàn tất" bắt buộc có kết quả/link bằng chứng HOẶC ghi chú
  lý do thay thế.
- Trạng thái "Không áp dụng" bắt buộc ghi lý do ở ô ghi chú.
Mỗi lần ĐỔI trạng thái đều ghi 1 dòng nhật ký sp_history.

Lưu ý: sheet "Cấu hình Muse" của file nguồn là hướng dẫn setup cho trợ lý
Muse, KHÔNG phải nội dung SOP cho người dùng nên không render thành tab.
Sheet này dùng bộ trạng thái có "Cần hỗ trợ" thay cho "Tạm dừng"; module
giữ bộ trạng thái của TikTok (có "Tạm dừng") theo đúng mẫu chung của app.
"""

import json
import os
import re
from datetime import datetime
from functools import lru_cache

_CATALOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "shopee_onboard.json"
)

STATUSES = [
    "Chưa bắt đầu",
    "Đang làm",
    "Chờ duyệt",
    "Hoàn tất",
    "Tạm dừng",
    "Không áp dụng",
]

DEFAULT_STATUS = "Chưa bắt đầu"
DONE_STATUS = "Hoàn tất"
NA_STATUS = "Không áp dụng"

# Nhãn class CSS cho huy hiệu trạng thái (dùng chung class tt-* ở style.css).
STATUS_CLASSES = {
    "Chưa bắt đầu": "tt-st-new",
    "Đang làm": "tt-st-doing",
    "Chờ duyệt": "tt-st-review",
    "Hoàn tất": "tt-st-done",
    "Tạm dừng": "tt-st-paused",
    "Không áp dụng": "tt-st-na",
}


# ------------------------------ danh mục tĩnh -------------------------------


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    """Nạp 1 lần danh mục nguyên văn (app/data/shopee_onboard.json)."""
    with open(_CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def list_phases() -> list:
    """7 giai đoạn theo đúng thứ tự lộ trình."""
    return sorted(load_catalog()["phases"], key=lambda p: p["order"])


def list_tasks() -> list:
    return list(load_catalog()["tasks"])


def get_task(code: str) -> dict | None:
    for task in load_catalog()["tasks"]:
        if task["code"] == code:
            return task
    return None


def phase_names() -> list:
    return [p["name"] for p in list_phases()]


def roadmap() -> dict:
    return load_catalog()["roadmap"]


def weekly() -> dict:
    return load_catalog()["weekly"]


def compare() -> dict:
    return load_catalog()["compare"]


def eval_sheet() -> dict:
    return load_catalog()["eval"]


# --------------------------- gộp danh mục + tiến độ --------------------------


def blank_progress() -> dict:
    """Tiến độ mặc định cho việc chưa từng được cập nhật."""
    return {
        "status": DEFAULT_STATUS,
        "assignee": "",
        "due": "",
        "evidence": "",
        "note": "",
        "updated_by": "",
        "updated_at": "",
    }


def merge_progress(tasks: list, progress_map: dict) -> list:
    """Gắn tiến độ DB vào từng việc của danh mục (thiếu -> mặc định)."""
    merged = []
    for task in tasks:
        item = dict(task)
        prog = progress_map.get(task["code"]) or blank_progress()
        item["progress"] = prog
        item["status_class"] = STATUS_CLASSES.get(
            prog["status"], STATUS_CLASSES[DEFAULT_STATUS]
        )
        item["due_vn"] = iso_to_vn(prog.get("due") or "")
        merged.append(item)
    return merged


def group_by_phase(tasks: list) -> list:
    """Gom việc theo giai đoạn, giữ thứ tự lộ trình; bỏ giai đoạn rỗng."""
    groups = []
    for phase in list_phases():
        items = [t for t in tasks if t["phase"] == phase["name"]]
        if items:
            groups.append({"phase": phase, "tasks": items})
    return groups


def filter_tasks(tasks: list, phase=None, status=None, q=None) -> list:
    """Lọc theo giai đoạn / trạng thái / từ khóa (không phân biệt hoa thường)."""
    out = tasks
    if phase:
        out = [t for t in out if t["phase"] == phase]
    if status:
        out = [t for t in out if t["progress"]["status"] == status]
    if q and q.strip():
        needle = q.strip().lower()
        out = [
            t
            for t in out
            if needle in t["code"].lower()
            or needle in t["title"].lower()
            or needle in (t["progress"].get("assignee") or "").lower()
        ]
    return out


def summarize(tasks: list) -> dict:
    """Tổng tiến độ: số hoàn tất / tổng, % và số Không áp dụng."""
    total = len(tasks)
    done = sum(1 for t in tasks if t["progress"]["status"] == DONE_STATUS)
    na = sum(1 for t in tasks if t["progress"]["status"] == NA_STATUS)
    return {
        "total": total,
        "done": done,
        "na": na,
        "percent": round(done / total * 100, 1) if total else 0.0,
    }


def phase_summaries(tasks: list) -> list:
    """done/total cho từng giai đoạn (để hiện trên các thẻ lộ trình)."""
    out = []
    for phase in list_phases():
        items = [t for t in tasks if t["phase"] == phase["name"]]
        done = sum(1 for t in items if t["progress"]["status"] == DONE_STATUS)
        out.append({"phase": phase, "done": done, "total": len(items)})
    return out


# ------------------------------ định dạng ngày -------------------------------


def iso_to_vn(iso: str) -> str:
    """'2026-10-23' -> '23/10/2026'; không phải ngày ISO thì trả nguyên."""
    s = (iso or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if not m:
        return s
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"


# ------------------------------ validate form --------------------------------


def validate_progress_payload(data: dict) -> tuple:
    """Kiểm tra dữ liệu form cập nhật tiến độ. Trả về (clean, errors).

    Quy tắc (mirror TikTok): "Hoàn tất" cần bằng chứng (link) hoặc lý do
    trong ghi chú; "Không áp dụng" cần lý do. Hạn (due) nhận ISO
    YYYY-MM-DD (date-vn.js đã đổi từ DD/MM/YYYY ở phía trình duyệt).
    """
    errors: dict = {}
    clean: dict = {}

    code = str(data.get("code") or "").strip()
    if get_task(code) is None:
        errors["code"] = "Mã công việc không tồn tại trong danh mục."
    clean["code"] = code

    status = str(data.get("status") or "").strip()
    if status not in STATUSES:
        errors["status"] = "Trạng thái không hợp lệ."
        status = DEFAULT_STATUS
    clean["status"] = status

    clean["assignee"] = str(data.get("assignee") or "").strip()
    clean["evidence"] = str(data.get("evidence") or "").strip()
    clean["note"] = str(data.get("note") or "").strip()

    due = str(data.get("due") or "").strip()
    if due:
        try:
            datetime.strptime(due, "%Y-%m-%d")
        except ValueError:
            errors["due"] = "Hạn hoàn thành chưa đúng định dạng ngày."
            due = ""
    clean["due"] = due

    if status == DONE_STATUS and not clean["evidence"] and not clean["note"]:
        errors["evidence"] = (
            "Việc Hoàn tất cần có link bằng chứng, hoặc ghi lý do vào ô ghi chú."
        )
    if status == NA_STATUS and not clean["note"]:
        errors["note"] = "Việc Không áp dụng cần ghi rõ lý do vào ô ghi chú."

    return clean, errors


def update_progress(data: dict, actor: str, db) -> tuple:
    """Validate + lưu tiến độ; đổi trạng thái thì ghi nhật ký. (clean, errors).

    `db` là module app.database (truyền vào để tránh import vòng và để
    test dễ thay thế). errors rỗng = đã lưu thành công.
    """
    clean, errors = validate_progress_payload(data)
    if errors:
        return clean, errors
    code = clean.pop("code")
    existing = db.sp_get_progress(code)
    old_status = (existing or {}).get("status") or DEFAULT_STATUS
    db.sp_upsert_progress(code, clean, updated_by=actor)
    if clean["status"] != old_status:
        db.sp_add_history(
            code,
            old_status,
            clean["status"],
            changed_by=actor,
            note=clean["note"],
        )
    return clean, {}
