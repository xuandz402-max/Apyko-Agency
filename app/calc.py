"""Hàm tính toán thuần túy (pure functions, không I/O).

Mọi tỷ lệ phí (platform_fee_rate, payment_fee_rate, ads_rate, affiliate_rate)
đều do người dùng khai báo, tính theo % trên giá bán. Module này KHÔNG chứa
biểu phí chính thức của bất kỳ sàn nào.
"""


def _num(value, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calc_profit(p: dict) -> dict:
    """Tính lợi nhuận và biên lợi nhuận của một sản phẩm.

    margin = None (không bao giờ chia cho 0) khi giá bán bằng 0.
    """
    price = _num(p.get("selling_price"))
    cost = _num(p.get("cost_price"))
    packaging = _num(p.get("packaging_cost"))
    shipping = _num(p.get("shipping_seller"))
    other = _num(p.get("other_cost"))

    platform_fee = price * _num(p.get("platform_fee_rate")) / 100
    payment_fee = price * _num(p.get("payment_fee_rate")) / 100
    ads_cost = price * _num(p.get("ads_rate")) / 100
    affiliate_cost = price * _num(p.get("affiliate_rate")) / 100
    total_pct_costs = platform_fee + payment_fee + ads_cost + affiliate_cost

    profit = round(price - cost - packaging - shipping - total_pct_costs - other)

    if price == 0:
        margin = None
    else:
        margin = round(profit / price * 100, 2)

    return {
        "selling_price": price,
        "cost_price": cost,
        "packaging_cost": packaging,
        "shipping_seller": shipping,
        "platform_fee_rate": _num(p.get("platform_fee_rate")),
        "payment_fee_rate": _num(p.get("payment_fee_rate")),
        "ads_rate": _num(p.get("ads_rate")),
        "affiliate_rate": _num(p.get("affiliate_rate")),
        "platform_fee": platform_fee,
        "payment_fee": payment_fee,
        "ads_cost": ads_cost,
        "affiliate_cost": affiliate_cost,
        "total_pct_costs": total_pct_costs,
        "other_cost": other,
        "profit": profit,
        "margin": margin,
        "margin_missing": margin is None,
    }


def margin_score(m) -> int | None:
    """Quy biên lợi nhuận (%) về thang 0-100."""
    if m is None:
        return None
    if m >= 30:
        return 100
    if m >= 20:
        return 80
    if m >= 15:
        return 60
    if m >= 10:
        return 40
    if m >= 0:
        return 20
    return 0


def scale_1_5(s) -> int | None:
    """Quy điểm 1-5 về thang 0-100."""
    if s is None:
        return None
    return round((s - 1) / 4 * 100)


_MISSING_NAMES = {
    "margin": "Lợi nhuận biên (giá bán = 0)",
    "demand_score": "Điểm nhu cầu",
    "competition_score": "Điểm cạnh tranh",
    "content_score": "Điểm nội dung",
    "supply_score": "Điểm nguồn hàng",
}


def score_product(p: dict, calc: dict) -> dict:
    """Chấm điểm sản phẩm 0-100.

    Thiếu dữ liệu (margin None hoặc bất kỳ điểm 1-5 nào None) thì trả về
    score None kèm danh sách trường còn thiếu.
    """
    needs_data = []
    if calc.get("margin") is None:
        needs_data.append(_MISSING_NAMES["margin"])
    for field in ("demand_score", "competition_score", "content_score", "supply_score"):
        if p.get(field) is None:
            needs_data.append(_MISSING_NAMES[field])

    if needs_data:
        return {
            "score": None,
            "label": "Cần bổ sung dữ liệu",
            "needs_data": needs_data,
            "components": {
                "margin": None,
                "demand": None,
                "competition": None,
                "content": None,
                "supply": None,
            },
        }

    components = {
        "margin": margin_score(calc["margin"]),
        "demand": scale_1_5(p.get("demand_score")),
        "competition": scale_1_5(p.get("competition_score")),
        "content": scale_1_5(p.get("content_score")),
        "supply": scale_1_5(p.get("supply_score")),
    }
    score = round(
        0.25 * components["margin"]
        + 0.25 * components["demand"]
        + 0.20 * components["competition"]
        + 0.15 * components["content"]
        + 0.15 * components["supply"],
        2,
    )
    if score >= 80:
        label = "Ưu tiên kiểm tra"
    elif score >= 60:
        label = "Có thể thử nghiệm"
    else:
        label = "Chưa ưu tiên"

    return {"score": score, "label": label, "needs_data": [], "components": components}


def analyze_product(p: dict) -> dict:
    """Gộp dữ liệu gốc + tính toán + chấm điểm + giả định."""
    calc = calc_profit(p)
    return {
        "product": dict(p),
        "calc": calc,
        "score": score_product(p, calc),
        "assumptions": [
            "Tỷ lệ phí do bạn khai báo, chưa xác minh với Shopee.",
            "Điểm chỉ là mô hình hỗ trợ quyết định, " "không phải xác suất thành công.",
        ],
    }
