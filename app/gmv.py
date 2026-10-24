"""Chỉ số quảng cáo Shopee GMV Max (pure functions, không I/O).

Toàn bộ tiền tệ tính bằng VNĐ:
- CTR%  = click / lượt_xem
- CIR%  = chi_phí_qc / doanh_thu
- CPC   = chi_phí_qc / click (VNĐ)
- CR%   = chuyển_đổi / click
- AOV   = doanh_thu / chuyển_đổi (VNĐ, dùng conversions làm số đơn)
- ROAS  = doanh_thu / chi_phí_qc
Chia cho 0 → None (UI hiển thị "—"), giống IFERROR trong sheet.
"""

from datetime import datetime

# Tên sản phẩm lấy từ Google Sheet thật của user. Chỉ seed khi bảng đang
# trống hoàn toàn (không seed lại khi đã có dữ liệu).
GMV_SEED_PRODUCTS = [
    "ỐC NỞ CAMP MỚI",
    "LIỀM",
    "XÀ BÔNG NGHỆ",
    "ĐEN TÓC",
    "MẶT NẠ ĐỊNH HÌNH",
]

_INT_FIELDS = {
    "views": "Lượt xem",
    "clicks": "Lượt click",
    "conversions": "Lượt chuyển đổi",
}
_MONEY_FIELDS = {
    "revenue_vnd": "Doanh thu (VNĐ)",
    "ad_cost": "Chi phí quảng cáo (VNĐ)",
}


def _num(value) -> float:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return 0.0
    if isinstance(value, bool):
        raise TypeError("not a number")
    return float(value)


def calc_gmv(entry: dict) -> dict:
    """Tính các chỉ số dẫn xuất. Server luôn tự tính lại, không tin client."""
    views = _num(entry.get("views"))
    clicks = _num(entry.get("clicks"))
    conv = _num(entry.get("conversions"))
    revenue = _num(entry.get("revenue_vnd"))
    cost = _num(entry.get("ad_cost"))

    def pct(n: float, d: float):
        if d == 0:
            return None
        return round(n / d * 100, 2)

    def money(n: float, d: float):
        if d == 0:
            return None
        return round(n / d, 2)

    return {
        "ctr": pct(clicks, views),
        "cir": pct(cost, revenue),
        "cpc": money(cost, clicks),
        "cr": pct(conv, clicks),
        "aov": money(revenue, conv),
        "roas": money(revenue, cost),
    }


def validate_gmv_entry(data: dict) -> tuple:
    """Kiểm tra dòng nhập liệu. Trả về (clean, errors); clean chỉ có field hợp lệ."""
    if not isinstance(data, dict):
        return {}, {"body": "Body phải là một object JSON."}
    errors: dict = {}
    clean: dict = {}

    raw_date = data.get("date")
    raw_date = raw_date.strip() if isinstance(raw_date, str) else ""
    try:
        datetime.strptime(raw_date, "%Y-%m-%d")
        clean["date"] = raw_date
    except ValueError:
        errors["date"] = "Ngày phải đúng định dạng YYYY-MM-DD và là ngày hợp lệ."

    for field, label in _INT_FIELDS.items():
        try:
            val = _num(data.get(field))
        except (TypeError, ValueError):
            errors[field] = f"{label} phải là số nguyên >= 0."
            continue
        if val < 0 or not val.is_integer():
            errors[field] = f"{label} phải là số nguyên >= 0."
        else:
            clean[field] = int(val)

    for field, label in _MONEY_FIELDS.items():
        try:
            val = _num(data.get(field))
        except (TypeError, ValueError):
            errors[field] = f"{label} phải là số >= 0."
            continue
        if val < 0:
            errors[field] = f"{label} phải là số >= 0."
        else:
            clean[field] = round(val, 2)

    note = data.get("action_note")
    clean["action_note"] = note.strip() if isinstance(note, str) else ""
    return clean, errors
