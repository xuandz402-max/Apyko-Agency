"""Kiểm tra dữ liệu sản phẩm đầu vào. Thông điệp lỗi bằng tiếng Việt."""

MONEY_FIELDS = [
    "selling_price",
    "cost_price",
    "packaging_cost",
    "shipping_seller",
    "other_cost",
]
RATE_FIELDS = [
    "platform_fee_rate",
    "payment_fee_rate",
    "ads_rate",
    "affiliate_rate",
]
SCORE_FIELDS = [
    "demand_score",
    "competition_score",
    "content_score",
    "supply_score",
]
TEXT_FIELDS = ["name", "sku", "category", "data_source", "notes"]
VALID_STATUSES = ("active", "testing", "archived")

_MONEY_LABELS = {
    "selling_price": "Giá bán",
    "cost_price": "Giá vốn",
    "packaging_cost": "Chi phí đóng gói",
    "shipping_seller": "Phí ship người bán chịu",
    "other_cost": "Chi phí khác",
}
_RATE_LABELS = {
    "platform_fee_rate": "Phí sàn (%)",
    "payment_fee_rate": "Phí thanh toán (%)",
    "ads_rate": "Chi phí quảng cáo (%)",
    "affiliate_rate": "Hoa hồng tiếp thị liên kết (%)",
}
_SCORE_LABELS = {
    "demand_score": "Điểm nhu cầu",
    "competition_score": "Điểm cạnh tranh",
    "content_score": "Điểm nội dung",
    "supply_score": "Điểm nguồn hàng",
}
_STATUS_LABELS = {
    "active": "Đang bán",
    "testing": "Đang thử nghiệm",
    "archived": "Lưu trữ",
}


def _is_empty(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _to_float(value):
    """Ép kiểu số đơn giản; trả về None nếu không ép được.

    Không parse định dạng số Việt Nam (ví dụ "45.000" chỉ hiểu là 45.0).
    """
    if _is_empty(value) or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value):
    """Ép về số nguyên; trả về None nếu không phải số nguyên hợp lệ."""
    if _is_empty(value) or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def validate_product(data: dict) -> dict:
    """Trả về dict {field: thông điệp lỗi}; dict rỗng nghĩa là hợp lệ."""
    errors: dict[str, str] = {}

    name = data.get("name")
    if _is_empty(name):
        errors["name"] = "Tên sản phẩm không được để trống."

    for field in MONEY_FIELDS:
        if field not in data or _is_empty(data[field]):
            continue  # thiếu thì dùng default 0
        num = _to_float(data[field])
        if num is None or num < 0:
            errors[field] = f"{_MONEY_LABELS[field]} phải là số ≥ 0."

    for field in RATE_FIELDS:
        if field not in data or _is_empty(data[field]):
            continue  # thiếu thì dùng default 0
        num = _to_float(data[field])
        if num is None or not 0 <= num <= 100:
            errors[field] = f"{_RATE_LABELS[field]} phải là số từ 0 đến 100."

    for field in SCORE_FIELDS:
        if field not in data or _is_empty(data[field]):
            continue  # được phép bỏ trống
        num = _to_int(data[field])
        if num is None or not 1 <= num <= 5:
            errors[field] = (
                f"{_SCORE_LABELS[field]} phải là số nguyên từ 1 đến 5 " "(bỏ trống nếu chưa có)."
            )

    status = data.get("status", "active")
    if not _is_empty(status) and status not in VALID_STATUSES:
        errors["status"] = "Trạng thái phải là active, testing hoặc archived."

    return errors


def _clean_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value)


def payload_from_input(data: dict) -> dict:
    """Chuyển input thô (form/JSON) thành dict đúng kiểu để lưu DB.

    Chỉ gọi sau khi validate_product(data) không còn lỗi.
    """
    out: dict = {}
    for field in TEXT_FIELDS:
        out[field] = _clean_text(data.get(field))
    status = data.get("status")
    out["status"] = status.strip() if isinstance(status, str) and status.strip() else "active"
    for field in MONEY_FIELDS + RATE_FIELDS:
        value = data.get(field)
        out[field] = _to_float(value) if not _is_empty(value) else 0.0
    for field in SCORE_FIELDS:
        value = data.get(field)
        out[field] = _to_int(value) if not _is_empty(value) else None
    return out
