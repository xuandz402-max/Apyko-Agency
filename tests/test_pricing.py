"""Định giá sản phẩm: đối chiếu công thức với file Excel gốc của user,
tính ngược giá bán, trần voucher, phân quyền API, tham số mặc định,
đường wrapper libsql (Turso) và tìm kiếm ngành hàng.
"""

import os
import sys

import pytest
from conftest import activate, create_owner, create_staff, login, logout

XLSX_PATH = (
    "/home/hatch/workspace/goals/thi-t-k-muse-ai-mvp-30-ng-y-cho-shop-s-ch-nh"
    "/hidden_files/pricing/du-tinh-gia-ban.xlsx"
)

# Mã ngành nguyên văn trong file gốc (giữ nguyên ký tự phân cấp).
LAPTOP_CODE = "[Thường] Máy tính & Laptop › Laptop"  # noqa: RUF001
SHAMPOO_CODE = "[MALL] Sắc Đẹp › Chăm sóc › tóc Dầu gội"  # noqa: RUF001
BAD_CODE = "[Không] Có › Ngành › Này"  # noqa: RUF001

# Cột sheet "Tính hàng loạt" (1-based theo openpyxl)
COL = {
    "name": 2,
    "category": 3,
    "cat_rate": 4,
    "cost": 5,
    "price": 6,
    "pay_rate": 7,
    "voucher_rate": 8,
    "voucher_cap": 9,
    "affiliate_rate": 10,
    "fixed": 11,
    "ads_rate": 12,
    "tax_rate": 13,
    "cat_fee": 14,
    "pay_fee": 15,
    "voucher_fee": 16,
    "affiliate_fee": 17,
    "ads_cost": 18,
    "tax_fee": 19,
    "total": 20,
    "profit": 21,
    "margin": 22,
}


def _sample_rows():
    """Đọc 3 dòng mẫu (2-4) từ file gốc: (input dict dạng DB, expected dict)."""
    openpyxl = pytest.importorskip(
        "openpyxl", reason="Thiếu openpyxl trong môi trường test để đọc file gốc."
    )

    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    ws = wb["Tính hàng loạt"]
    out = []
    for r in (2, 3, 4):
        v = {k: ws.cell(row=r, column=c).value for k, c in COL.items()}
        assert v["fixed"] == 5700  # = Pi Ship 2.700 + Hạ tầng 3.000 (mặc định)
        inp = {
            "cost_price": int(v["cost"]),
            "selling_price": int(v["price"]),
            "category_fee_rate": float(v["cat_rate"]),
            "pay_rate": float(v["pay_rate"]),
            "voucher_rate": float(v["voucher_rate"]),
            "voucher_cap": int(v["voucher_cap"]),
            "affiliate_rate": float(v["affiliate_rate"]),
            "ads_rate": float(v["ads_rate"]),
            "tax_rate": float(v["tax_rate"]),
            "pi_ship": 2700,
            "infra_fee": 3000,
        }
        expected = {
            "cat_fee": v["cat_fee"],
            "pay_fee": v["pay_fee"],
            "voucher_fee": v["voucher_fee"],
            "affiliate_fee": v["affiliate_fee"],
            "ads_cost": v["ads_cost"],
            "tax_fee": v["tax_fee"],
            "total_cost": v["total"],
            "profit": v["profit"],
            "margin_dec": v["margin"],
        }
        out.append((v["name"], inp, expected))
    return out


needs_xlsx = pytest.mark.skipif(
    not os.path.exists(XLSX_PATH),
    reason="Thiếu file Excel gốc 'Dự tính giá bán' để đối chiếu công thức.",
)


@needs_xlsx
@pytest.mark.parametrize("idx", [0, 1, 2])
def test_calc_matches_excel_sample_rows(idx):
    from app.pricing import calc_pricing

    _name, inp, expected = _sample_rows()[idx]
    calc = calc_pricing(inp)
    for key in (
        "cat_fee",
        "pay_fee",
        "voucher_fee",
        "affiliate_fee",
        "ads_cost",
        "tax_fee",
        "total_cost",
        "profit",
    ):
        assert abs(calc[key] - expected[key]) <= 1, (key, calc[key], expected[key])
    assert abs(calc["margin_pct"] - expected["margin_dec"] * 100) <= 0.011
    assert calc["fixed_fee"] == 5700


def _reverse_base():
    return {
        "cost_price": 100000,
        "category_fee_rate": 0.10,
        "pay_rate": 0.06,
        "voucher_rate": 0.055,
        "voucher_cap": 50000,
        "affiliate_rate": 0.05,
        "ads_rate": 0.10,
        "tax_rate": 0.015,
        "pi_ship": 2700,
        "infra_fee": 3000,
    }


def test_price_for_margin_roundtrip():
    from app.pricing import calc_pricing, price_for_margin

    d = _reverse_base()
    price = price_for_margin(d, 20)
    assert price is not None and price > 0
    margin = calc_pricing({**d, "selling_price": price})["margin_pct"]
    assert margin >= 20
    assert margin - 20 <= 0.2  # giá nguyên đồng tối thiểu -> sát target
    # giá thấp hơn 1 đồng thì chưa đạt (đúng nghĩa "nhỏ nhất")
    prev = calc_pricing({**d, "selling_price": price - 1})["margin_pct"]
    assert prev < 20


def test_price_for_margin_hits_voucher_cap_region():
    from app.pricing import calc_pricing, price_for_margin

    # Giá vốn lớn -> giá bán cần đặt vượt 909.090đ, nơi MIN(5.5% x P, 50.000) chạm trần.
    d = {**_reverse_base(), "cost_price": 1_000_000}
    price = price_for_margin(d, 30)
    assert price is not None and price > 909090
    calc = calc_pricing({**d, "selling_price": price})
    assert calc["voucher_fee"] == 50000  # đã chạm trần
    assert calc["margin_pct"] >= 30
    assert calc["margin_pct"] - 30 <= 0.2


def test_price_for_margin_impossible_cases():
    from app.pricing import price_for_margin

    d = _reverse_base()
    assert price_for_margin(d, 100) is None
    assert price_for_margin(d, 150) is None
    # tổng % phí > 100% giá bán thì biên dương không bao giờ đạt
    greedy = {**d, "pay_rate": 0.6, "ads_rate": 0.6}
    assert price_for_margin(greedy, 10) is None


def test_price_for_margin_negative_target():
    from app.pricing import calc_pricing, price_for_margin

    d = _reverse_base()
    price = price_for_margin(d, -10)
    assert price is not None and price > 0
    assert calc_pricing({**d, "selling_price": price})["margin_pct"] >= -10


def test_voucher_fee_capped():
    from app.pricing import calc_pricing

    d = {**_reverse_base(), "selling_price": 10_000_000}
    assert calc_pricing(d)["voucher_fee"] == 50000


def test_zero_selling_price_margin_none():
    from app.pricing import calc_pricing

    calc = calc_pricing({**_reverse_base(), "selling_price": 0})
    assert calc["margin_pct"] is None
    assert calc["total_cost"] == 100000 + 5700
    assert calc["profit"] == -(100000 + 5700)


def test_validate_converts_pct_to_decimal():
    from app.pricing import validate_pricing_payload

    clean, errors = validate_pricing_payload(
        {"name": "SP test", "cost_price": 100000, "selling_price": 200000,
         "pay_rate_pct": 6, "tax_rate_pct": 1.5}
    )
    assert errors == {}
    assert clean["pay_rate"] == 0.06
    assert clean["tax_rate"] == 0.015
    assert clean["category_fee_rate"] == 0.0


def test_validate_rejects_bad_input():
    from app.pricing import validate_pricing_payload

    _clean, errors = validate_pricing_payload({"name": "  "})
    assert "name" in errors
    _clean, errors = validate_pricing_payload(
        {"name": "X", "pay_rate_pct": 101, "cost_price": -5}
    )
    assert "pay_rate_pct" in errors
    assert "cost_price" in errors
    _clean, errors = validate_pricing_payload({"name": "X", "category_code": BAD_CODE})
    assert "category_code" in errors


def test_search_categories_laptop():
    from app.pricing import find_category, search_categories

    results = search_categories("Laptop")
    assert results, "phải có kết quả cho 'Laptop'"
    codes = [c["code"] for c in results]
    assert LAPTOP_CODE in codes
    hit = find_category(LAPTOP_CODE)
    assert hit is not None
    assert hit["fee_rate"] == pytest.approx(0.02)
    for c in results:
        haystack = f"{c['code']} {c['big']} {c['small']}".lower()
        assert "laptop" in haystack


def test_categories_count():
    from app.pricing import list_categories

    assert len(list_categories()) == 2904


# ------------------------------ API / quyền --------------------------------

ITEM_PAYLOAD = {
    "name": "Dầu gội test",
    "category_code": SHAMPOO_CODE,
    "cost_price": "100000",
    "selling_price": "260000",
    "ads_rate_pct": 5,
}


@pytest.fixture()
def staff_no_edit(client):
    """Nhân sự chỉ xem (không thêm/sửa/xóa sản phẩm), đã kích hoạt + đăng nhập."""
    create_owner(client)
    code = create_staff(
        client, "nv_xem", perms=("can_view_products", "can_view_uni", "can_view_pricing")
    )
    logout(client)
    activate(client, "nv_xem", code)
    return client


def test_staff_without_edit_perm_cannot_create_or_delete(staff_no_edit):
    r = staff_no_edit.post("/api/pricing/items", json=ITEM_PAYLOAD)
    assert r.status_code == 403
    r = staff_no_edit.delete("/api/pricing/items/1")
    assert r.status_code == 403
    # nhưng xem được trang + danh sách + tính ngược
    assert staff_no_edit.get("/dinh-gia").status_code == 200
    assert staff_no_edit.get("/api/pricing/items").status_code == 200
    r = staff_no_edit.post(
        "/api/pricing/reverse",
        json={"cost_price": 100000, "target_margin_pct": 20},
    )
    assert r.status_code == 200


def test_staff_edit_perm_but_no_delete(staff_no_edit):
    # Cấp thêm quyền sửa (không cấp quyền xóa) rồi thử lại
    logout(staff_no_edit)
    login(staff_no_edit, "chushop", "matkhau123")
    from app import database as db

    target = db.get_user_by_username("nv_xem")
    staff_no_edit.post(
        f"/accounts/{target['id']}/perms",
        data={"can_view_products": "on", "can_add_edit_products": "on"},
    )
    logout(staff_no_edit)
    login(staff_no_edit, "nv_xem", "matkhau123")
    r = staff_no_edit.post("/api/pricing/items", json=ITEM_PAYLOAD)
    assert r.status_code == 201
    item_id = r.json()["id"]
    r = staff_no_edit.delete(f"/api/pricing/items/{item_id}")
    assert r.status_code == 403


def test_owner_crud_and_calc(client):
    create_owner(client)
    r = client.post("/api/pricing/items", json=ITEM_PAYLOAD)
    assert r.status_code == 201
    item = r.json()
    # ngành MALL dầu gội: phí ngành 20.8% x 260.000 = 54.080
    assert item["category_fee_rate"] == pytest.approx(0.208)
    assert item["calc"]["cat_fee"] == 54080
    assert item["calc"]["pay_fee"] == 15600  # 6% mặc định
    assert item["calc"]["tax_fee"] == 3900  # 1.5% mặc định
    assert item["calc"]["fixed_fee"] == 5700
    item_id = item["id"]

    r = client.put(
        f"/api/pricing/items/{item_id}",
        json={**ITEM_PAYLOAD, "selling_price": "300000"},
    )
    assert r.status_code == 200
    assert r.json()["calc"]["cat_fee"] == 62400

    r = client.get("/api/pricing/items")
    assert r.json()["total"] == 1
    r = client.get("/api/pricing/export")
    assert r.status_code == 200
    assert "Dầu gội test" in r.text

    r = client.delete(f"/api/pricing/items/{item_id}")
    assert r.status_code == 204
    assert client.get("/api/pricing/items").json()["total"] == 0


def test_settings_put_forbidden_for_staff(staff_no_edit):
    r = staff_no_edit.put("/api/pricing/settings", json={"pay_rate_pct": 5})
    assert r.status_code == 403


def test_settings_owner_update_applies_to_new_items(client):
    create_owner(client)
    r = client.put("/api/pricing/settings", json={"pay_rate_pct": 5})
    assert r.status_code == 200
    assert r.json()["settings"]["pay_rate_pct"] == 5

    r = client.post(
        "/api/pricing/items",
        json={"name": "SP mặc định mới", "cost_price": 50000, "selling_price": 100000},
    )
    assert r.status_code == 201
    item = r.json()
    assert item["pay_rate"] == pytest.approx(0.05)  # dùng mặc định mới
    assert item["calc"]["pay_fee"] == 5000


def test_categories_api(client):
    create_owner(client)
    r = client.get("/api/pricing/categories", params={"q": "Laptop"})
    assert r.status_code == 200
    cats = r.json()["categories"]
    assert any(c["code"] == LAPTOP_CODE for c in cats)
    hit = next(c for c in cats if c["code"] == LAPTOP_CODE)
    assert hit["fee_rate"] == pytest.approx(0.02)


def test_pricing_page_sidebar_visible_without_product_perm(client):
    """Nhân sự không có quyền sản phẩm vẫn thấy + mở được Định giá
    (Định giá có quyền xem riêng can_view_pricing, không mượn quyền SP)."""
    create_owner(client)
    code = create_staff(client, "nv_uni", perms=("can_view_uni", "can_view_pricing"))
    logout(client)
    activate(client, "nv_uni", code)
    r = client.get("/dinh-gia")
    assert r.status_code == 200
    assert "Định giá sản phẩm" in r.text


# ------------------------------ wrapper libsql -----------------------------


@pytest.fixture()
def turso_pricing(tmp_path, monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", f"file:{tmp_path / 'turso.db'}")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "x")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "fallback.db"))
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key-khong-dung-that")
    monkeypatch.setenv("DISABLE_BACKGROUND", "1")
    for name in [n for n in sys.modules if n == "app" or n.startswith("app.")]:
        sys.modules.pop(name)
    import app.database as db

    assert db._turso_enabled()
    db.init_db()
    return db


def test_pricing_settings_via_turso_wrapper(turso_pricing):
    db = turso_pricing
    all_settings = db.pricing_setting_get_all()
    assert all_settings["pay_rate"] == "0.06"
    assert all_settings["tax_rate"] == "0.015"
    assert all_settings["pi_ship"] == "2700"
    assert all_settings["infra_fee"] == "3000"
    assert all_settings["voucher_cap"] == "50000"
    db.pricing_setting_set("pay_rate", "0.05")
    assert db.pricing_setting_get_all()["pay_rate"] == "0.05"


def test_pricing_item_crud_via_turso_wrapper(turso_pricing):
    db = turso_pricing
    item_id = db.pricing_item_create(
        {
            "name": "SP wrapper",
            "category_code": "",
            "category_fee_rate": 0.0,
            "cost_price": 10000,
            "selling_price": 20000,
            "pay_rate": 0.06,
            "voucher_rate": 0.0,
            "voucher_cap": 50000,
            "affiliate_rate": 0.0,
            "pi_ship": 2700,
            "infra_fee": 3000,
            "ads_rate": 0.0,
            "tax_rate": 0.015,
        },
        created_by="tester",
    )
    got = db.pricing_item_get(item_id)
    assert got["name"] == "SP wrapper"
    assert got["created_by"] == "tester"
    assert db.pricing_item_delete(item_id) is True
    assert db.pricing_item_get(item_id) is None
