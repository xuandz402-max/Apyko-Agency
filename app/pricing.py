"""Định giá sản phẩm — bảng tính giá bán Shopee (hàm thuần, không I/O DB).

Nguồn sự thật: file Excel "Dự tính giá bán" của user (sheet "Tính hàng loạt"
+ "Tham số mặc định"). Công thức cho 1 sản phẩm, P = giá bán, E = giá vốn:
- Phí ngành       = P x % phí ngành (tra theo mã ngành, dữ liệu tĩnh đóng gói)
- Phí thanh toán  = P x % thanh toán
- Phí Voucher Xtra = MIN(P x % voucher, trần voucher)
- Phí Affiliate   = P x % affiliate
- Tiền quảng cáo  = P x % quảng cáo
- Thuế khấu trừ   = P x % thuế
- Phí cố định/đơn = Pi Ship + Hạ tầng (mặc định 2.700 + 3.000 = 5.700đ)
- Tổng chi phí    = E + các khoản trên
- Lãi/Lỗ          = P - Tổng chi phí;  % biên lãi = Lãi/Lỗ / P

Quy ước % trong TOÀN module (nơi duy nhất chuyển đổi):
- API / UI dùng số % kiểu người dùng: 6 nghĩa là 6%, 1.5 nghĩa là 1.5%.
- DB lưu dạng thập phân như file gốc: 0.06, 0.015.
- validate_pricing_payload() là nơi DUY NHẤT đổi % người dùng -> thập phân;
  calc nhận/đầu ra nội bộ dùng thập phân cho các rate, riêng margin_pct
  trả về dạng % người dùng (VD 29.72) để UI hiển thị trực tiếp.
"""

import json
import os
from functools import lru_cache

_DATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "pricing_categories.json"
)

# Các trường tiền (đồng, số nguyên >= 0) trong payload người dùng.
MONEY_FIELDS = ["cost_price", "selling_price", "voucher_cap", "pi_ship", "infra_fee"]
# Các trường % trong payload người dùng: tên field -> tên cột DB (thập phân).
PCT_FIELDS = {
    "pay_rate_pct": "pay_rate",
    "voucher_rate_pct": "voucher_rate",
    "affiliate_rate_pct": "affiliate_rate",
    "ads_rate_pct": "ads_rate",
    "tax_rate_pct": "tax_rate",
    "category_fee_rate_pct": "category_fee_rate",
}


# ------------------------------ ngành hàng ---------------------------------


@lru_cache(maxsize=1)
def list_categories() -> list:
    """Nạp 1 lần toàn bộ 2.904 ngành hàng đóng gói trong app/data/."""
    with open(_DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _category_index() -> dict:
    return {c["code"]: c for c in list_categories()}


def find_category(code: str | None) -> dict | None:
    if not code:
        return None
    return _category_index().get(code.strip())


def search_categories(q: str, limit: int = 20) -> list:
    """Tìm ngành theo chuỗi con, không phân biệt hoa/thường (code + big + small)."""
    needle = (q or "").strip().lower()
    if not needle:
        return []
    out = []
    for c in list_categories():
        haystack = f"{c['code']}\n{c['big']}\n{c['small']}".lower()
        if needle in haystack:
            out.append(c)
            if len(out) >= limit:
                break
    return out


# ------------------------------ tính giá -----------------------------------


def _f(d: dict, key: str) -> float:
    v = d.get(key)
    return float(v) if v is not None else 0.0


def calc_pricing(d: dict) -> dict:
    """Tính mọi khoản phí từ dict dạng DB (các rate là thập phân, tiền là đồng).

    Trả về các khoản đã làm tròn về số nguyên đồng; margin_pct dạng % người
    dùng (VD 29.72), None khi giá bán <= 0 (tránh chia 0, hiển thị "—").
    """
    price = _f(d, "selling_price")
    cost = _f(d, "cost_price")
    cat_fee = round(price * _f(d, "category_fee_rate"))
    pay_fee = round(price * _f(d, "pay_rate"))
    voucher_fee = round(min(price * _f(d, "voucher_rate"), _f(d, "voucher_cap")))
    affiliate_fee = round(price * _f(d, "affiliate_rate"))
    ads_cost = round(price * _f(d, "ads_rate"))
    tax_fee = round(price * _f(d, "tax_rate"))
    fixed_fee = int(_f(d, "pi_ship")) + int(_f(d, "infra_fee"))
    total_cost = (
        int(cost)
        + cat_fee
        + pay_fee
        + voucher_fee
        + affiliate_fee
        + ads_cost
        + tax_fee
        + fixed_fee
    )
    profit = int(price) - total_cost
    margin_pct = round(profit / price * 100, 2) if price > 0 else None
    return {
        "cat_fee": cat_fee,
        "pay_fee": pay_fee,
        "voucher_fee": voucher_fee,
        "affiliate_fee": affiliate_fee,
        "ads_cost": ads_cost,
        "tax_fee": tax_fee,
        "fixed_fee": fixed_fee,
        "total_cost": total_cost,
        "profit": profit,
        "margin_pct": margin_pct,
    }


_MAX_PRICE = 10**10


def price_for_margin(d: dict, target_margin_pct: float) -> int | None:
    """Tính NGƯỢC giá bán nguyên đồng nhỏ nhất đạt biên lãi >= target (%).

    Giải bằng tìm kiếm nhị phân trên [1, 10^10] vì phí Voucher có trần
    (MIN) nên không giải đại số được. Biên lãi đơn điệu không giảm theo
    giá bán (khi giá tăng, tỷ trọng giá vốn + phí cố định giảm và % phí
    Voucher hiệu dụng không tăng). Trả None khi target >= 100% hoặc ngay
    ở giá tối đa vẫn không đạt target (tổng % phí quá cao).
    """
    if target_margin_pct is None or target_margin_pct >= 100:
        return None

    def margin_at(price: int) -> float:
        m = calc_pricing({**d, "selling_price": price})["margin_pct"]
        return m if m is not None else float("-inf")

    if margin_at(_MAX_PRICE) < target_margin_pct:
        return None
    lo, hi = 1, _MAX_PRICE
    while lo < hi:
        mid = (lo + hi) // 2
        if margin_at(mid) >= target_margin_pct:
            hi = mid
        else:
            lo = mid + 1
    return lo


# ------------------------------ validate -----------------------------------


def _num(value):
    """Như daily._num: chấp nhận int/float/chuỗi số; bool -> lỗi."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    if isinstance(value, bool):
        raise TypeError("not a number")
    if isinstance(value, str):
        value = value.replace(",", "").replace(" ", "")
    return float(value)


def _money_field(data: dict, field: str, default, errors: dict, label: str):
    raw = data.get(field)
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return int(default) if default is not None else 0
    try:
        val = _num(raw)
    except (TypeError, ValueError):
        errors[field] = f"{label} phải là số >= 0."
        return 0
    if val is None or val < 0:
        errors[field] = f"{label} phải là số >= 0."
        return 0
    return int(round(val))


def _pct_field(data: dict, field: str, default_rate, errors: dict, label: str) -> float:
    """% người dùng (0..100) -> thập phân. Vắng mặt -> default (đã thập phân)."""
    raw = data.get(field)
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return float(default_rate) if default_rate is not None else 0.0
    try:
        val = _num(raw)
    except (TypeError, ValueError):
        errors[field] = f"{label} phải là số từ 0 đến 100."
        return 0.0
    if val is None or val < 0 or val > 100:
        errors[field] = f"{label} phải là số từ 0 đến 100."
        return 0.0
    return val / 100


def validate_pricing_payload(data, defaults: dict | None = None, require_name: bool = True):
    """Kiểm tra payload định giá (dạng NGƯỜI DÙNG) -> (clean, errors).

    clean ở dạng DB (rate thập phân, tiền nguyên đồng) — đây là nơi duy
    nhất chuyển đổi % người dùng -> thập phân. `defaults` là dict dạng DB
    (từ pricing_settings) dùng khi payload thiếu trường.
    """
    if not isinstance(data, dict):
        return {}, {"body": "Body phải là một object JSON."}
    defaults = defaults or {}
    errors: dict = {}
    clean: dict = {}

    name = data.get("name")
    name = name.strip() if isinstance(name, str) else ""
    if require_name and not name:
        errors["name"] = "Tên sản phẩm không được trống."
    clean["name"] = name

    # Ngành hàng: có mã hợp lệ -> % phí lấy từ danh mục (như VLOOKUP của sheet),
    # bỏ qua category_fee_rate_pct gửi kèm. Không có mã -> dùng % gửi kèm/mặc định.
    code = data.get("category_code")
    code = code.strip() if isinstance(code, str) else ""
    clean["category_code"] = code
    if code:
        cat = find_category(code)
        if cat is None:
            errors["category_code"] = "Ngành hàng không tồn tại trong danh mục."
            clean["category_fee_rate"] = 0.0
        else:
            clean["category_fee_rate"] = float(cat["fee_rate"])
    else:
        clean["category_fee_rate"] = _pct_field(
            data,
            "category_fee_rate_pct",
            defaults.get("category_fee_rate", 0.0),
            errors,
            "% phí ngành",
        )

    labels = {
        "cost_price": "Giá vốn",
        "selling_price": "Giá bán",
        "voucher_cap": "Trần Voucher Xtra",
        "pi_ship": "Phí Pi Ship",
        "infra_fee": "Phí hạ tầng",
    }
    for field in MONEY_FIELDS:
        clean[field] = _money_field(
            data, field, defaults.get(field, 0), errors, labels[field]
        )
    pct_labels = {
        "pay_rate_pct": "% phí thanh toán",
        "voucher_rate_pct": "% phí Voucher Xtra",
        "affiliate_rate_pct": "% phí Affiliate",
        "ads_rate_pct": "% chi phí quảng cáo",
        "tax_rate_pct": "% thuế khấu trừ",
    }
    for field, col in PCT_FIELDS.items():
        if field == "category_fee_rate_pct":
            continue  # đã xử lý cùng ngành hàng ở trên
        clean[col] = _pct_field(data, field, defaults.get(col, 0.0), errors, pct_labels[field])
    return clean, errors


def settings_to_defaults(raw: dict) -> dict:
    """pricing_settings (chuỗi trong DB) -> dict mặc định dạng DB cho validate."""
    out = {}
    for key in ("pay_rate", "voucher_rate", "affiliate_rate", "tax_rate"):
        try:
            out[key] = float(raw.get(key) or 0)
        except (TypeError, ValueError):
            out[key] = 0.0
    for key in ("voucher_cap", "pi_ship", "infra_fee"):
        try:
            out[key] = int(round(float(raw.get(key) or 0)))
        except (TypeError, ValueError):
            out[key] = 0
    return out


def settings_to_user_view(raw: dict) -> dict:
    """pricing_settings -> dạng NGƯỜI DÙNG cho API/UI (% thay vì thập phân)."""
    d = settings_to_defaults(raw)
    return {
        "pay_rate_pct": round(d["pay_rate"] * 100, 4),
        "voucher_rate_pct": round(d["voucher_rate"] * 100, 4),
        "voucher_cap": d["voucher_cap"],
        "affiliate_rate_pct": round(d["affiliate_rate"] * 100, 4),
        "pi_ship": d["pi_ship"],
        "infra_fee": d["infra_fee"],
        "tax_rate_pct": round(d["tax_rate"] * 100, 4),
    }


def validate_settings_payload(data):
    """Kiểm tra payload sửa tham số mặc định (dạng NGƯỜI DÙNG).

    Trả (clean_db_strings, errors): clean là dict key -> chuỗi dạng DB
    sẵn sàng ghi vào pricing_settings. Chỉ gồm các trường có mặt.
    """
    if not isinstance(data, dict):
        return {}, {"body": "Body phải là một object JSON."}
    errors: dict = {}
    clean: dict = {}
    pct_map = {
        "pay_rate_pct": ("pay_rate", "% phí thanh toán"),
        "voucher_rate_pct": ("voucher_rate", "% phí Voucher Xtra"),
        "affiliate_rate_pct": ("affiliate_rate", "% phí Affiliate"),
        "tax_rate_pct": ("tax_rate", "% thuế khấu trừ"),
    }
    for field, (col, label) in pct_map.items():
        if field in data:
            rate = _pct_field(data, field, None, errors, label)
            if field not in errors:
                clean[col] = repr(rate)
    money_map = {
        "voucher_cap": "Trần Voucher Xtra",
        "pi_ship": "Phí Pi Ship",
        "infra_fee": "Phí hạ tầng",
    }
    for field, label in money_map.items():
        if field in data:
            val = _money_field(data, field, None, errors, label)
            if field not in errors:
                clean[field] = str(val)
    if not clean and not errors:
        errors["body"] = "Không có tham số nào để cập nhật."
    return clean, errors
