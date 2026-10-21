"""Affiliate — bảng theo dõi link TTLK + nội dung bài "Shopee tiếp thị liên kết".

Hai phần độc lập:
1. Tracker (dữ liệu ở bảng affiliate_links, tầng DB app/database.py): số
   liệu TÍCH LŨY theo từng link, nhân viên nhập tay từ báo cáo của nền
   tảng. Chỉ số dẫn xuất do server tính ở đây, không lưu DB:
   - CVR = orders / clicks x 100 (%)
   - EPC = commission_received / clicks (VNĐ/click) — dùng hoa hồng THỰC
     NHẬN vì đó là sự thật cuối cùng, không dùng số dự kiến.
   clicks = 0 -> cả hai đều None (template hiện "—"), cấm chia 0/bịa số.
2. Nội dung bài: file tĩnh app/data/affiliate_deck.json trích NGUYÊN VĂN
   từ bài thuyết trình Google Slides "Shopee tiếp thị liên kết" của chủ
   shop (54 slide; 26 slide có chữ, 28 slide chỉ có ảnh). Ảnh gốc trong
   các slide đã tải về static/lesson-images/aff/ và trỏ từ khóa "images"
   của từng slide; "source_url" là link bài gốc trên Google Drive.
   Module chỉ nạp + trả nguyên trạng, tuyệt đối không sửa/tóm tắt chữ.
"""

import json
import os
from functools import lru_cache

_DECK_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "affiliate_deck.json"
)

PLATFORMS = ["Shopee", "TikTok", "Facebook", "Zalo", "Khác"]


# ------------------------------ nội dung bài -------------------------------


@lru_cache(maxsize=1)
def load_deck() -> dict:
    """Nạp 1 lần bài thuyết trình đã trích nguyên văn (app/data/)."""
    with open(_DECK_PATH, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------ chỉ số dẫn xuất ----------------------------


def calc_affiliate(row: dict) -> dict:
    """CVR (%) + EPC (VNĐ/click) của 1 link; clicks = 0 -> None (hiện "—")."""
    clicks = row.get("clicks") or 0
    orders = row.get("orders") or 0
    received = row.get("commission_received") or 0
    if not clicks:
        return {"cvr": None, "epc": None}
    return {
        "cvr": round(orders / clicks * 100, 2),
        "epc": round(received / clicks, 2),
    }


def affiliate_totals(rows: list) -> dict:
    """Tổng toàn danh sách đang xem: số link, click, đơn, hoa hồng thực nhận."""
    return {
        "links": len(rows),
        "clicks": sum(r.get("clicks") or 0 for r in rows),
        "orders": sum(r.get("orders") or 0 for r in rows),
        "commission_received": sum(r.get("commission_received") or 0 for r in rows),
    }


# ------------------------------ validate form ------------------------------


def _parse_count(raw, label: str, errors: dict, field: str) -> int:
    """Số nguyên >= 0; chấp nhận dấu chấm/phẩy phân cách nghìn kiểu VN."""
    s = str(raw or "").strip().replace(".", "").replace(",", "").replace(" ", "")
    if s == "":
        return 0
    try:
        value = int(s)
    except ValueError:
        errors[field] = f"{label} phải là số nguyên."
        return 0
    if value < 0:
        errors[field] = f"{label} không được âm."
        return 0
    return value


def _parse_rate(raw, errors: dict) -> float:
    """% hoa hồng: số thập phân >= 0 (chấp nhận "7,5" lẫn "7.5")."""
    s = str(raw or "").strip().replace(" ", "").replace("%", "").replace(",", ".")
    if s == "":
        return 0.0
    try:
        value = float(s)
    except ValueError:
        errors["commission_rate"] = "% hoa hồng phải là số."
        return 0.0
    if value < 0:
        errors["commission_rate"] = "% hoa hồng không được âm."
        return 0.0
    return value


def validate_affiliate_payload(data: dict) -> tuple:
    """Kiểm tra dữ liệu form tracker. Trả về (clean, errors).

    clean chỉ chứa các cột của bảng affiliate_links (trừ id/updated_*).
    Tên sản phẩm là bắt buộc duy nhất; các số để trống hiểu là 0.
    """
    errors: dict = {}
    clean: dict = {}

    clean["product_name"] = str(data.get("product_name") or "").strip()
    if not clean["product_name"]:
        errors["product_name"] = "Thiếu tên sản phẩm."

    platform = str(data.get("platform") or "").strip()
    clean["platform"] = platform if platform in PLATFORMS else "Shopee"

    clean["affiliate_link"] = str(data.get("affiliate_link") or "").strip()
    clean["sub_id"] = str(data.get("sub_id") or "").strip()
    clean["data_source"] = str(data.get("data_source") or "").strip()
    clean["note"] = str(data.get("note") or "").strip()

    clean["commission_rate"] = _parse_rate(data.get("commission_rate"), errors)
    clean["clicks"] = _parse_count(data.get("clicks"), "Lượt click", errors, "clicks")
    clean["orders"] = _parse_count(data.get("orders"), "Số đơn", errors, "orders")
    clean["commission_estimated"] = _parse_count(
        data.get("commission_estimated"), "Hoa hồng dự kiến", errors, "commission_estimated"
    )
    clean["commission_received"] = _parse_count(
        data.get("commission_received"), "Hoa hồng thực nhận", errors, "commission_received"
    )
    return clean, errors
