"""Báo cáo doanh thu ngày (pure functions, không I/O).

Nhân sự nhập tay mỗi ngày: doanh thu theo 5 nguồn + chỉ số quảng cáo.
Server tự tính:
- total_rev = rev_product + rev_live + rev_video + rev_aff_link + rev_affiliate
- roas = ad_gmv / ad_cost (chia cho 0 → None, UI hiển thị "—")
"""

from datetime import date, datetime, timedelta

MONEY_FIELDS = {
    "rev_product": "Doanh thu Thẻ sản phẩm",
    "rev_live": "Doanh thu Live",
    "rev_video": "Doanh thu Video",
    "rev_aff_link": "Doanh thu Tiếp thị liên kết",
    "rev_affiliate": "Doanh thu Affiliate",
    "ad_gmv": "GMV quảng cáo",
    "ad_cost": "Chi phí ads",
    "aov": "Giá trị đơn trung bình",
}

REV_FIELDS = ["rev_product", "rev_live", "rev_video", "rev_aff_link", "rev_affiliate"]


def _num(value) -> float:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return 0.0
    if isinstance(value, bool):
        raise TypeError("not a number")
    return float(value)


def calc_daily(entry: dict) -> dict:
    """Tính các chỉ số dẫn xuất. Server luôn tự tính lại, không tin client."""
    total = sum(_num(entry.get(f)) for f in REV_FIELDS)
    ad_gmv = _num(entry.get("ad_gmv"))
    ad_cost = _num(entry.get("ad_cost"))
    return {
        "total_rev": round(total),
        "roas": round(ad_gmv / ad_cost, 2) if ad_cost != 0 else None,
    }


def period_totals(reports: list, start: str, end: str) -> dict:
    """Tổng Báo cáo ngày trong 1 khoảng [start, end] (chuỗi ISO gồm 2 đầu).

    Nhận list báo cáo thô (như db.daily_list). Ngày trong khoảng chưa nhập
    báo cáo thì bỏ qua (không tính là 0). Cả khoảng không có báo cáo nào
    -> count = 0 và mọi chỉ số None. ROAS kỳ = tổng ad_gmv / tổng ad_cost
    của cả khoảng (không lấy trung bình ROAS ngày).
    """
    scoped = [r for r in reports if start <= r["date"] <= end]
    if not scoped:
        return {"count": 0, "revenue": None, "ads_cost": None, "roas": None}
    revenue = sum(calc_daily(r)["total_rev"] for r in scoped)
    ad_gmv = sum(_num(r.get("ad_gmv")) for r in scoped)
    ad_cost = sum(_num(r.get("ad_cost")) for r in scoped)
    return {
        "count": len(scoped),
        "revenue": revenue,
        "ads_cost": round(ad_cost),
        "roas": round(ad_gmv / ad_cost, 2) if ad_cost != 0 else None,
    }


def validate_daily_report(data: dict) -> tuple:
    """Kiểm tra báo cáo ngày. Trả về (clean, errors); clean chỉ có field hợp lệ."""
    if not isinstance(data, dict):
        return {}, {"body": "Body phải là một object JSON."}
    errors: dict = {}
    clean: dict = {}

    raw_date = data.get("date")
    raw_date = raw_date.strip() if isinstance(raw_date, str) else ""
    try:
        parsed = datetime.strptime(raw_date, "%Y-%m-%d").date()
        max_date = date.today() + timedelta(days=1)
        if parsed > max_date:
            errors["date"] = "Ngày không được vượt quá ngày mai."
        else:
            clean["date"] = raw_date
    except ValueError:
        errors["date"] = "Ngày phải đúng định dạng YYYY-MM-DD và là ngày hợp lệ."

    for field, label in MONEY_FIELDS.items():
        try:
            val = _num(data.get(field))
        except (TypeError, ValueError):
            errors[field] = f"{label} phải là số >= 0."
            continue
        if val < 0:
            errors[field] = f"{label} phải là số >= 0."
        else:
            clean[field] = round(val)

    try:
        conv = _num(data.get("conv_rate"))
    except (TypeError, ValueError):
        errors["conv_rate"] = "Tỉ lệ chuyển đổi phải là số từ 0 đến 100."
    else:
        if conv < 0 or conv > 100:
            errors["conv_rate"] = "Tỉ lệ chuyển đổi phải là số từ 0 đến 100."
        else:
            clean["conv_rate"] = round(conv, 2)

    note = data.get("note")
    clean["note"] = note.strip() if isinstance(note, str) else ""
    return clean, errors
