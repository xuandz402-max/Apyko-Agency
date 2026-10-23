"""Phân tích đơn hàng Shopee — ánh xạ file xuất Seller Centre + đối soát.

Nguồn dữ liệu: file .csv/.xlsx xuất từ Shopee (62 cột cố định A..BJ).
Nguyên tắc đã chốt trong kế hoạch (KE-HOACH-SHOPEE-ORDER-ANALYTICS):

- Nhận diện cột bằng VỊ TRÍ + TIÊU ĐỀ cùng lúc: vị trí chuẩn của bản
  xuất Shopee thắng; tiêu đề (đã chuẩn hoá) phải "khớp" từ khóa riêng
  của cột — hai cột tiền AC và AT có tiêu đề gần giống nhau nhưng vị
  trí khác nhau nên không bao giờ bị gán nhầm cho nhau.
- Giá trị sau voucher của 1 dòng = AC x AA - AE - AG (công thức nghiệp
  vụ của chủ shop). Giá trị của đơn = tổng các dòng của đơn.
- AT (Tiền khách thanh toán cuối cùng) là số CẤP ĐƠN: chỉ tính 1 lần
  cho mỗi đơn khi mọi dòng của đơn ghi AT giống nhau; khác nhau -> đơn
  bị gắn cờ "AT không nhất quán" và bị loại khỏi tổng AT.
- Đối soát từng đơn (dung sai 1đ):
    A: tổng(AC x AA - AE - AG) == AT
    B: tổng(AC x AA - AE - AG) - AK x 100 + AQ == AT
       (AK = Shopee Xu được hoàn, AQ = phí vận chuyển người mua trả;
       AK/AQ chỉ lấy 1 lần khi các dòng trong đơn nhất quán)
  Không biến thể nào khớp -> gắn cờ "cần kiểm tra tiền", ghi số lệch.
- Dòng trống Mã đơn hàng / lỗi dữ liệu chí mạng -> CÁCH LY, không bao
  giờ tham gia chỉ số. Ô tiền đọc không được -> ghi nhận lỗi ô (cell
  error), không crash, không âm thầm nuốt dữ liệu.
- Mọi chỉ số tiền mặc định LOẠI đơn "Đã hủy" (nêu rõ ở chú thích UI).
- Module này thuần logic + đọc DB qua app.database; không ghi DB ở
  bước ánh xạ (routes ghi sau khi user xác nhận xem trước).
"""

import hashlib
import json
import re
from collections import Counter
from datetime import date

from . import database as db
from . import importer

# --------------------------- bản đồ cột Shopee ----------------------------
# (field, vị trí 0-based chuẩn, từ khóa tiêu đề đã chuẩn hoá để đối chiếu,
#  loại: text | money | int | date | dt)
# Vị trí tính theo bản xuất 62 cột: A=0 ... BJ=61.

COLUMNS = [
    ("order_id", 0, "ma don hang", "text"),
    ("package_id", 1, "ma kien hang", "text"),
    ("order_dt", 2, "ngay dat hang", "dt"),
    ("status", 3, "trang thai don hang", "text"),
    ("cancel_reason", 5, "ly do huy", "text"),
    ("tracking_no", 7, "ma van don", "text"),
    ("carrier", 8, "don vi van chuyen", "text"),
    ("delivery_method", 9, "phuong thuc giao hang", "text"),
    ("order_type", 10, "loai don hang", "text"),
    ("expected_dt", 11, "ngay giao hang du kien", "date"),
    ("ship_dt", 12, "ngay gui hang", "date"),
    ("delivery_dt", 13, "thoi gian giao hang", "date"),
    ("return_status", 14, "tra hang hoan tien", "text"),
    ("sku", 15, "sku san pham", "text"),
    ("product_name", 16, "ten san pham", "text"),
    ("variation_sku", 19, "sku phan loai", "text"),
    ("variation_name", 20, "ten phan loai", "text"),
    ("price_original", 21, "gia goc", "money"),
    ("seller_subsidy", 22, "nguoi ban tro gia", "money"),
    ("shopee_subsidy", 23, "shopee tro gia", "money"),
    ("seller_subsidy_total", 24, "tong so tien duoc nguoi ban tro gia", "money"),
    ("price_promo", 25, "gia uu dai", "money"),
    ("qty", 26, "so luong", "int"),
    ("qty_returned", 27, "so luong san pham duoc hoan tra", "int"),
    ("amount_ac", 28, "thanh toan truoc khi tru voucher", "money"),
    ("order_total_ad", 29, "tong gia tri don hang", "money"),
    ("voucher_shop", 30, "ma giam gia cua shop", "money"),
    ("coin_cashback", 31, "hoan xu", "money"),
    ("voucher_shopee", 32, "ma giam gia cua shopee", "money"),
    ("combo_shopee", 34, "giam gia tu combo shopee", "money"),
    ("combo_shop", 35, "giam gia tu combo cua shop", "money"),
    ("shopee_coin", 36, "shopee xu duoc hoan", "money"),
    ("card_discount", 37, "giam khi thanh toan bang the", "money"),
    ("ship_est", 40, "phi van chuyen (du kien)", "money"),
    ("ship_buyer", 42, "phi van chuyen ma nguoi mua tra", "money"),
    ("ship_sponsored", 43, "phi van chuyen tai tro boi shopee", "money"),
    ("ship_return_fee", 44, "phi van chuyen tra hang", "money"),
    ("buyer_paid_at", 45, "tien khach thanh toan cuoi cung", "money"),
    ("completed_dt", 46, "thoi gian hoan thanh don hang", "date"),
    ("paid_dt", 47, "thoi gian don hang duoc thanh toan", "date"),
    ("payment_method", 48, "phuong thuc thanh toan", "text"),
    ("fee_fixed", 49, "phi co dinh", "money"),
    ("fee_service", 50, "phi dich vu", "money"),
    ("fee_transaction", 51, "phi xu ly giao dich", "money"),
    ("province", 56, "tinh thanh pho", "text"),
    ("district", 57, "quan huyen", "text"),
    ("ward", 58, "quan", "text"),
]

BUYER_COLUMNS = [
    ("buyer_username", 53, "nguoi mua"),
    ("recipient_name", 54, "ten nguoi nhan"),
    ("phone", 55, "so dien thoai"),
    ("address", 59, "dia chi nhan hang"),
]

FIELD_POS = {f: pos for f, pos, _kw, _kind in COLUMNS}
FIELD_KIND = {f: kind for f, _pos, _kw, kind in COLUMNS}

# Nhãn hiển thị bắt buộc cho 2 cột tiền dễ nhầm (theo đặc tả).
AC_LABEL = "Tiền người mua thanh toán trước voucher shop/Shopee (AC)"
AT_LABEL = "Tiền khách thanh toán cuối cùng (AT)"

CANCELLED = "Đã hủy"

KNOWN_STATUSES = {
    "Đã giao",
    "Đã hủy",
    "Chờ giao hàng",
    "Chờ lấy hàng",
    "Chờ xác nhận",
    "Đang giao",
    "Đang vận chuyển",
    "Trả hàng/Hoàn tiền",
    "Đã hoàn thành",
    "Hoàn thành",
    "Giao hàng không thành công",
}

RECON_TOLERANCE = 1  # đồng


def is_cancelled(status: str) -> bool:
    return importer.normalize_header(status or "") == "da huy"


def fmt_vnd(value) -> str:
    """Số tiền -> '1.234.567' (chấm = phân cách nghìn); None -> '—'."""
    if value is None:
        return "—"
    return f"{value:,.0f}".replace(",", ".")


def _norm_text(value: str) -> str:
    return " ".join((value or "").split()).lower()


def _header_matches(header: str, keyword: str) -> bool:
    return keyword in importer.normalize_header(header or "")


def map_order_columns(headers: list) -> tuple:
    """Ánh xạ field -> vị trí cột, bằng VỊ TRÍ + TIÊU ĐỀ cùng lúc.

    Ưu tiên vị trí chuẩn khi tiêu đề ở vị trí đó khớp từ khóa của field;
    field nào chưa khớp được mới tìm theo tiêu đề ở các vị trí còn trống.
    Trả (mapping, cảnh báo) — cảnh báo liệt kê field không tìm thấy và
    các vị trí có tiêu đề khác dự kiến.
    """
    mapping: dict[str, int] = {}
    used: set[int] = set()
    warnings: list[str] = []
    for field, pos, keyword, _kind in COLUMNS:
        if pos < len(headers) and _header_matches(headers[pos], keyword):
            mapping[field] = pos
            used.add(pos)
    for field, _pos, keyword, _kind in COLUMNS:
        if field in mapping:
            continue
        for pos, header in enumerate(headers):
            if pos not in used and _header_matches(header, keyword):
                mapping[field] = pos
                used.add(pos)
                break
    for field, pos, _kw, _kind in COLUMNS:
        if field not in mapping:
            warnings.append(field)
        elif mapping[field] != pos and pos < len(headers):
            warnings.append(f"{field}: lệch vị trí chuẩn")
    return mapping, warnings


# ------------------------------ parse dòng --------------------------------

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _parse_dt(raw: str) -> tuple:
    """-> (ngày ISO hoặc None, 'YYYY-MM-DD HH:MM' hoặc ngày ISO)."""
    s = (raw or "").strip()
    if not s:
        return None, ""
    d = importer.parse_date(s)
    if d is None:
        return None, ""
    m = _TIME_RE.search(s)
    if m:
        return d, f"{d} {int(m.group(1)):02d}:{m.group(2)}"
    return d, d


def _money(raw: str, field: str, cell_errors: list):
    """Ép kiểu tiền: rỗng -> None (không lỗi); đọc không được -> None + lỗi ô."""
    s = (raw or "").strip()
    if not s:
        return None
    val = importer.parse_number(s)
    if val is None:
        cell_errors.append(field)
        return None
    return round(val)


def _int(raw: str, field: str, cell_errors: list):
    s = (raw or "").strip()
    if not s:
        return None
    val = importer.parse_number(s)
    if val is None or not float(val).is_integer() or val < 0:
        cell_errors.append(field)
        return None
    return int(val)


def _cell(row: list, mapping: dict, field: str) -> str:
    pos = mapping.get(field)
    if pos is None or pos >= len(row):
        return ""
    return str(row[pos] or "").strip()


def _line_base_key(order_id: str, data: dict) -> str:
    def money(v):
        return "" if v is None else str(int(round(v)))

    parts = [
        order_id,
        _norm_text(data.get("product_name") or ""),
        (data.get("sku") or "").strip(),
        (data.get("variation_sku") or "").strip(),
        _norm_text(data.get("variation_name") or ""),
        "" if data.get("qty") is None else str(data["qty"]),
        money(data.get("amount_ac")),
        money(data.get("price_promo")),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def parse_order_rows(headers: list, rows: list, shop: str) -> tuple:
    """Ánh xạ toàn bộ dòng file -> danh sách item xem trước.

    Mỗi item: {row, status: 'ok'|'quarantine', reason, cell_errors,
    data (dict khớp ORDER_LINE_COLUMNS, trừ import_id/shop/line_key —
    line_key có sẵn), buyer}. Raises ValueError nếu thiếu cột Mã đơn
    hàng (lỗi cấp file).
    """
    mapping, col_warnings = map_order_columns(headers)
    if "order_id" not in mapping:
        raise ValueError(
            "File thiếu cột 'Mã đơn hàng' (cột A) — không nhận diện được "
            "đây là file xuất đơn hàng Shopee."
        )
    buyer_mapping: dict[str, int] = {}
    for field, pos, keyword in BUYER_COLUMNS:
        if pos < len(headers) and _header_matches(headers[pos], keyword):
            buyer_mapping[field] = pos

    items: list = []
    ordinal_counter: Counter = Counter()
    for i, row in enumerate(rows, start=2):
        cell_errors: list[str] = []
        fatal: list[str] = []
        data: dict = {}
        order_id = _cell(row, mapping, "order_id")
        if not order_id:
            fatal.append("Mã đơn hàng trống")
        for field, _pos, _kw, kind in COLUMNS:
            if field == "order_id":
                data[field] = order_id
                continue
            raw = _cell(row, mapping, field)
            if kind == "money":
                data[field] = _money(raw, field, cell_errors)
            elif kind == "int":
                data[field] = _int(raw, field, cell_errors)
            elif kind == "dt":
                d, text = _parse_dt(raw)
                data["order_date"] = d or ""
                data["order_dt"] = text
                if d is None:
                    fatal.append("Ngày đặt hàng không đọc được")
            elif kind == "date":
                d, _text = _parse_dt(raw)
                data[field] = d or ""
            else:
                data[field] = raw
        # Đổi tên khóa ngày cho khớp schema order_lines.
        data["expected_date"] = data.pop("expected_dt", "")
        data["ship_date"] = data.pop("ship_dt", "")
        data["delivery_date"] = data.pop("delivery_dt", "")
        data["completed_date"] = data.pop("completed_dt", "")
        data["paid_date"] = data.pop("paid_dt", "")
        if data.get("qty") is None:
            fatal.append("Số lượng (AA) không đọc được")
        if data.get("amount_ac") is None:
            fatal.append("Số tiền AC không đọc được")
        if fatal:
            items.append(
                {
                    "row": i,
                    "status": "quarantine",
                    "reason": "; ".join(dict.fromkeys(fatal)),
                    "cell_errors": cell_errors,
                    "data": None,
                    "buyer": None,
                    "raw": {
                        "order_id_raw": order_id,
                        "product_name": data.get("product_name") or "",
                        "variation_name": data.get("variation_name") or "",
                        "status": data.get("status") or "",
                        "order_date": data.get("order_date") or "",
                        "amount_ac": data.get("amount_ac"),
                        "buyer_paid_at": data.get("buyer_paid_at"),
                    },
                }
            )
            continue
        base = _line_base_key(order_id, data)
        group = (order_id, base)
        ordinal = ordinal_counter[group]
        ordinal_counter[group] += 1
        data["line_key"] = f"{base}#{ordinal}"
        data["cell_errors"] = json.dumps(cell_errors, ensure_ascii=False)
        buyer = {
            f: (str(row[p]).strip() if p < len(row) and row[p] is not None else "")
            for f, p in buyer_mapping.items()
        }
        items.append(
            {
                "row": i,
                "status": "ok",
                "reason": "",
                "cell_errors": cell_errors,
                "data": data,
                "buyer": buyer,
                "raw": None,
            }
        )
    return items, mapping, col_warnings


# --------------------------- tổng hợp cấp đơn ------------------------------


def line_value(line: dict):
    """Giá trị sau voucher của 1 dòng = AC x AA - AE - AG."""
    ac = line.get("amount_ac")
    qty = line.get("qty")
    if ac is None or qty is None:
        return None
    return ac * qty - (line.get("voucher_shop") or 0) - (line.get("voucher_shopee") or 0)


def _distinct(values) -> list:
    out: list = []
    for v in values:
        if v is not None and v not in out:
            out.append(v)
    return out


def _single(values):
    """Giá trị cấp đơn: đúng 1 giá trị khác nhau -> giá trị đó; còn lại None."""
    vals = _distinct(values)
    return vals[0] if len(vals) == 1 else None


def rollup_order(order_id: str, lines: list) -> dict:
    """Tổng hợp 1 đơn từ các dòng của nó + đối soát AC/AE/AG/AK/AQ/AT."""
    statuses = [ln.get("status") or "" for ln in lines if (ln.get("status") or "")]
    status = Counter(statuses).most_common(1)[0][0] if statuses else ""
    cancelled = is_cancelled(status)
    total_value = 0
    value_ok = True
    for ln in lines:
        v = line_value(ln)
        if v is None:
            value_ok = False
        else:
            total_value += v
    at_vals = _distinct(ln.get("buyer_paid_at") for ln in lines)
    at_inconsistent = len(at_vals) > 1
    at = at_vals[0] if len(at_vals) == 1 else None
    ak = _single(ln.get("shopee_coin") for ln in lines)
    aq = _single(ln.get("ship_buyer") for ln in lines)
    ad = _single(ln.get("order_total_ad") for ln in lines)
    recon = "na"
    recon_diff = None
    recon_variant = ""
    if not cancelled and at is not None and value_ok:
        recon_diff = total_value - at
        if abs(recon_diff) <= RECON_TOLERANCE:
            recon, recon_variant = "ok", "A"
        elif ak is not None and aq is not None:
            diff_b = total_value - ak * 100 + aq - at
            if abs(diff_b) <= RECON_TOLERANCE:
                recon, recon_variant = "ok", "B"
            else:
                recon = "review"
        else:
            recon = "review"
    flagged = at_inconsistent or recon == "review"
    dates = [ln.get("order_date") or "" for ln in lines if ln.get("order_date")]
    return {
        "order_id": order_id,
        "shop": lines[0].get("shop") or "" if lines else "",
        "order_date": min(dates) if dates else "",
        "order_dt": next((ln.get("order_dt") for ln in lines if ln.get("order_dt")), ""),
        "status": status,
        "status_conflict": len(set(statuses)) > 1,
        "cancelled": cancelled,
        "lines": lines,
        "n_lines": len(lines),
        "qty": sum(ln.get("qty") or 0 for ln in lines),
        "qty_returned": sum(ln.get("qty_returned") or 0 for ln in lines),
        "line_value": total_value if value_ok else None,
        "at": at,
        "at_inconsistent": at_inconsistent,
        "ak": ak,
        "aq": aq,
        "ad": ad,
        "recon": recon,
        "recon_variant": recon_variant,
        "recon_diff": recon_diff,
        "flagged": flagged,
        "carrier": next((ln.get("carrier") for ln in lines if ln.get("carrier")), ""),
        "payment_method": next(
            (ln.get("payment_method") for ln in lines if ln.get("payment_method")), ""
        ),
        "province": next((ln.get("province") for ln in lines if ln.get("province")), ""),
        "cancel_reason": next(
            (ln.get("cancel_reason") for ln in lines if ln.get("cancel_reason")), ""
        ),
        "return_status": next(
            (ln.get("return_status") for ln in lines if ln.get("return_status")), ""
        ),
    }


def rollup_orders(lines: list) -> list:
    """Nhóm dòng theo (shop, mã đơn) rồi tổng hợp từng đơn."""
    groups: dict[tuple, list] = {}
    for ln in lines:
        groups.setdefault((ln.get("shop") or "", ln.get("order_id") or ""), []).append(ln)
    return [rollup_order(oid, groups[key]) for key in sorted(groups) for oid in [key[1]]]


# ------------------------------ các chỉ số ---------------------------------

_ORDER_LEVEL_MONEY = (
    ("fee_fixed", "Phí cố định (AX)"),
    ("fee_service", "Phí Dịch Vụ (AY)"),
    ("fee_transaction", "Phí xử lý giao dịch (AZ)"),
    ("ship_est", "Phí vận chuyển dự kiến (AO)"),
    ("ship_buyer", "Phí vận chuyển người mua trả (AQ)"),
    ("ship_sponsored", "Phí vận chuyển Shopee tài trợ (AR)"),
    ("ship_return_fee", "Phí vận chuyển trả hàng (AS)"),
)


def overview_stats(rollups: list) -> dict:
    """Chỉ số Tổng quan trên các đơn đã tổng hợp (phạm vi lọc hiện tại)."""
    active = [r for r in rollups if not r["cancelled"]]
    trend: dict[str, dict] = {}
    for r in rollups:
        d = r["order_date"] or "(không ngày)"
        t = trend.setdefault(d, {"date": d, "orders": 0, "at": 0})
        t["orders"] += 1
        if not r["cancelled"] and r["at"] is not None:
            t["at"] += r["at"]
    return {
        "orders": len(rollups),
        "lines": sum(r["n_lines"] for r in rollups),
        "qty": sum(r["qty"] for r in active),
        "line_value": sum(r["line_value"] or 0 for r in active),
        "at_total": sum(r["at"] for r in active if r["at"] is not None),
        "at_orders": sum(1 for r in active if r["at"] is not None),
        "flagged": sum(1 for r in rollups if r["flagged"]),
        "cancelled": sum(1 for r in rollups if r["cancelled"]),
        "status_dist": Counter(r["status"] or "(trống)" for r in rollups),
        "trend": [trend[d] for d in sorted(trend)],
    }


def product_stats(lines: list) -> list:
    """Gộp theo (tên SP, SKU, SKU phân loại, tên phân loại); loại đơn hủy
    khỏi số bán — đơn hủy được đếm riêng ở cột qty_cancelled."""
    groups: dict[tuple, dict] = {}
    for ln in lines:
        key = (
            ln.get("product_name") or "(không tên)",
            ln.get("sku") or "",
            ln.get("variation_sku") or "",
            ln.get("variation_name") or "",
        )
        g = groups.setdefault(
            key,
            {
                "product_name": key[0],
                "sku": key[1],
                "variation_sku": key[2],
                "variation_name": key[3],
                "orders": set(),
                "lines": 0,
                "qty": 0,
                "qty_returned": 0,
                "qty_cancelled": 0,
                "line_value": 0,
            },
        )
        g["lines"] += 1
        if is_cancelled(ln.get("status") or ""):
            g["qty_cancelled"] += ln.get("qty") or 0
            continue
        g["orders"].add((ln.get("shop") or "", ln.get("order_id") or ""))
        g["qty"] += ln.get("qty") or 0
        g["qty_returned"] += ln.get("qty_returned") or 0
        v = line_value(ln)
        if v is not None:
            g["line_value"] += v
    out = []
    for g in groups.values():
        g["orders"] = len(g["orders"])
        out.append(g)
    out.sort(key=lambda g: (-g["line_value"], -g["qty"], g["product_name"]))
    return out


def finance_stats(lines: list, rollups: list) -> dict:
    """Phân rã giá / voucher / trợ giá / phí. Tiền CẤP DÒNG cộng theo
    dòng; tiền CẤP ĐƠN (phí AX/AY/AZ, vận chuyển, AT, AK, AQ) chỉ cộng
    1 lần/đơn khi các dòng nhất quán — tránh cộng lặp đơn nhiều dòng."""
    active_lines = [ln for ln in lines if not is_cancelled(ln.get("status") or "")]
    active = [r for r in rollups if not r["cancelled"]]

    def ssum(field, mult_qty=False):
        total = 0
        for ln in active_lines:
            v = ln.get(field)
            if v is None:
                continue
            total += v * (ln.get("qty") or 0) if mult_qty else v
        return total

    order_level: dict[str, dict] = {}
    for field, label in _ORDER_LEVEL_MONEY:
        total, n_ok, n_bad = 0, 0, 0
        for r in active:
            v = _single(ln.get(field) for ln in r["lines"])
            if v is None:
                if any(ln.get(field) is not None for ln in r["lines"]):
                    n_bad += 1
            else:
                total += v
                n_ok += 1
        order_level[field] = {"label": label, "total": total, "orders": n_ok, "inconsistent": n_bad}
    ak_total = sum(r["ak"] for r in active if r["ak"] is not None)
    return {
        "gross_original": ssum("price_original", mult_qty=True),
        "promo_total": ssum("price_promo", mult_qty=True),
        "seller_subsidy_total": ssum("seller_subsidy_total"),
        "shopee_subsidy": ssum("shopee_subsidy"),
        "voucher_shop": ssum("voucher_shop"),
        "voucher_shopee": ssum("voucher_shopee"),
        "combo_shopee": ssum("combo_shopee"),
        "combo_shop": ssum("combo_shop"),
        "card_discount": ssum("card_discount"),
        "coin_cashback": ssum("coin_cashback"),
        "line_value": sum(r["line_value"] or 0 for r in active),
        "at_total": sum(r["at"] for r in active if r["at"] is not None),
        "ad_total": sum(r["ad"] for r in active if r["ad"] is not None),
        "ak_xu": ak_total,
        "ak_vnd": ak_total * 100,
        "order_level": order_level,
        "recon_ok": sum(1 for r in active if r["recon"] == "ok"),
        "recon_review": sum(1 for r in active if r["recon"] == "review"),
        "recon_na": sum(1 for r in active if r["recon"] == "na"),
    }


def _days_between(a: str, b: str):
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except (ValueError, TypeError):
        return None


def ops_stats(rollups: list) -> dict:
    """Vận hành: thời gian xử lý/giao, giao trễ, theo ĐVVC + thanh toán."""
    active = [r for r in rollups if not r["cancelled"]]
    proc_days, ship_days = [], []
    late = ontime_known = 0
    carriers: dict[str, dict] = {}
    payments: Counter = Counter()
    for r in active:
        lines = r["lines"]
        o_date = r["order_date"]
        s_date = next((ln.get("ship_date") for ln in lines if ln.get("ship_date")), "")
        d_date = next((ln.get("delivery_date") for ln in lines if ln.get("delivery_date")), "")
        e_date = next((ln.get("expected_date") for ln in lines if ln.get("expected_date")), "")
        p = _days_between(o_date, s_date) if o_date and s_date else None
        s = _days_between(s_date, d_date) if s_date and d_date else None
        if p is not None:
            proc_days.append(p)
        if s is not None:
            ship_days.append(s)
        is_late = None
        if d_date and e_date:
            ontime_known += 1
            is_late = d_date > e_date
            if is_late:
                late += 1
        c = carriers.setdefault(
            r["carrier"] or "(không rõ)",
            {
                "carrier": r["carrier"] or "(không rõ)",
                "orders": 0,
                "proc": [],
                "ship": [],
                "late": 0,
                "late_known": 0,
            },
        )
        c["orders"] += 1
        if p is not None:
            c["proc"].append(p)
        if s is not None:
            c["ship"].append(s)
        if is_late is not None:
            c["late_known"] += 1
            if is_late:
                c["late"] += 1
        payments[r["payment_method"] or "(không rõ)"] += 1

    def avg(vals):
        return round(sum(vals) / len(vals), 2) if vals else None

    carrier_rows = []
    for c in carriers.values():
        carrier_rows.append(
            {
                "carrier": c["carrier"],
                "orders": c["orders"],
                "avg_proc": avg(c["proc"]),
                "avg_ship": avg(c["ship"]),
                "late": c["late"],
                "late_known": c["late_known"],
            }
        )
    carrier_rows.sort(key=lambda c: -c["orders"])
    return {
        "avg_proc": avg(proc_days),
        "n_proc": len(proc_days),
        "avg_ship": avg(ship_days),
        "n_ship": len(ship_days),
        "late": late,
        "late_known": ontime_known,
        "late_pct": round(late * 100 / ontime_known, 1) if ontime_known else None,
        "carriers": carrier_rows,
        "payments": payments.most_common(),
    }


def cancel_stats(rollups: list, lines: list) -> dict:
    """Hủy / trả hàng / hoàn tiền: tỷ lệ + lý do + theo SP/khu vực/ĐVVC."""
    total = len(rollups)
    cancelled = [r for r in rollups if r["cancelled"]]
    returns = [
        r
        for r in rollups
        if not r["cancelled"] and (r["return_status"] or r["qty_returned"] > 0)
    ]
    by_product: Counter = Counter()
    for ln in lines:
        if is_cancelled(ln.get("status") or ""):
            by_product[ln.get("product_name") or "(không tên)"] += ln.get("qty") or 0
    return {
        "total_orders": total,
        "cancelled": len(cancelled),
        "cancel_pct": round(len(cancelled) * 100 / total, 1) if total else None,
        "by_reason": Counter(
            r["cancel_reason"] or "(không ghi lý do)" for r in cancelled
        ).most_common(),
        "by_product": by_product.most_common(10),
        "by_province": Counter(r["province"] or "(không rõ)" for r in cancelled).most_common(),
        "by_carrier": Counter(r["carrier"] or "(không rõ)" for r in cancelled).most_common(),
        "by_date": Counter(r["order_date"] or "(không ngày)" for r in cancelled).most_common(),
        "return_orders": len(returns),
        "qty_returned": sum(r["qty_returned"] for r in returns),
        "return_by_status": Counter(
            r["return_status"] or "(theo số lượng hoàn)" for r in returns
        ).most_common(),
    }


def data_quality(lines: list, rollups: list) -> dict:
    """Tổng hợp vấn đề chất lượng dữ liệu trên phạm vi đang xem."""
    cell_error_lines = []
    for ln in lines:
        errs = ln.get("cell_errors") or ""
        if errs and errs != "[]":
            try:
                fields = json.loads(errs)
            except ValueError:
                fields = [errs]
            if fields:
                cell_error_lines.append(
                    {"order_id": ln.get("order_id"), "shop": ln.get("shop"), "fields": fields}
                )
    unknown_statuses = Counter(
        ln.get("status") or "(trống)"
        for ln in lines
        if (ln.get("status") or "") not in KNOWN_STATUSES
    )
    return {
        "cell_error_lines": cell_error_lines,
        "unknown_statuses": unknown_statuses.most_common(),
        "recon_review": [r for r in rollups if r["recon"] == "review"],
        "at_inconsistent": [r for r in rollups if r["at_inconsistent"]],
        "status_conflicts": [r for r in rollups if r["status_conflict"]],
    }


def shops_for_filter() -> list:
    return db.orders_distinct_shops()
