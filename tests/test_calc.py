"""Kiểm tra tính toán đối chiếu tay (dùng lại công thức đã duyệt)."""

from app.calc import analyze_product, calc_profit, margin_score, scale_1_5, score_product


def test_profit_hand_checked():
    # Giá 79.000đ: vốn 42.000, đóng gói 1.500, ship 6.000,
    # phí 8/2/5/5%, khác 1.000 — tính tay:
    # phí = 6.320 + 1.580 + 3.950 + 3.950 = 15.800
    # LN = 79.000 - 42.000 - 1.500 - 6.000 - 15.800 - 1.000 = 12.700
    # biên = 12.700 / 79.000 = 16,08%
    c = calc_profit(
        {
            "selling_price": 79000,
            "cost_price": 42000,
            "packaging_cost": 1500,
            "shipping_seller": 6000,
            "platform_fee_rate": 8,
            "payment_fee_rate": 2,
            "ads_rate": 5,
            "affiliate_rate": 5,
            "other_cost": 1000,
        }
    )
    assert c["platform_fee"] == 6320.0
    assert c["payment_fee"] == 1580.0
    assert c["ads_cost"] == 3950.0
    assert c["affiliate_cost"] == 3950.0
    assert c["profit"] == 12700
    assert c["margin"] == 16.08


def test_margin_tiers():
    assert margin_score(30) == 100
    assert margin_score(29.99) == 80
    assert margin_score(20) == 80
    assert margin_score(19.99) == 60
    assert margin_score(15) == 60
    assert margin_score(14.99) == 40
    assert margin_score(10) == 40
    assert margin_score(9.99) == 20
    assert margin_score(0) == 20
    assert margin_score(-0.01) == 0
    assert margin_score(None) is None


def test_scale_1_5():
    assert scale_1_5(1) == 0
    assert scale_1_5(3) == 50
    assert scale_1_5(5) == 100
    assert scale_1_5(None) is None


def test_score_full_data_label():
    # Biên 35% → 100 điểm biên; mọi tiêu chí 5 → tổng 100 → Ưu tiên kiểm tra
    p = {
        "selling_price": 100000,
        "cost_price": 60000,
        "packaging_cost": 0,
        "shipping_seller": 0,
        "platform_fee_rate": 5,
        "payment_fee_rate": 0,
        "ads_rate": 0,
        "affiliate_rate": 0,
        "other_cost": 0,
        "demand_score": 5,
        "competition_score": 5,
        "content_score": 5,
        "supply_score": 5,
    }
    calc = calc_profit(p)  # LN = 100000-60000-5000 = 35000 → biên 35%
    assert calc["profit"] == 35000
    assert calc["margin"] == 35.0
    s = score_product(p, calc)
    assert s["score"] == 100
    assert s["label"] == "Ưu tiên kiểm tra"
    assert s["components"] == {
        "margin": 100,
        "demand": 100,
        "competition": 100,
        "content": 100,
        "supply": 100,
    }


def test_score_missing_data_never_zero_filled():
    p = {
        "selling_price": 100000,
        "cost_price": 60000,
        "demand_score": None,
        "competition_score": 3,
        "content_score": 3,
        "supply_score": 3,
    }
    s = score_product(p, calc_profit(p))
    assert s["score"] is None
    assert s["label"] == "Cần bổ sung dữ liệu"
    assert "Điểm nhu cầu" in s["needs_data"]


def test_price_zero_no_division():
    c = calc_profit({"selling_price": 0, "cost_price": 1000})
    assert c["margin"] is None
    assert c["margin_missing"] is True
    s = score_product(
        {"demand_score": 5, "competition_score": 5, "content_score": 5, "supply_score": 5}, c
    )
    assert s["score"] is None


def test_negative_profit():
    c = calc_profit({"selling_price": 10000, "cost_price": 20000})
    assert c["profit"] == -10000
    assert c["margin"] == -100.0
    assert margin_score(c["margin"]) == 0


def test_analyze_product_shape():
    a = analyze_product({"name": "X", "selling_price": 50000, "cost_price": 30000})
    assert set(a) == {"product", "calc", "score", "assumptions"}
    assert a["calc"]["profit"] == 20000
