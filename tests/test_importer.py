"""Nạp Excel/CSV: parser stdlib (CSV + XLSX tự parse), ánh xạ bí danh,
quy đổi VNĐ->RM, kỷ luật xem trước -> xác nhận, phân quyền."""

import io
import re
import zipfile

import pytest
from app import importer
from conftest import activate, create_owner, create_staff, logout

# ------------------------------- parse_number ------------------------------


@pytest.mark.parametrize(
    "text,want",
    [
        ("1.234.567", 1234567.0),
        ("1,234,567", 1234567.0),
        ("500.000₫", 500000.0),
        ("RM 12.5", 12.5),
        ("12,5", 12.5),
        ("1.234.567,89", 1234567.89),
        ("1,234,567.89", 1234567.89),
        ("530000", 530000.0),
        ("0", 0.0),
        ("-5", -5.0),
        (" 1 234 567 ", 1234567.0),
        ("", None),
        ("   ", None),
        ("abc", None),
        (None, None),
        (250, 250.0),
    ],
)
def test_parse_number(text, want):
    assert importer.parse_number(text) == want


def test_parse_date_variants():
    assert importer.parse_date("2026-10-19") == "2026-10-19"
    assert importer.parse_date("19/10/2026") == "2026-10-19"
    assert importer.parse_date("2026-10-19 00:00:00") == "2026-10-19"
    assert importer.parse_date("không phải ngày") is None
    assert importer.parse_date("") is None


def test_parse_date_excel_serial():
    # Serial Excel: 45931 = 2025-10-01 (epoch 1899-12-30).
    assert importer.parse_date(45931) == "2025-10-01"
    assert importer.parse_date("45931") == "2025-10-01"


# ------------------------------- read_table --------------------------------

GMV_CSV = (
    "Ngày,Tên sản phẩm,Lượt xem,Lượt click,Đơn hàng,GMV,Chi phí quảng cáo\n"
    '19/10/2026,SP IMPORT A,1000,50,10,"1.590.000","159.000"\n'
    "2026-10-20,SP IMPORT A,2000,80,20,3180000,318000\n"
).encode("utf-8-sig")


def test_read_csv_utf8_bom():
    headers, rows = importer.read_table(GMV_CSV, "gmv.csv")
    assert headers[0] == "Ngày"
    assert len(rows) == 2
    assert rows[0][1] == "SP IMPORT A"


def test_read_table_bad_extension():
    with pytest.raises(ValueError, match="chỉ nhận file|Chỉ nhận file"):
        importer.read_table(b"abc", "file.txt")


def test_read_table_empty():
    with pytest.raises(ValueError):
        importer.read_table(b"", "file.csv")


def test_read_table_too_big():
    big = b"x" * (importer.MAX_FILE_BYTES + 1)
    with pytest.raises(ValueError, match="quá lớn"):
        importer.read_table(big, "file.csv")


def _make_xlsx(shared: list, rows_spec: list, styles_xml: str = "") -> bytes:
    """Sinh file xlsx tối thiểu: sharedStrings + sheet1.

    rows_spec: list các dòng; mỗi ô là (giá trị, kiểu, style_index|None)
    với kiểu 's' (shared string index), 'n' (số), 'inline'.
    """
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    ss = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<sst {ns} count="{len(shared)}" uniqueCount="{len(shared)}">'
        + "".join(f"<si><t>{s}</t></si>" for s in shared)
        + "</sst>"
    )
    body = []
    for r_idx, row in enumerate(rows_spec, start=1):
        cells = []
        for c_idx, (val, kind, style) in enumerate(row):
            col = chr(ord("A") + c_idx)
            s_attr = f' s="{style}"' if style is not None else ""
            if kind == "s":
                cells.append(f'<c r="{col}{r_idx}" t="s"{s_attr}><v>{val}</v></c>')
            elif kind == "inline":
                cells.append(
                    f'<c r="{col}{r_idx}" t="inlineStr"{s_attr}><is><t>{val}</t></is></c>'
                )
            else:
                cells.append(f'<c r="{col}{r_idx}"{s_attr}><v>{val}</v></c>')
        body.append(f'<row r="{r_idx}">' + "".join(cells) + "</row>")
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<worksheet {ns}><sheetData>" + "".join(body) + "</sheetData></worksheet>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/sharedStrings.xml", ss)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        if styles_xml:
            z.writestr("xl/styles.xml", styles_xml)
    return buf.getvalue()


def test_read_xlsx_shared_strings_and_numbers():
    shared = ["Ngày", "Sản phẩm", "GMV", "Chi phí", "SP IMPORT A"]
    data = _make_xlsx(
        shared,
        [
            [(0, "s", None), (1, "s", None), (2, "s", None), (3, "s", None)],
            [(45931, "n", None), (4, "s", None), (530000, "n", None), (53000, "n", None)],
        ],
    )
    headers, rows = importer.read_table(data, "gmv.xlsx")
    assert headers == ["Ngày", "Sản phẩm", "GMV", "Chi phí"]
    # Ô ngày serial KHÔNG style -> vẫn là chuỗi số, parse_date lo phần còn lại.
    assert rows[0][0] == "45931"
    mapped = importer.map_gmv_rows(headers, rows, "vnd")
    assert mapped[0]["status"] == "ok"
    assert mapped[0]["data"]["date"] == "2025-10-01"
    assert mapped[0]["data"]["revenue_rm"] == 100.0


def test_read_xlsx_date_style_serial():
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    styles = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<styleSheet {ns}><numFmts count="1">'
        '<numFmt numFmtId="164" formatCode="dd/mm/yyyy"/></numFmts>'
        '<cellXfs count="2"><xf numFmtId="0"/>'
        '<xf numFmtId="164" applyNumberFormat="1"/></cellXfs></styleSheet>'
    )
    shared = ["Ngày", "Sản phẩm", "GMV", "Chi phí", "SP IMPORT A"]
    data = _make_xlsx(
        shared,
        [
            [(0, "s", None), (1, "s", None), (2, "s", None), (3, "s", None)],
            [(45931, "n", 1), (4, "s", None), (530000, "n", None), (53000, "n", None)],
        ],
        styles_xml=styles,
    )
    headers, rows = importer.read_table(data, "gmv.xlsx")
    assert rows[0][0] == "2025-10-01"  # style ngày -> đổi sang ISO ngay khi đọc


def test_read_xlsx_garbage():
    with pytest.raises(ValueError, match="không hợp lệ"):
        importer.read_table(b"day khong phai zip", "file.xlsx")


# ------------------------------- map GMV -----------------------------------


def test_map_gmv_vnd_converts_to_rm():
    headers, rows = importer.read_table(GMV_CSV, "gmv.csv")
    mapped = importer.map_gmv_rows(headers, rows, "vnd")
    assert [m["status"] for m in mapped] == ["ok", "ok"]
    # 1.590.000đ / 5300 = 300 RM; 159.000đ -> 30 RM
    assert mapped[0]["data"]["revenue_rm"] == 300.0
    assert mapped[0]["data"]["ad_cost"] == 30.0
    assert mapped[0]["data"]["views"] == 1000
    assert mapped[1]["data"]["revenue_rm"] == 600.0


def test_map_gmv_rm_keeps_values():
    headers = ["Date", "Product Name", "Revenue", "Ad Cost"]
    rows = [["2026-10-19", "SP IMPORT A", "100.5", "30"]]
    mapped = importer.map_gmv_rows(headers, rows, "rm")
    assert mapped[0]["data"]["revenue_rm"] == 100.5
    assert mapped[0]["data"]["ad_cost"] == 30.0


def test_map_gmv_missing_required_column_is_file_error():
    with pytest.raises(ValueError, match="thiếu cột bắt buộc"):
        importer.map_gmv_rows(["Ngày", "Sản phẩm"], [["2026-10-19", "X"]], "vnd")


def test_map_gmv_bad_row_does_not_block_good_row():
    headers = ["Ngày", "Sản phẩm", "GMV", "Chi phí"]
    rows = [
        ["2026-10-19", "SP IMPORT A", "530000", "53000"],
        ["ngày sai", "SP IMPORT A", "530000", "53000"],
        ["2026-10-21", "SP IMPORT A", "-5", "53000"],
        ["2026-10-22", "", "530000", "53000"],
    ]
    mapped = importer.map_gmv_rows(headers, rows, "vnd")
    assert [m["status"] for m in mapped] == ["ok", "error", "error", "error"]
    assert mapped[0]["data"]["revenue_rm"] == 100.0


def test_map_gmv_duplicate_in_file_last_wins():
    headers = ["Ngày", "Sản phẩm", "GMV", "Chi phí"]
    rows = [
        ["2026-10-19", "SP IMPORT A", "530000", "53000"],
        ["2026-10-19", "sp import a", "1060000", "53000"],
    ]
    mapped = importer.map_gmv_rows(headers, rows, "vnd")
    assert mapped[0]["status"] == "dup"
    assert mapped[1]["status"] == "ok"
    assert mapped[1]["data"]["revenue_rm"] == 200.0
    assert mapped[0]["warnings"] and mapped[1]["warnings"]


def test_map_gmv_unmatched_headers_listed():
    headers = ["Ngày", "Sản phẩm", "GMV", "Chi phí", "Cột Lạ Hoắc"]
    assert importer.unmatched_headers(headers, "gmv") == ["Cột Lạ Hoắc"]


# ------------------------------- map daily ---------------------------------

DAILY_HEADERS = [
    "Ngày",
    "Doanh thu sản phẩm",
    "Live",
    "Video",
    "Aff link",
    "Affiliate",
    "GMV quảng cáo",
    "Chi phí ads",
    "AOV",
    "Tỷ lệ chuyển đổi",
    "Ghi chú",
]


def test_map_daily_ok():
    rows = [
        ["2026-10-19", "5.000.000", "1200000", "800000", "0", "300000",
         "2000000", "500000", "150000", "2,5", "ngày đẹp"],
    ]
    mapped = importer.map_daily_rows(DAILY_HEADERS, rows)
    assert mapped[0]["status"] == "ok"
    d = mapped[0]["data"]
    assert d["rev_product"] == 5000000
    assert d["conv_rate"] == 2.5
    assert d["note"] == "ngày đẹp"
    assert set(d) == {
        "date", "rev_product", "rev_live", "rev_video", "rev_aff_link",
        "rev_affiliate", "ad_gmv", "ad_cost", "aov", "conv_rate", "note",
    }


def test_map_daily_missing_date_column_is_file_error():
    with pytest.raises(ValueError, match="thiếu cột bắt buộc"):
        importer.map_daily_rows(["Doanh thu sản phẩm"], [["5000"]])


def test_map_daily_duplicate_date_last_wins():
    rows = [
        ["2026-10-19", "1000", "", "", "", "", "", "", "", "", ""],
        ["2026-10-19", "2000", "", "", "", "", "", "", "", "", ""],
    ]
    mapped = importer.map_daily_rows(DAILY_HEADERS, rows)
    assert mapped[0]["status"] == "dup"
    assert mapped[1]["status"] == "ok"
    assert mapped[1]["data"]["rev_product"] == 2000


def test_map_daily_future_date_rejected():
    rows = [["2999-01-01", "1000", "", "", "", "", "", "", "", "", ""]]
    mapped = importer.map_daily_rows(DAILY_HEADERS, rows)
    assert mapped[0]["status"] == "error"


# ------------------------------- luồng web ---------------------------------


def _token(html: str) -> str:
    m = re.search(r'name="token" value="([^"]+)"', html)
    assert m, "không thấy token xem trước trong HTML"
    return m.group(1)


def _make_product(client, name="SP IMPORT A"):
    r = client.post("/api/gmv/products", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _upload_gmv(client, data=GMV_CSV, filename="gmv.csv", **form):
    payload = {"currency": "vnd", "create_products": "1"}
    payload.update(form)
    return client.post(
        "/gmv/import",
        files={"file": (filename, data, "application/octet-stream")},
        data=payload,
    )


def test_web_gmv_preview_does_not_write_then_confirm_writes(client):
    create_owner(client)
    prod = _make_product(client)
    r = _upload_gmv(client)
    assert r.status_code == 200
    assert "Xem trước" in r.text
    assert "SP IMPORT A" in r.text
    # Xem trước KHÔNG ghi DB
    entries = client.get(f"/api/gmv/products/{prod['id']}/entries").json()["entries"]
    assert entries == []
    token = _token(r.text)
    r2 = client.post("/gmv/import/confirm", data={"token": token})
    assert r2.status_code == 200
    entries = client.get(f"/api/gmv/products/{prod['id']}/entries").json()["entries"]
    assert len(entries) == 2
    by_date = {e["date"]: e for e in entries}
    assert by_date["2026-10-19"]["revenue_rm"] == 300.0
    assert by_date["2026-10-19"]["updated_by"] == "Chủ Shop"


def test_web_gmv_reimport_updates_not_duplicates(client):
    create_owner(client)
    prod = _make_product(client)
    for _ in range(2):
        r = _upload_gmv(client)
        client.post("/gmv/import/confirm", data={"token": _token(r.text)})
    entries = client.get(f"/api/gmv/products/{prod['id']}/entries").json()["entries"]
    assert len(entries) == 2  # upsert, không nhân đôi


def test_web_gmv_new_product_create_toggle(client):
    create_owner(client)
    csv_new = (
        "Ngày,Tên sản phẩm,GMV,Chi phí quảng cáo\n"
        "2026-10-19,SP HOÀN TOÀN MỚI,530000,53000\n"
    ).encode("utf-8-sig")
    # Bật tạo mới -> sản phẩm được tạo + ghi entry
    r = _upload_gmv(client, data=csv_new)
    assert "sẽ được tạo mới" in r.text
    client.post("/gmv/import/confirm", data={"token": _token(r.text)})
    names = [p["name"] for p in client.get("/api/gmv/products").json()["products"]]
    assert "SP HOÀN TOÀN MỚI" in names
    # Tắt tạo mới -> bỏ qua, không tạo
    csv_new2 = (
        "Ngày,Tên sản phẩm,GMV,Chi phí quảng cáo\n"
        "2026-10-19,SP MỚI NỮA,530000,53000\n"
    ).encode("utf-8-sig")
    r = client.post(
        "/gmv/import",
        files={"file": ("g.csv", csv_new2, "application/octet-stream")},
        data={"currency": "vnd"},
    )
    r2 = client.post("/gmv/import/confirm", data={"token": _token(r.text)})
    assert r2.status_code == 200
    names = [p["name"] for p in client.get("/api/gmv/products").json()["products"]]
    assert "SP MỚI NỮA" not in names


def test_web_gmv_bad_token_writes_nothing(client):
    create_owner(client)
    prod = _make_product(client)
    r = client.post("/gmv/import/confirm", data={"token": "token-khong-ton-tai"})
    assert r.status_code == 400
    entries = client.get(f"/api/gmv/products/{prod['id']}/entries").json()["entries"]
    assert entries == []


def test_web_gmv_garbage_file_vietnamese_error(client):
    create_owner(client)
    r = _upload_gmv(client, data=b"\x00\x01\x02 khong doc duoc", filename="file.txt")
    assert r.status_code == 422
    assert "chỉ nhận file" in r.text.lower() or "Chỉ nhận file" in r.text
    # File .csv nhưng nội dung rác không phải UTF-8
    r = _upload_gmv(client, data=b"\xff\xfe\x00bad", filename="file.csv")
    assert r.status_code == 422
    assert "Không đọc được" in r.text


def test_web_import_card_hidden_and_post_403_for_view_only_staff(client):
    create_owner(client)
    code = create_staff(client, "nv_xem", perms=("can_view_products",))
    logout(client)
    activate(client, "nv_xem", code)
    page = client.get("/gmv")
    assert page.status_code == 200
    assert "Nạp từ Excel" not in page.text
    r = client.post("/gmv/import", files={"file": ("g.csv", GMV_CSV, "text/csv")})
    assert r.status_code == 403
    assert client.post("/gmv/import/confirm", data={"token": "x"}).status_code == 403
    page = client.get("/bao-cao")
    assert "Nạp từ Excel" not in page.text
    r = client.post("/bao-cao/import", files={"file": ("d.csv", b"a", "text/csv")})
    assert r.status_code == 403
    assert client.get("/bao-cao/file-mau.csv").status_code == 403


DAILY_CSV = (
    "Ngày,Doanh thu sản phẩm,Live,Video,Aff link,Affiliate,GMV quảng cáo,"
    "Chi phí ads,AOV,Tỷ lệ chuyển đổi,Ghi chú\n"
    "2026-10-19,5000000,1200000,800000,0,300000,2000000,500000,150000,2.5,từ file\n"
    "2026-10-20,6000000,0,0,0,0,1000000,250000,140000,3.0,\n"
).encode("utf-8-sig")


def test_web_daily_flow_and_sample_template(client):
    create_owner(client)
    # File mẫu tải được, có header đúng bí danh
    r = client.get("/bao-cao/file-mau.csv")
    assert r.status_code == 200
    assert "Doanh thu sản phẩm" in r.text
    assert "DÒNG VÍ DỤ" in r.text

    r = client.post(
        "/bao-cao/import",
        files={"file": ("daily.csv", DAILY_CSV, "text/csv")},
    )
    assert r.status_code == 200
    assert client.get("/api/daily").json()["reports"] == []  # chưa ghi
    r2 = client.post("/bao-cao/import/confirm", data={"token": _token(r.text)})
    assert r2.status_code == 200
    reports = {x["date"]: x for x in client.get("/api/daily").json()["reports"]}
    assert set(reports) == {"2026-10-19", "2026-10-20"}
    assert reports["2026-10-19"]["rev_product"] == 5000000
    assert reports["2026-10-19"]["calc"]["total_rev"] == 7300000
    assert reports["2026-10-19"]["note"] == "từ file"
    # Nạp lại cùng file -> cập nhật, không nhân đôi
    r = client.post(
        "/bao-cao/import",
        files={"file": ("daily.csv", DAILY_CSV, "text/csv")},
    )
    client.post("/bao-cao/import/confirm", data={"token": _token(r.text)})
    assert len(client.get("/api/daily").json()["reports"]) == 2


def test_web_daily_cancel_writes_nothing(client):
    create_owner(client)
    r = client.post(
        "/bao-cao/import",
        files={"file": ("daily.csv", DAILY_CSV, "text/csv")},
    )
    token = _token(r.text)
    r2 = client.post("/bao-cao/import/cancel", data={"token": token})
    assert r2.status_code == 200
    assert client.get("/api/daily").json()["reports"] == []
    # Token đã hủy -> xác nhận lại cũng không ghi
    r3 = client.post("/bao-cao/import/confirm", data={"token": token})
    assert r3.status_code == 400
    assert client.get("/api/daily").json()["reports"] == []
