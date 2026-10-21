"""Module Affiliate: bảng tracker (CRUD + phân quyền + CVR/EPC + CSV)
và tab nội dung bài "Shopee tiếp thị liên kết" nguyên văn 54 slide."""

import json
import os

from conftest import activate, create_owner, create_staff, logout

_DECK_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app",
    "data",
    "affiliate_deck.json",
)


def _db():
    from app import database as db

    return db


def _aff():
    from app import affiliate

    return affiliate


def _payload(**overrides):
    base = {
        "product_name": "Rơ le nhiệt RL-NC-01",
        "platform": "Shopee",
        "affiliate_link": "https://shopee.vn/aff/rl-nc-01",
        "sub_id": "video-rl01-01",
        "commission_rate": "10",
        "clicks": "200",
        "orders": "10",
        "commission_estimated": "600000",
        "commission_received": "500000",
        "data_source": "Báo cáo Shopee Affiliate",
        "note": "Video review 1",
    }
    base.update(overrides)
    return base


# ------------------------------ tính chỉ số ------------------------------


def test_calc_affiliate_cvr_epc():
    aff = _aff()
    calc = aff.calc_affiliate({"clicks": 200, "orders": 10, "commission_received": 500000})
    assert calc["cvr"] == 5.0
    assert calc["epc"] == 2500.0


def test_calc_affiliate_zero_clicks_is_none():
    aff = _aff()
    calc = aff.calc_affiliate({"clicks": 0, "orders": 3, "commission_received": 1000})
    assert calc["cvr"] is None
    assert calc["epc"] is None


def test_validate_payload_parses_vn_numbers():
    aff = _aff()
    clean, errors = aff.validate_affiliate_payload(
        _payload(clicks="1.500", commission_received="2.000.000", commission_rate="7,5")
    )
    assert errors == {}
    assert clean["clicks"] == 1500
    assert clean["commission_received"] == 2000000
    assert clean["commission_rate"] == 7.5


def test_validate_payload_requires_product_name():
    aff = _aff()
    _clean, errors = aff.validate_affiliate_payload(_payload(product_name="  "))
    assert "product_name" in errors


# ------------------------------ CRUD qua HTTP ------------------------------


def test_affiliate_crud_as_owner(client):
    create_owner(client)
    db = _db()
    r = client.post("/affiliate", data=_payload(), follow_redirects=False)
    assert r.status_code == 303
    rows = db.affiliate_list()
    assert len(rows) == 1
    item = rows[0]
    assert item["product_name"] == "Rơ le nhiệt RL-NC-01"
    assert item["sub_id"] == "video-rl01-01"
    assert item["clicks"] == 200
    assert item["commission_received"] == 500000

    r = client.get("/affiliate")
    assert r.status_code == 200
    assert "Rơ le nhiệt RL-NC-01" in r.text
    assert "video-rl01-01" in r.text
    # Thẻ tổng + chỉ số dẫn xuất: CVR 10/200 = 5.00%, EPC 500000/200 = 2.500đ
    assert "500.000đ" in r.text
    assert "5.00%" in r.text
    assert "2.500đ" in r.text

    r = client.post(
        f"/affiliate/{item['id']}/edit",
        data=_payload(orders="20", commission_received="900000"),
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert db.affiliate_get(item["id"])["orders"] == 20

    r = client.post(f"/affiliate/{item['id']}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert db.affiliate_get(item["id"]) is None


def test_affiliate_zero_clicks_shows_dash(client):
    create_owner(client)
    client.post("/affiliate", data=_payload(clicks="0", orders="0"), follow_redirects=False)
    r = client.get("/affiliate")
    assert r.status_code == 200
    assert "—" in r.text  # CVR + EPC không chia 0, hiện "—"


def test_affiliate_validation_error_redirects(client):
    create_owner(client)
    db = _db()
    r = client.post(
        "/affiliate", data=_payload(product_name=""), follow_redirects=False
    )
    assert r.status_code == 303
    assert "err=" in r.headers["location"]
    assert db.affiliate_list() == []


def test_affiliate_search_and_platform_filter(client):
    create_owner(client)
    db = _db()
    db.affiliate_upsert(_payload(), "owner")
    db.affiliate_upsert(
        _payload(product_name="Bếp từ X2", platform="TikTok", sub_id="live-x2-01"),
        "owner",
    )
    r = client.get("/affiliate", params={"q": "video-rl01"})
    assert "<strong>Rơ le nhiệt RL-NC-01</strong>" in r.text
    assert "Bếp từ X2" not in r.text
    r = client.get("/affiliate", params={"platform": "TikTok"})
    assert "<strong>Bếp từ X2</strong>" in r.text
    assert "<strong>Rơ le nhiệt RL-NC-01</strong>" not in r.text


# ------------------------------ phân quyền ------------------------------


def test_affiliate_forbidden_without_view_perm_and_menu_hidden(client):
    create_owner(client)
    code = create_staff(client, "nv_no_view", perms=())
    logout(client)
    activate(client, "nv_no_view", code)
    assert client.get("/affiliate").status_code == 403
    assert client.get("/affiliate/export").status_code == 403
    # Menu Affiliate bị ẩn ở trang nhân viên này vẫn vào được
    r = client.get("/cskh")
    assert r.status_code == 200
    assert 'href="/affiliate"' not in r.text


def test_affiliate_menu_visible_for_owner(client):
    create_owner(client)
    r = client.get("/affiliate")
    assert r.status_code == 200
    assert 'href="/affiliate"' in r.text


def test_affiliate_write_permissions(client):
    create_owner(client)
    db = _db()
    item_id = db.affiliate_upsert(_payload(), "owner")
    code_view = create_staff(client, "nv_xem", perms=("can_view_products",))
    code_edit = create_staff(
        client, "nv_sua", perms=("can_view_products", "can_add_edit_products")
    )
    # Chỉ xem: xem được, thêm/sửa/xóa đều 403
    logout(client)
    activate(client, "nv_xem", code_view)
    assert client.get("/affiliate").status_code == 200
    assert client.post("/affiliate", data=_payload(), follow_redirects=False).status_code == 403
    r = client.post(
        f"/affiliate/{item_id}/edit", data=_payload(), follow_redirects=False
    )
    assert r.status_code == 403
    assert client.post(f"/affiliate/{item_id}/delete", follow_redirects=False).status_code == 403
    # Có quyền sửa: thêm/sửa được, xóa vẫn 403
    logout(client)
    activate(client, "nv_sua", code_edit)
    assert client.post("/affiliate", data=_payload(), follow_redirects=False).status_code == 303
    r = client.post(
        f"/affiliate/{item_id}/edit", data=_payload(), follow_redirects=False
    )
    assert r.status_code == 303
    assert client.post(f"/affiliate/{item_id}/delete", follow_redirects=False).status_code == 403


# ------------------------------ CSV export ------------------------------


def test_affiliate_csv_export(client):
    create_owner(client)
    db = _db()
    db.affiliate_upsert(_payload(), "owner")
    r = client.get("/affiliate/export")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    text = r.content.decode("utf-8-sig")
    assert "Hoa hồng thực nhận (VNĐ)" in text
    assert "Rơ le nhiệt RL-NC-01" in text
    assert "video-rl01-01" in text
    assert "500000" in text


# ------------------------------ tab nội dung bài ------------------------------


def _load_deck():
    with open(_DECK_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_affiliate_content_tab_renders_all_54_slides(client):
    create_owner(client)
    deck = _load_deck()
    assert len(deck["slides"]) == 54
    r = client.get("/affiliate", params={"tab": "noi-dung"})
    assert r.status_code == 200
    html = r.text
    assert deck["title"] in html
    # Đủ 54 khối slide, đúng thứ tự
    assert html.count("aff-slide") == 54
    positions = [html.index(f"Slide {n}") for n in range(1, 55)]
    assert positions == sorted(positions)


def test_affiliate_content_tab_verbatim_paragraphs(client):
    create_owner(client)
    deck = _load_deck()
    r = client.get("/affiliate", params={"tab": "noi-dung"})
    html = r.text
    # Slide 21: hạn mức hoa hồng 70,000 VNĐ — nguyên văn từng chữ từ JSON
    slide21 = deck["slides"][20]
    para21 = next(p for p in slide21["paragraphs"] if "70,000" in p)
    assert para21 in html
    # Slide 36: khái niệm Sub id — nguyên văn từng chữ từ JSON
    slide36 = deck["slides"][35]
    assert slide36["paragraphs"][0] in html
    assert "Sub id" in slide36["paragraphs"][0]
    # Mọi đoạn của mọi slide có chữ đều xuất hiện nguyên văn
    # (chỉ khác ở escape HTML chuẩn của Jinja: & < > " ')
    def esc(text):
        return (
            text.replace("&", "&amp;")
            .replace(">", "&gt;")
            .replace("<", "&lt;")
            .replace('"', "&#34;")
            .replace("'", "&#39;")
        )

    for s in deck["slides"]:
        if s["has_text"]:
            for p in s["paragraphs"]:
                assert esc(p) in html


_STATIC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static"
)

_SOURCE_URL = (
    "https://docs.google.com/presentation/d/"
    "176Smsph6GDbdB9e6T8hjVgBQ3BDk8AWJU9cC8SJyIy8/edit?usp=sharing"
)


def test_affiliate_deck_images_point_to_real_files():
    deck = _load_deck()
    # Link bài gốc ở cấp deck
    assert deck["source_url"] == _SOURCE_URL
    total = 0
    for s in deck["slides"]:
        for img in s.get("images", []):
            total += 1
            assert img.startswith("/static/lesson-images/aff/")
            path = os.path.join(_STATIC_DIR, img.removeprefix("/static/"))
            assert os.path.isfile(path), f"Thiếu file ảnh: {img}"
            assert os.path.getsize(path) > 0
    assert total == 54  # 54 ảnh gốc trong deck, ở 44 slide


def test_affiliate_deck_all_image_only_slides_have_images():
    deck = _load_deck()
    no_text = [s for s in deck["slides"] if not s["has_text"]]
    assert len(no_text) == 28
    # Cả 28 slide trước đây chỉ có ghi chú nay đều có ảnh thật
    for s in no_text:
        assert s.get("images"), f"Slide {s['slide']} chưa có ảnh"


def test_affiliate_content_tab_shows_source_link_and_images(client):
    create_owner(client)
    deck = _load_deck()
    total_images = sum(len(s.get("images", [])) for s in deck["slides"])
    r = client.get("/affiliate", params={"tab": "noi-dung"})
    assert r.status_code == 200
    html = r.text
    # Link bài gốc Google Drive ở đầu mục nội dung
    assert "Bài gốc trên Google Drive" in html
    assert f'href="{_SOURCE_URL}"' in html
    # Số thẻ ảnh khớp tổng số ảnh trong JSON
    assert html.count('class="aff-img"') == total_images
    # Ghi chú cũ đã bỏ hẳn; không slide nào thiếu ảnh tới mức phải ghi chú
    assert "ảnh chụp minh họa trong bản gốc (không có chữ)" not in html
    assert "chưa lấy được hình ảnh" not in html
    # Vẫn đủ 54 khối slide
    assert html.count("aff-slide") == 54


def test_affiliate_slide_images_served(client):
    create_owner(client)
    deck = _load_deck()
    samples = []
    for s in deck["slides"]:
        if s.get("images"):
            samples.append(s["images"][0])
    # Kiểm mẫu: ảnh đầu tiên của vài slide rải khắp deck + slide cuối có ảnh
    for img in (samples[0], samples[len(samples) // 2], samples[-1]):
        r = client.get(img)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/")


def test_affiliate_default_tab_is_tracker(client):
    create_owner(client)
    r = client.get("/affiliate")
    assert r.status_code == 200
    assert "Bảng theo dõi" in r.text
    assert "Danh sách link affiliate" in r.text
    assert "aff-slide" not in r.text
