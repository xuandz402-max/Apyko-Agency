"""Phân tích đơn hàng Shopee (/analysis/don-hang — mục trong Phân tích).

Neo số liệu lấy từ file mẫu thật tests/fixtures/demo_order.xlsx (bản sao
Demo_Order.xlsx của Shopee, 12 dòng / 62 cột):
- 11 đơn hợp lệ + 1 dòng cách ly (trống mã đơn).
- Trạng thái đơn hợp lệ: 6 Đã giao / 4 Đã hủy / 1 Chờ giao hàng.
- Phạm vi ĐÃ GIAO: tổng AT = 977.130đ, tổng giá trị sau voucher
  (AC x AA - AE - AG) = 822.160đ.
- Đối soát: 5/6 đơn đã giao khớp (3 biến thể A, 2 biến thể B). Đơn
  261019284CYC85 bị gắn cờ: dòng thứ hai của nó trong file gốc chính là
  dòng trống mã đơn đã bị cách ly, nên tổng dòng hợp lệ không khớp AT.
"""

import csv
import io
import re
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from conftest import activate, create_owner, create_staff, login, logout

FIXTURE = Path(__file__).parent / "fixtures" / "demo_order.xlsx"


def _db():
    from app import database as db

    return db


def _orders():
    from app import orders

    return orders
SHOP = "Shop Test"
RANGE = "from=2026-01-01&to=2026-12-31"

HEADERS = [
    "Mã đơn hàng", "Mã Kiện Hàng", "Ngày đặt hàng", "Trạng Thái Đơn Hàng",
    "Sản Phẩm Bán Chạy", "Lý do hủy", "Nhận xét từ Người mua", "Mã vận đơn",
    "Đơn Vị Vận Chuyển", "Phương thức giao hàng", "Loại đơn hàng",
    "Ngày giao hàng dự kiến", "Ngày gửi hàng", "Thời gian giao hàng",
    "Trạng thái Trả hàng/Hoàn tiền", "SKU sản phẩm", "Tên sản phẩm",
    "Cân nặng sản phẩm", "Tổng cân nặng", "SKU phân loại hàng",
    "Tên phân loại hàng", "Giá gốc", "Người bán trợ giá",
    "Được Shopee trợ giá", "Tổng số tiền được người bán trợ giá",
    "Giá ưu đãi", "Số lượng", "Số lượng sản phẩm được hoàn trả",
    "Tổng tiền người mua thanh toán trước khi trừ voucher shop và Shopee.",
    "Tổng giá trị đơn hàng (VND)", "Mã giảm giá của Shop", "Hoàn Xu",
    "Mã giảm giá của Shopee", "Chỉ tiêu Combo Khuyến Mãi",
    "Giảm giá từ combo Shopee", "Giảm giá từ Combo của Shop",
    "Shopee Xu được hoàn", "Số tiền được giảm khi thanh toán bằng thẻ Ghi nợ",
    "Trade-in Discount", "Trade-in Bonus", "Phí vận chuyển (dự kiến)",
    "Trade-in Bonus by Seller", "Phí vận chuyển mà người mua trả",
    "Phí vận chuyển tài trợ bởi Shopee (dự kiến)",
    "Phí vận chuyển trả hàng (đơn Trả hàng/hoàn tiền)",
    "Tiền khách thanh toán cuối cùng", "Thời gian hoàn thành đơn hàng",
    "Thời gian đơn hàng được thanh toán", "Phương thức thanh toán",
    "Phí cố định", "Phí Dịch Vụ", "Phí xử lý giao dịch", "Tiền ký quỹ",
    "Người Mua", "Tên Người nhận", "Số điện thoại", "Tỉnh/Thành phố",
    "TP / Quận / Huyện", "Quận", "Địa chỉ nhận hàng", "Quốc gia", "Ghi chú",
]
assert len(HEADERS) == 62


def _row(**kw):
    row = {h: "" for h in HEADERS}
    row.update(
        {
            "Ngày đặt hàng": "2026-10-20 10:00:00",
            "Trạng Thái Đơn Hàng": "Đã giao",
            "Số lượng": "1",
            "Giá gốc": "100000",
            "Giá ưu đãi": "90000",
            "Tổng tiền người mua thanh toán trước khi trừ voucher shop và Shopee.": "90000",
            "Mã giảm giá của Shop": "0",
            "Mã giảm giá của Shopee": "0",
            "Tiền khách thanh toán cuối cùng": "90000",
            "Người Mua": "nguoimua1",
            "Tên Người nhận": "Người Nhận",
            "Số điện thoại": "0909123456",
            "Địa chỉ nhận hàng": "1 Đường Test, Quận 1",
        }
    )
    row.update(kw)
    return [row[h] for h in HEADERS]


def _csv_bytes(rows) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADERS)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def _col_letter(idx: int) -> str:
    s = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        s = chr(65 + rem) + s
    return s


def _xlsx_bytes(rows, sheet_name="orders") -> bytes:
    """XLSX tối thiểu: sheet đặt tên 'orders', ô text dùng inlineStr."""

    all_rows = [HEADERS, *rows]
    body = []
    for ri, row in enumerate(all_rows, start=1):
        cells = ""
        for p, v in enumerate(row):
            if v == "" or v is None:
                continue
            ref = f"{_col_letter(p)}{ri}"
            if re.fullmatch(r"-?\d+(\.\d+)?", str(v)):
                cells += f'<c r="{ref}"><v>{v}</v></c>'
            else:
                cells += (
                    f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>'
                )
        body.append(f'<row r="{ri}">{cells}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(body)}</sheetData></worksheet>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


def _upload(client, content: bytes, filename: str, shop=SHOP):
    return client.post(
        "/analysis/don-hang/import",
        files={"file": (filename, content, "application/octet-stream")},
        data={"shop_new": shop},
    )


def _confirm(client, preview_resp):
    m = re.search(r'name="token" value="([^"]+)"', preview_resp.text)
    assert m, "preview không có token xác nhận"
    return client.post(
        "/analysis/don-hang/import/confirm", data={"token": m.group(1)}
    )


def _import_demo(client):
    create_owner(client)
    raw = FIXTURE.read_bytes()
    preview = _upload(client, raw, "demo_order.xlsx")
    assert preview.status_code == 200
    result = _confirm(client, preview)
    assert result.status_code == 200
    return result


def _delivered_rollups():
    lines = _db().orders_list_lines(
        date_from="2026-01-01", date_to="2026-12-31", status="Đã giao"
    )
    return _orders().rollup_orders(lines)


# ------------------------- file mẫu thật -------------------------


def test_preview_real_file_counts_and_nothing_written(client):
    create_owner(client)
    preview = _upload(client, FIXTURE.read_bytes(), "demo_order.xlsx")
    assert preview.status_code == 200
    # Xem trước: CHƯA ghi gì vào DB.
    assert _db().orders_list_lines() == []
    assert _db().orders_list_imports() == []
    assert "11" in preview.text  # 11 đơn duy nhất
    assert "Cách ly" in preview.text  # 1 dòng trống mã đơn bị cách ly
    result = _confirm(client, preview)
    assert result.status_code == 200
    lines = _db().orders_list_lines()
    assert len(lines) == 11
    assert len(_db().orders_list_quarantine()) == 1
    statuses = Counter(ln["status"] for ln in lines)
    assert statuses == {"Đã giao": 6, "Đã hủy": 4, "Chờ giao hàng": 1}


def test_anchor_totals_delivered_scope(client):
    _import_demo(client)
    rollups = _delivered_rollups()
    ov = _orders().overview_stats(rollups)
    assert ov["orders"] == 6
    assert ov["at_total"] == 977130
    assert ov["line_value"] == 822160
    # Hiện trên giao diện khi lọc trạng thái Đã giao.
    r = client.get(
        f"/analysis/don-hang?tab=tong-quan&{RANGE}&status={quote('Đã giao')}"
    )
    assert r.status_code == 200
    assert "977.130" in r.text
    assert "822.160" in r.text


def test_reconciliation_variants_and_flag(client):
    _import_demo(client)
    by_id = {r["order_id"]: r for r in _delivered_rollups()}
    ok = [r for r in by_id.values() if r["recon"] == "ok"]
    assert len(ok) == 5
    assert Counter(r["recon_variant"] for r in ok) == {"A": 3, "B": 2}
    # Đơn chờ giao hàng khớp nhờ biến thể B (AK x 100).
    waiting = _db().orders_list_lines(status="Chờ giao hàng")
    wr = _orders().rollup_orders(waiting)
    assert len(wr) == 1
    assert wr[0]["recon"] == "ok" and wr[0]["recon_variant"] == "B"
    # Đơn còn lại bị gắn cờ: dòng song sinh của nó là dòng cách ly.
    bad = by_id["261019284CYC85"]
    assert bad["recon"] == "review" and bad["flagged"]
    r = client.get(f"/analysis/don-hang?tab=chat-luong&{RANGE}")
    assert "261019284CYC85" in r.text


def test_reimport_inserts_nothing(client):
    _import_demo(client)
    preview = _upload(client, FIXTURE.read_bytes(), "demo_order.xlsx")
    assert preview.status_code == 200
    assert "đã được nhập trước đây" in preview.text  # cảnh báo trùng hash file
    result = _confirm(client, preview)
    assert result.status_code == 200
    assert len(_db().orders_list_lines()) == 11
    assert len(_db().orders_existing_order_ids(SHOP)) == 11
    ov = _orders().overview_stats(_delivered_rollups())
    assert ov["at_total"] == 977130  # doanh thu không tăng sau khi nạp lại


# ------------------------- đơn nhiều dòng (tự tạo) -------------------------

MULTI_ROWS = [
    # Đơn ML1: 3 dòng, AT cấp đơn lặp giống nhau -> tính 1 lần.
    _row(**{"Mã đơn hàng": "ML1", "Tên sản phẩm": "SP A", "Số lượng": "2",
            "Tổng tiền người mua thanh toán trước khi trừ voucher shop và Shopee.": "90000",
            "Mã giảm giá của Shop": "5000", "Mã giảm giá của Shopee": "3000",
            "Tiền khách thanh toán cuối cùng": "300000"}),
    _row(**{"Mã đơn hàng": "ML1", "Tên sản phẩm": "SP B",
            "Tổng tiền người mua thanh toán trước khi trừ voucher shop và Shopee.": "100000",
            "Mã giảm giá của Shopee": "2000",
            "Tiền khách thanh toán cuối cùng": "300000"}),
    _row(**{"Mã đơn hàng": "ML1", "Tên sản phẩm": "SP C",
            "Tổng tiền người mua thanh toán trước khi trừ voucher shop và Shopee.": "30000",
            "Tiền khách thanh toán cuối cùng": "300000"}),
    # Đơn ML2: 2 dòng GIỐNG HỆT nhau -> giữ cả 2 (occurrence ordinal).
    _row(**{"Mã đơn hàng": "ML2", "Tên sản phẩm": "SP D",
            "Tổng tiền người mua thanh toán trước khi trừ voucher shop và Shopee.": "50000",
            "Tiền khách thanh toán cuối cùng": "100000"}),
    _row(**{"Mã đơn hàng": "ML2", "Tên sản phẩm": "SP D",
            "Tổng tiền người mua thanh toán trước khi trừ voucher shop và Shopee.": "50000",
            "Tiền khách thanh toán cuối cùng": "100000"}),
    # Đơn ML3: AT khác nhau giữa các dòng -> gắn cờ, loại khỏi tổng AT.
    _row(**{"Mã đơn hàng": "ML3", "Tên sản phẩm": "SP E",
            "Tổng tiền người mua thanh toán trước khi trừ voucher shop và Shopee.": "40000",
            "Tiền khách thanh toán cuối cùng": "90000"}),
    _row(**{"Mã đơn hàng": "ML3", "Tên sản phẩm": "SP F",
            "Tổng tiền người mua thanh toán trước khi trừ voucher shop và Shopee.": "50000",
            "Tiền khách thanh toán cuối cùng": "95000"}),
]


def test_multiline_csv_aggregation(client):
    create_owner(client)
    preview = _upload(client, _csv_bytes(MULTI_ROWS), "multi.csv")
    assert preview.status_code == 200
    assert _confirm(client, preview).status_code == 200
    lines = _db().orders_list_lines()
    assert len(lines) == 7  # cả 2 dòng sinh đôi của ML2 đều được giữ
    rollups = {r["order_id"]: r for r in _orders().rollup_orders(lines)}
    ml1 = rollups["ML1"]
    assert ml1["n_lines"] == 3
    # Dòng SL=2 tính AC x AA: 90000x2 - 5000 - 3000 = 172000.
    assert ml1["line_value"] == 172000 + 98000 + 30000
    assert ml1["at"] == 300000  # AT tính đúng 1 lần, không x3
    assert ml1["recon"] == "ok"
    ml2 = rollups["ML2"]
    assert ml2["n_lines"] == 2 and ml2["line_value"] == 100000
    ml3 = rollups["ML3"]
    assert ml3["at_inconsistent"] and ml3["at"] is None and ml3["flagged"]
    ov = _orders().overview_stats(list(rollups.values()))
    assert ov["at_total"] == 400000  # ML3 bị loại khỏi tổng AT


def test_multiline_xlsx_sheet_orders(client):
    create_owner(client)
    rows = MULTI_ROWS[:2]  # 2 dòng đầu của ML1
    preview = _upload(client, _xlsx_bytes(rows), "multi.xlsx")
    assert preview.status_code == 200
    assert _confirm(client, preview).status_code == 200
    lines = _db().orders_list_lines()
    assert len(lines) == 2
    rollup = _orders().rollup_orders(lines)[0]
    assert rollup["order_id"] == "ML1"
    assert rollup["line_value"] == 172000 + 98000
    assert rollup["at"] == 300000


# ------------------------- phân quyền -------------------------


def test_section_requires_can_view_orders(client):
    _import_demo(client)
    code = create_staff(client, "nv1", perms=("can_view_products",))
    logout(client)
    activate(client, "nv1", code)
    r = client.get("/analysis")
    assert r.status_code == 200
    assert "Đơn hàng Shopee" not in r.text  # không thấy mục chuyển mục
    r = client.get("/analysis/don-hang")
    assert r.status_code == 403
    r = client.get(f"/analysis/don-hang/don/261018VUCSNGU4?shop={quote(SHOP)}")
    assert r.status_code == 403


def test_finance_stripped_server_side(client):
    _import_demo(client)
    login(client, "chushop", "matkhau123")
    code = create_staff(
        client, "nvfin", perms=("can_view_products", "can_view_orders")
    )
    logout(client)
    activate(client, "nvfin", code)
    r = client.get(f"/analysis/don-hang?tab=tong-quan&{RANGE}")
    assert r.status_code == 200
    assert "977.130" not in r.text and "822.160" not in r.text
    assert "1.035.980" not in r.text  # tổng AT mọi trạng thái không hủy
    r = client.get(f"/analysis/don-hang?tab=gia&{RANGE}")
    assert r.status_code == 403  # tab tài chính bị chặn ở server
    r = client.get(f"/analysis/don-hang?tab=don-hang&{RANGE}")
    assert r.status_code == 200 and "977.130" not in r.text


def test_pii_masked_and_reveal_audited(client):
    _import_demo(client)
    buyer = _db().orders_get_buyer(SHOP, "261018VUCSNGU4")
    assert buyer and buyer["phone"]
    login(client, "chushop", "matkhau123")
    code_no = create_staff(
        client, "nvpii0", perms=("can_view_products", "can_view_orders")
    )
    code_yes = create_staff(
        client,
        "nvpii1",
        perms=("can_view_products", "can_view_orders", "can_view_buyer_pii"),
    )
    logout(client)
    url = f"/analysis/don-hang/don/261018VUCSNGU4?shop={quote(SHOP)}"
    activate(client, "nvpii0", code_no)
    r = client.get(url)
    assert r.status_code == 200
    assert buyer["phone"] not in r.text and buyer["address"] not in r.text
    r = client.post(
        f"/analysis/don-hang/don/261018VUCSNGU4/reveal?shop={quote(SHOP)}"
    )
    assert r.status_code == 403  # không có quyền mở PII
    logout(client)
    activate(client, "nvpii1", code_yes)
    r = client.get(url)
    assert buyer["phone"] not in r.text  # vẫn che cho tới khi bấm mở
    r = client.post(
        f"/analysis/don-hang/don/261018VUCSNGU4/reveal?shop={quote(SHOP)}"
    )
    assert r.status_code == 200
    assert buyer["phone"] in r.text and buyer["address"] in r.text
    actions = [a["action"] for a in _db().orders_list_audit()]
    assert "reveal_pii" in actions  # đã ghi nhật ký


def test_import_and_export_permissions(client):
    _import_demo(client)
    login(client, "chushop", "matkhau123")
    code = create_staff(
        client, "nvio", perms=("can_view_products", "can_view_orders")
    )
    logout(client)
    activate(client, "nvio", code)
    r = _upload(client, FIXTURE.read_bytes(), "demo_order.xlsx")
    assert r.status_code == 403  # thiếu can_import_orders
    r = client.get(f"/analysis/don-hang/export?{RANGE}")
    assert r.status_code == 403  # thiếu can_export_orders
    logout(client)
    login(client, "chushop", "matkhau123")
    r = client.get(f"/analysis/don-hang/export?{RANGE}")
    assert r.status_code == 200
    assert "261018VUCSNGU4" in r.text
    assert "Người mua" in r.text  # chủ shop có quyền PII -> có cột PII
    assert any(a["action"] == "export" for a in _db().orders_list_audit())


def test_order_permission_defaults(client):
    create_owner(client)
    owner = _db().get_user_by_username("chushop")
    for flag in (
        "can_view_orders", "can_view_order_finance", "can_import_orders",
        "can_export_orders", "can_view_buyer_pii",
    ):
        assert owner[flag] == 1
    code = create_staff(client, "nvdef", perms=("can_view_products",))
    activate(client, "nvdef", code)
    staff = _db().get_user_by_username("nvdef")
    for flag in (
        "can_view_orders", "can_view_order_finance", "can_import_orders",
        "can_export_orders", "can_view_buyer_pii",
    ):
        assert staff[flag] == 0  # fail-closed cho tài khoản mới


def test_batch_delete_removes_only_own_lines(client):
    _import_demo(client)
    batch = _db().orders_list_imports()[0]
    r = client.post(f"/analysis/don-hang/import/{batch['id']}/delete")
    assert r.status_code == 200
    assert _db().orders_list_lines() == []
    assert any(a["action"] == "delete_batch" for a in _db().orders_list_audit())
