"""Nạp dữ liệu từ Excel/CSV thay nhập tay (pure logic, chỉ dùng stdlib).

Hai luồng dùng module này:
- GMV Max: file xuất từ Shopee Ads (hoặc file tự lập) -> gmv_entries.
- Báo cáo ngày: file Excel/CSV doanh thu theo ngày -> daily_reports.

Nguyên tắc:
- KHÔNG thêm thư viện ngoài (gói Windows của user cài offline từ wheels):
  CSV qua module csv; XLSX tự parse bằng zipfile + xml.etree
  (sharedStrings + sheet đầu tiên; ngày dạng serial Excel được đổi theo
  epoch 1899-12-30, kể cả khi ô có style ngày tháng).
- Ánh xạ cột theo BÍ DANH, không phân biệt hoa thường và dấu tiếng Việt.
- TIỀN GMV LƯU BẰNG VNĐ: gmv_entries lưu revenue_vnd/ad_cost bằng VNĐ,
  đúng như file Shopee Việt Nam ghi. map_gmv_rows giữ nguyên số tiền.
  nguyên. Báo cáo ngày mọi số đã là VNĐ, không quy đổi.
- Module này chỉ ĐỌC + ÁNH XẠ (không ghi DB). Việc ghi nằm ở routes sau
  khi user xem trước và bấm xác nhận.
"""

import csv
import io
import re
import unicodedata
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree

from .daily import validate_daily_report
from .gmv import validate_gmv_entry

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000

_EXCEL_EPOCH = date(1899, 12, 30)
# Serial Excel hợp lệ cho ngày tháng thực tế (1954 .. 2064 khoảng).
_SERIAL_MIN, _SERIAL_MAX = 20000, 60000

# ------------------------------- bí danh cột -------------------------------
# Khóa = tên field nội bộ; giá trị = các tên cột có thể gặp trong file.
# So khớp SAU khi chuẩn hóa (bỏ dấu, thường hóa, gộp khoảng trắng, bỏ
# phần trong ngoặc đơn) nên chỉ cần liệt kê dạng gốc có dấu/không dấu.

GMV_ALIASES = {
    "date": ["ngày", "date", "thời gian"],
    "product": ["tên sản phẩm", "sản phẩm", "product name", "product", "tên hàng"],
    "views": ["lượt xem", "lượt hiển thị", "views", "impressions", "hiển thị"],
    "clicks": ["lượt nhấp", "lượt click", "clicks", "nhấp chuột"],
    "conversions": ["đơn hàng", "chuyển đổi", "orders", "conversions", "lượt mua"],
    "revenue": ["gmv", "doanh thu", "revenue", "tổng gmv", "doanh số"],
    "ad_cost": [
        "chi phí",
        "chi phí quảng cáo",
        "cost",
        "ad cost",
        "ad spend",
        "tiền quảng cáo",
    ],
}

DAILY_ALIASES = {
    "date": ["ngày", "date", "thời gian"],
    "rev_product": ["doanh thu sản phẩm", "sp"],
    "rev_live": ["live", "livestream"],
    "rev_video": ["video"],
    "rev_aff_link": ["aff link", "link affiliate"],
    "rev_affiliate": ["affiliate", "hoa hồng affiliate"],
    "ad_gmv": ["gmv quảng cáo", "ad gmv"],
    "ad_cost": ["chi phí ads", "chi phí quảng cáo", "ad cost"],
    "aov": ["aov", "giá trị đơn trung bình"],
    "conv_rate": ["tỷ lệ chuyển đổi", "cr", "conversion rate"],
    "note": ["ghi chú", "note"],
}

GMV_REQUIRED = ["date", "product", "revenue", "ad_cost"]
DAILY_REQUIRED = ["date"]

# Nhãn tiếng Việt cho thông báo lỗi cấp file.
_FIELD_LABELS = {
    "date": "Ngày",
    "product": "Tên sản phẩm",
    "revenue": "GMV/Doanh thu",
    "ad_cost": "Chi phí quảng cáo",
}


def _strip_accents(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize_header(header) -> str:
    """Chuẩn hóa tên cột để so bí danh: bỏ ngoặc, bỏ dấu, thường, gộp trắng."""
    s = str(header or "")
    s = re.sub(r"\([^)]*\)", " ", s)  # "GMV (VNĐ)" -> "GMV"
    s = _strip_accents(s).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _alias_index(aliases: dict) -> dict:
    """{tên cột đã chuẩn hóa: field} — field khai trước thắng nếu trùng."""
    index: dict[str, str] = {}
    for field, names in aliases.items():
        for name in names:
            index.setdefault(normalize_header(name), field)
    return index


def match_columns(headers: list, aliases: dict) -> tuple:
    """Trả về (mapping {field: vị trí cột}, [tên cột không nhận diện được])."""
    index = _alias_index(aliases)
    mapping: dict[str, int] = {}
    unknown: list[str] = []
    for pos, header in enumerate(headers):
        field = index.get(normalize_header(header))
        if field is not None and field not in mapping:
            mapping[field] = pos
        elif field is None and str(header or "").strip():
            unknown.append(str(header).strip())
    return mapping, unknown


def unmatched_headers(headers: list, kind: str) -> list:
    """Danh sách cột trong file mà app không nhận diện được (để báo user)."""
    aliases = GMV_ALIASES if kind == "gmv" else DAILY_ALIASES
    return match_columns(headers, aliases)[1]


# ------------------------------- đọc file ---------------------------------


def read_table(file_bytes: bytes, filename: str) -> tuple:
    """Đọc file .csv/.xlsx -> (headers, rows) đều là list[str].

    Raises ValueError với câu tiếng Việt khi file sai định dạng/quá lớn/
    quá nhiều dòng.
    """
    if file_bytes is None or len(file_bytes) == 0:
        raise ValueError("File trống — hãy chọn file có dữ liệu.")
    if len(file_bytes) > MAX_FILE_BYTES:
        raise ValueError("File quá lớn (tối đa 5MB) — hãy xuất lại với khoảng ngày ngắn hơn.")
    name = (filename or "").lower()
    if name.endswith(".csv"):
        raw_rows = _read_csv(file_bytes)
    elif name.endswith(".xlsx"):
        raw_rows = _read_xlsx(file_bytes)
    else:
        raise ValueError("Chỉ nhận file .csv hoặc .xlsx — file bạn chọn không đúng định dạng.")
    rows = [[("" if c is None else str(c)) for c in row] for row in raw_rows]
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise ValueError("File không có dòng dữ liệu nào.")
    headers = [h.strip() for h in rows[0]]
    if not any(headers):
        raise ValueError("File thiếu dòng tiêu đề cột.")
    data_rows = rows[1:]
    if len(data_rows) > MAX_ROWS:
        raise ValueError(f"File có quá nhiều dòng (tối đa {MAX_ROWS:,} dòng dữ liệu).")
    return headers, data_rows


# --------------------- đọc file ĐƠN HÀNG Shopee ---------------------------
# File đơn xuất từ Shopee Seller Centre: 62 cột cố định, có thể rất dài.
# Giới hạn riêng (lớn hơn hẳn file GMV/ngày): 20MB / 50.000 dòng.
# XLSX: ưu tiên sheet tên "orders" (sheet chuẩn của Shopee), không có
# thì lấy sheet đầu tiên như read_table.

ORDER_MAX_FILE_BYTES = 20 * 1024 * 1024
ORDER_MAX_ROWS = 50000
ORDER_SHEET_NAME = "orders"


def read_order_table(file_bytes: bytes, filename: str) -> tuple:
    """Đọc file đơn Shopee .csv/.xlsx -> (headers, rows).

    headers/rows là list[str] như read_table. Raises ValueError tiếng
    Việt khi file sai định dạng/quá lớn/quá nhiều dòng.
    """
    if file_bytes is None or len(file_bytes) == 0:
        raise ValueError("File trống — hãy chọn file có dữ liệu.")
    if len(file_bytes) > ORDER_MAX_FILE_BYTES:
        raise ValueError(
            "File quá lớn (tối đa 20MB) — hãy xuất lại với khoảng ngày ngắn hơn."
        )
    name = (filename or "").lower()
    if name.endswith(".csv"):
        raw_rows = _read_csv(file_bytes)
    elif name.endswith(".xlsx"):
        raw_rows = _read_xlsx(file_bytes, sheet_name=ORDER_SHEET_NAME)
    else:
        raise ValueError("Chỉ nhận file .csv hoặc .xlsx — file bạn chọn không đúng định dạng.")
    rows = [[("" if c is None else str(c)) for c in row] for row in raw_rows]
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise ValueError("File không có dòng dữ liệu nào.")
    headers = [h.strip() for h in rows[0]]
    if not any(headers):
        raise ValueError("File thiếu dòng tiêu đề cột.")
    data_rows = rows[1:]
    if len(data_rows) > ORDER_MAX_ROWS:
        raise ValueError(
            f"File có quá nhiều dòng (tối đa {ORDER_MAX_ROWS:,} dòng dữ liệu)."
        )
    return headers, data_rows


def _read_csv(file_bytes: bytes) -> list:
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(
            "Không đọc được file CSV (cần mã hóa UTF-8). "
            "Hãy mở file bằng Excel rồi lưu lại dạng CSV UTF-8."
        ) from None
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return list(csv.reader(io.StringIO(text), dialect))


# ---- XLSX: parse tối thiểu bằng zipfile + XML (không thư viện ngoài) ----

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
# numFmtId có sẵn của Excel thuộc nhóm ngày tháng.
_BUILTIN_DATE_FMTS = {
    14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 28, 29, 30, 31, 32, 33, 34, 35,
    36, 45, 46, 47, 50, 57,
}
_DATE_CODE_RE = re.compile(r"yyyy|yy|dd|mmm|mm", re.IGNORECASE)


def _xlsx_date_style_indexes(zf: zipfile.ZipFile) -> set:
    """Tập chỉ số style (cellXfs) có định dạng ngày tháng."""
    try:
        raw = zf.read("xl/styles.xml")
    except KeyError:
        return set()
    root = ElementTree.fromstring(raw)
    custom_codes = {}
    num_fmts = root.find(f"{_NS}numFmts")
    if num_fmts is not None:
        for fmt in num_fmts:
            code = fmt.get("formatCode") or ""
            if _DATE_CODE_RE.search(code):
                custom_codes[int(fmt.get("numFmtId"))] = True
    date_ids = _BUILTIN_DATE_FMTS | set(custom_codes)
    indexes = set()
    cell_xfs = root.find(f"{_NS}cellXfs")
    if cell_xfs is not None:
        for i, xf in enumerate(cell_xfs):
            try:
                fmt_id = int(xf.get("numFmtId") or 0)
            except ValueError:
                continue
            if fmt_id in date_ids:
                indexes.add(i)
    return indexes


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> list:
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ElementTree.fromstring(raw)
    strings = []
    for si in root:
        text = "".join(t.text or "" for t in si.iter(f"{_NS}t"))
        strings.append(text)
    return strings


def _col_index(cell_ref: str) -> int:
    """'B3' -> 1 (cột B, tính từ 0)."""
    letters = ""
    for ch in cell_ref or "":
        if ch.isalpha():
            letters += ch
        else:
            break
    idx = 0
    for ch in letters.upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1 if letters else 0


def _serial_to_iso(value: float) -> str:
    return (_EXCEL_EPOCH + timedelta(days=int(value))).isoformat()


def _xlsx_sheet_path(zf: zipfile.ZipFile, sheet_name: str) -> str | None:
    """Part của sheet theo TÊN hiển thị (qua workbook.xml + rels).

    File Shopee xuất có sheet tên 'orders' nhưng part bên trong không
    nhất thiết là sheet1.xml — phải tra quan hệ r:id -> Target.
    Không tra được -> None (caller tự quay về sheet đầu tiên).
    """
    try:
        wb_root = ElementTree.fromstring(zf.read("xl/workbook.xml"))
        rels_root = ElementTree.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ElementTree.ParseError):
        return None
    rel_ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    r_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    targets: dict[str, str] = {}
    for rel in rels_root.iter(f"{rel_ns}Relationship"):
        rid, target = rel.get("Id"), rel.get("Target") or ""
        if rid and target:
            if target.startswith("/"):
                target = target.lstrip("/")
            elif not target.startswith("xl/"):
                target = "xl/" + target
            targets[rid] = target
    sheets_el = wb_root.find(f"{_NS}sheets")
    if sheets_el is None:
        return None
    for sh in sheets_el:
        if (sh.get("name") or "") == sheet_name:
            return targets.get(sh.get(f"{r_ns}id") or "")
    return None


def _read_xlsx(file_bytes: bytes, sheet_name: str | None = None) -> list:
    try:
        zf = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile:
        raise ValueError("File .xlsx không hợp lệ (không mở được gói Excel).") from None
    with zf:
        names = zf.namelist()
        sheet_names = sorted(
            n
            for n in names
            if n.startswith("xl/worksheets/") and n.endswith(".xml")
        )
        if not sheet_names:
            raise ValueError("File .xlsx không có trang tính nào.")
        sheet_part = sheet_names[0]
        if sheet_name:
            named = _xlsx_sheet_path(zf, sheet_name)
            if named and named in names:
                sheet_part = named
        shared = _xlsx_shared_strings(zf)
        date_styles = _xlsx_date_style_indexes(zf)
        try:
            root = ElementTree.fromstring(zf.read(sheet_part))
        except ElementTree.ParseError:
            raise ValueError("File .xlsx bị lỗi cấu trúc — hãy xuất lại từ Excel/Shopee.") from None
    sheet_data = root.find(f"{_NS}sheetData")
    if sheet_data is None:
        return []
    rows: list = []
    for row_el in sheet_data:
        cells: dict[int, str] = {}
        for c in row_el:
            if not c.tag.endswith("}c"):
                continue
            pos = _col_index(c.get("r") or "")
            ctype = c.get("t") or ""
            v_el = c.find(f"{_NS}v")
            raw = v_el.text if v_el is not None else None
            if ctype == "s":
                try:
                    value = shared[int(raw)] if raw is not None else ""
                except (ValueError, IndexError):
                    value = ""
            elif ctype == "inlineStr":
                is_el = c.find(f"{_NS}is")
                value = (
                    "".join(t.text or "" for t in is_el.iter(f"{_NS}t"))
                    if is_el is not None
                    else ""
                )
            elif ctype == "b":
                value = "TRUE" if raw == "1" else "FALSE"
            elif raw is None:
                value = ""
            else:
                value = raw
                # Ô số có style ngày tháng -> đổi serial sang ISO ngay.
                style = c.get("s")
                if style is not None and date_styles:
                    try:
                        if int(style) in date_styles:
                            num = float(raw)
                            if _SERIAL_MIN <= num <= _SERIAL_MAX + 1:
                                value = _serial_to_iso(num)
                    except ValueError:
                        pass
            cells[pos] = value
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(i, "") for i in range(width)])
        else:
            rows.append([])
    return rows


# ------------------------------ parse số ----------------------------------


def parse_number(text) -> float | None:
    """Đọc số chịu nhiều định dạng: '1.234.567', '1,234,567', '500.000₫',
    'VND 12.5', '12,5', khoảng trắng thừa. Rỗng/không đọc được -> None."""
    if text is None or isinstance(text, bool):
        return None
    if isinstance(text, int | float):
        return float(text)
    s = str(text).strip().replace("\u00a0", " ").replace(" ", "")
    if not s:
        return None
    s = re.sub(r"(?i)vnđ|vnd|rm", "", s).replace("₫", "").replace("đ", "")
    s = s.rstrip("%")
    if not s:
        return None
    negative = s.startswith("-")
    body = s[1:] if negative or s.startswith("+") else s
    if not re.fullmatch(r"[0-9.,]+", body):
        return None
    has_dot, has_comma = "." in body, "," in body
    if has_dot and has_comma:
        if body.rfind(",") > body.rfind("."):
            body = body.replace(".", "").replace(",", ".")
        else:
            body = body.replace(",", "")
    elif has_comma:
        if re.fullmatch(r"\d{1,3}(,\d{3})+", body):
            body = body.replace(",", "")
        elif body.count(",") == 1:
            body = body.replace(",", ".")
        else:
            return None
    elif has_dot:
        if body.count(".") > 1:
            if not re.fullmatch(r"\d{1,3}(\.\d{3})+", body):
                return None
            body = body.replace(".", "")
        else:
            head, _, tail = body.partition(".")
            if len(tail) == 3 and head not in ("", "0"):
                body = head + tail  # 500.000 kiểu VN = 500000
    try:
        value = float(body)
    except ValueError:
        return None
    return -value if negative else value


# ------------------------------ parse ngày ---------------------------------

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y")


def parse_date(value) -> str | None:
    """Đổi nhiều dạng ngày về ISO 'YYYY-MM-DD'; không đọc được -> None.

    Chấp nhận: datetime/date, text ISO, dd/mm/yyyy, serial Excel (số hoặc
    chuỗi toàn số trong khoảng serial hợp lệ).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, int | float) and not isinstance(value, bool):
        if _SERIAL_MIN <= value <= _SERIAL_MAX:
            return _serial_to_iso(float(value))
        return None
    s = str(value).strip()
    if not s:
        return None
    head = re.split(r"[ T]", s, maxsplit=1)[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(head, fmt).date().isoformat()
        except ValueError:
            continue
    num = parse_number(s)
    if num is not None and _SERIAL_MIN <= num <= _SERIAL_MAX and float(num).is_integer():
        return _serial_to_iso(num)
    return None


# ------------------------------ ánh xạ dòng --------------------------------


def _cell(row: list, mapping: dict, field: str) -> str:
    pos = mapping.get(field)
    if pos is None or pos >= len(row):
        return ""
    return str(row[pos] or "").strip()


def _require_columns(mapping: dict, required: list) -> None:
    missing = [f for f in required if f not in mapping]
    if missing:
        labels = ", ".join(_FIELD_LABELS.get(f, f) for f in missing)
        raise ValueError(
            f"File thiếu cột bắt buộc: {labels}. "
            "Hãy kiểm tra dòng tiêu đề của file hoặc dùng file mẫu."
        )


def _mark_duplicates(mapped: list, key_of) -> None:
    """Trùng khóa trong cùng file: dòng CUỐI thắng, dòng trước -> 'dup'.

    key_of nhận cả item (gồm product_name/date ở cấp ngoài data) và trả
    khóa so trùng. Dòng 'dup' giữ nguyên data để xem trước, nhưng bước
    xác nhận chỉ ghi dòng 'ok'.
    """
    seen: dict = {}
    for item in mapped:
        if item["status"] != "ok":
            continue
        key = key_of(item)
        if key in seen:
            prev = seen[key]
            prev["status"] = "dup"
            prev["warnings"].append(
                f"Trùng với dòng {item['row']} trong file — chỉ dòng cuối được ghi."
            )
            item["warnings"].append(
                f"Ghi đè dòng {prev['row']} (trùng trong cùng file)."
            )
        seen[key] = item


def map_gmv_rows(headers: list, rows: list) -> list:
    """Ánh xạ dòng file -> entry GMV (số tiền giữ nguyên bằng VNĐ).

    Trả list dict: {row, status: ok|error|dup, errors, warnings,
    data}. Thiếu cột bắt buộc -> ValueError (lỗi cấp file).
    """
    mapping, _unknown = match_columns(headers, GMV_ALIASES)
    _require_columns(mapping, GMV_REQUIRED)
    mapped: list = []
    for i, row in enumerate(rows, start=2):
        errors: list[str] = []
        product_name = _cell(row, mapping, "product")
        if not product_name:
            errors.append("Thiếu tên sản phẩm.")
        date_iso = parse_date(_cell(row, mapping, "date"))
        if date_iso is None:
            errors.append(f"Ngày không đọc được: '{_cell(row, mapping, 'date')}'.")
        numbers: dict = {}
        for field, label, required in (
            ("revenue", "GMV/Doanh thu", True),
            ("ad_cost", "Chi phí quảng cáo", True),
            ("views", "Lượt xem", False),
            ("clicks", "Lượt click", False),
            ("conversions", "Chuyển đổi", False),
        ):
            raw = _cell(row, mapping, field)
            if raw == "":
                if required:
                    errors.append(f"Thiếu {label}.")
                numbers[field] = 0.0
                continue
            val = parse_number(raw)
            if val is None:
                errors.append(f"{label} không đọc được số: '{raw}'.")
                numbers[field] = 0.0
            elif val < 0:
                errors.append(f"{label} không được âm.")
                numbers[field] = val
            else:
                numbers[field] = val
        _int_labels = {"views": "Lượt xem", "clicks": "Lượt click", "conversions": "Chuyển đổi"}
        for field in ("views", "clicks", "conversions"):
            if numbers[field] and not float(numbers[field]).is_integer():
                errors.append(f"{_int_labels[field]} phải là số nguyên.")
        if errors:
            mapped.append(
                {
                    "row": i,
                    "status": "error",
                    "errors": errors,
                    "warnings": [],
                    "data": None,
                    "product_name": product_name,
                    "date": date_iso,
                }
            )
            continue
        data = {
            "date": date_iso,
            "views": int(numbers["views"]),
            "clicks": int(numbers["clicks"]),
            "conversions": int(numbers["conversions"]),
            "revenue_vnd": round(numbers["revenue"], 2),
            "ad_cost": round(numbers["ad_cost"], 2),
            "action_note": "",
        }
        clean, verr = validate_gmv_entry(data)
        if verr:
            mapped.append(
                {
                    "row": i,
                    "status": "error",
                    "errors": [f"{k}: {v}" for k, v in verr.items()],
                    "warnings": [],
                    "data": None,
                    "product_name": product_name,
                    "date": date_iso,
                }
            )
            continue
        mapped.append(
            {
                "row": i,
                "status": "ok",
                "errors": [],
                "warnings": [],
                "data": clean,
                "product_name": product_name,
                "date": date_iso,
            }
        )
    _mark_duplicates(
        mapped,
        lambda it: (" ".join((it["product_name"] or "").split()).lower(), it["date"]),
    )
    return mapped


def map_daily_rows(headers: list, rows: list) -> list:
    """Ánh xạ dòng file -> báo cáo ngày (khóa đúng daily_upsert, VNĐ).

    Trả list dict như map_gmv_rows. Thiếu cột ngày -> ValueError.
    """
    mapping, _unknown = match_columns(headers, DAILY_ALIASES)
    _require_columns(mapping, DAILY_REQUIRED)
    money_fields = [
        "rev_product",
        "rev_live",
        "rev_video",
        "rev_aff_link",
        "rev_affiliate",
        "ad_gmv",
        "ad_cost",
        "aov",
    ]
    mapped: list = []
    for i, row in enumerate(rows, start=2):
        errors: list[str] = []
        date_iso = parse_date(_cell(row, mapping, "date"))
        if date_iso is None:
            errors.append(f"Ngày không đọc được: '{_cell(row, mapping, 'date')}'.")
        data: dict = {"date": date_iso or ""}
        for field in money_fields:
            raw = _cell(row, mapping, field)
            if raw == "":
                data[field] = 0
                continue
            val = parse_number(raw)
            if val is None:
                errors.append(f"Cột {field}: không đọc được số '{raw}'.")
                data[field] = 0
            elif val < 0:
                errors.append(f"Cột {field}: không được âm.")
                data[field] = val
            else:
                data[field] = round(val)
        raw_cr = _cell(row, mapping, "conv_rate")
        if raw_cr == "":
            data["conv_rate"] = 0
        else:
            cr = parse_number(raw_cr)
            if cr is None:
                errors.append(f"Tỷ lệ chuyển đổi không đọc được: '{raw_cr}'.")
                data["conv_rate"] = 0
            else:
                data["conv_rate"] = cr
        data["note"] = _cell(row, mapping, "note")
        if errors:
            mapped.append(
                {
                    "row": i,
                    "status": "error",
                    "errors": errors,
                    "warnings": [],
                    "data": None,
                    "date": date_iso,
                }
            )
            continue
        clean, verr = validate_daily_report(data)
        if verr:
            mapped.append(
                {
                    "row": i,
                    "status": "error",
                    "errors": [f"{k}: {v}" for k, v in verr.items()],
                    "warnings": [],
                    "data": None,
                    "date": date_iso,
                }
            )
            continue
        mapped.append(
            {
                "row": i,
                "status": "ok",
                "errors": [],
                "warnings": [],
                "data": clean,
                "date": date_iso,
            }
        )
    _mark_duplicates(mapped, lambda it: it["date"])
    return mapped
