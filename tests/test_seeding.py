"""Sidebar mới 'Seeding': trang SOP chỉ đọc, nguyên văn nội dung
file user gửi, kèm đủ 7 ảnh minh họa; grant sidebar "seeding" (registry)."""

# ruff: noqa: RUF001, E501 — các chuỗi nguyên văn từ file user gửi chứa
# dấu gạch ngang dài và vượt độ dài dòng; đó là nội dung, không được sửa.

from conftest import activate, create_owner, create_staff, logout

STEP_TEXTS = (
    "Tạo 1 sản phẩm giá 18-20k ( Phụ kiện hoặc gì đó ) – mục đích để giảm phí sàn khi đặt đơn ảo",
    # Trong HTML nguồn, ký tự < được viết dạng &lt; (nội dung render ra giống hệt)
    "SET MUA KÈM DEAL SOCK – SẢN PHẨM CHÍNH LÀ SẢN PHẨM ĐÃ TẠO Ở BƯỚC 1 – SỐ LƯỢNG SẢN PHẨM MUA KÈM LÀ SẢN PHẨM CẦN BUFF - SET GIÁ 1000đ – LÊN BUFF &lt; 5 SẢN PHẨM 1 LẦN",
    "NHỜ NGƯỜI ĐẶT ĐƠN – THÊM VÀO GIỎ HÀNG SẢN PHẨM CHÍNH Ở BƯỚC 1 - LINK SẢN PHẨM 1K THÊM VÀO VÀ BẬT HẾT TỒN – SAU ĐÓ ĐẶT ĐƠN",
)

NOTES = (
    "KHÔNG BUFF &gt; 5 SẢN PHẨM 1 LÚC",
    "BẬT HỎA TỐC – ĐƠN ĐI NHANH HƠN",
    "KHÔNG SỬ DỤNG MẠNG WIFI ĐỂ ĐẶT ĐƠN",
    "RANK VÀNG TRỞ LÊN CÀNG TỐT",
    "NẾU KHÔNG MUỐN KHÁCH ĐÓNG ĐƠN GỬI ĐI - THAY ĐỔI ĐỊA CHỈ VỀ KHO CỦA BẠN TRƯỚC KHI CHUẨN BỊ ĐƠN",
    "CHỦ SHOP SET SỐ LƯỢNG TỒN MONG MUỐN ĐẶT – ĐỂ NGƯỜI ĐẶT BẬT HẾT TỒN – SẢN PHẨM SẼ VỀ HẾT HÀNG ĐỂ DỄ KIỂM SOÁT",
)

IMAGES = (
    "/static/seeding/buoc2-1.png",
    "/static/seeding/buoc2-2.png",
    "/static/seeding/buoc2-3.png",
    "/static/seeding/buoc2-4.png",
    "/static/seeding/buoc2-5.png",
    "/static/seeding/buoc3-1.jpeg",
    "/static/seeding/luu-y-1.jpeg",
)


def _staff(client, username, perms):
    code = create_staff(client, username, perms=perms)
    logout(client)
    activate(client, username, code)


def test_owner_sees_full_verbatim_content_and_all_images(client):
    create_owner(client)
    r = client.get("/seeding")
    assert r.status_code == 200
    assert "🌱 Seeding" in r.text
    for text in STEP_TEXTS + NOTES:
        assert text in r.text, text
    for img in IMAGES:
        assert img in r.text, img
    # Đúng thứ tự: Bước 1 -> Bước 2 (+ 5 ảnh) -> Bước 3 (+ 1 ảnh) -> LƯU Ý (+ 1 ảnh)
    order = [
        "Bước 1",
        "Bước 2",
        "/static/seeding/buoc2-1.png",
        "/static/seeding/buoc2-2.png",
        "/static/seeding/buoc2-3.png",
        "/static/seeding/buoc2-4.png",
        "/static/seeding/buoc2-5.png",
        "Bước 3",
        "/static/seeding/buoc3-1.jpeg",
        "LƯU Ý",
        "/static/seeding/luu-y-1.jpeg",
    ]
    positions = [r.text.index(item) for item in order]
    assert positions == sorted(positions)
    # Caption trung lập của 5 ảnh bước 2
    for i in range(1, 6):
        assert f"Ảnh minh họa bước 2 ({i}/5)" in r.text


def test_staff_without_flag_is_blocked_and_sees_no_link(client):
    create_owner(client)
    _staff(client, "nv_khong_seed", perms=("sidebar_products",))
    assert client.get("/seeding").status_code == 403
    page = client.get("/products")
    assert 'href="/seeding"' not in page.text


def test_staff_with_flag_sees_page_and_link(client):
    create_owner(client)
    _staff(client, "nv_seed", perms=("sidebar_seeding",))
    r = client.get("/seeding")
    assert r.status_code == 200
    assert 'href="/seeding"' in r.text
    assert "🌱 Seeding" in r.text


def test_sidebar_order_seeding_right_after_analysis(client):
    create_owner(client)
    page = client.get("/seeding").text
    i_analysis = page.index('href="/analysis"')
    i_seeding = page.index('href="/seeding"')
    i_pricing = page.index('href="/dinh-gia"')
    assert i_analysis < i_seeding < i_pricing


def test_home_falls_back_to_seeding_for_seeding_only_staff(client):
    create_owner(client)
    _staff(client, "nv_chi_seed", perms=("sidebar_seeding",))
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/seeding"


def test_seeding_images_capped_width():
    """Ảnh minh họa Seeding không tràn full thẻ (tối đa 640px, căn giữa)."""
    css = open("static/style.css", encoding="utf-8").read()
    rule = next(line for line in css.splitlines() if line.strip().startswith(".seed-img"))
    assert "max-width: 640px" in rule and "margin: 12px auto" in rule


def test_seeding_tall_images_capped_by_height():
    """2 ảnh dọc (bước 3, lưu ý) giới hạn theo chiều cao, không cao tràn trang."""
    css = open("static/style.css", encoding="utf-8").read()
    rule = next(line for line in css.splitlines() if line.strip().startswith(".seed-img-tall"))
    assert "max-height: 520px" in rule
    html = open("templates/seeding.html", encoding="utf-8").read()
    assert 'buoc3-1.jpeg" alt="Ảnh minh họa bước 3" class="seed-img seed-img-tall"' in html
    assert 'luu-y-1.jpeg" alt="Ảnh minh họa lưu ý" class="seed-img seed-img-tall"' in html


def test_seeding_sheets_shopee_active_and_tiktok_placeholder(client):
    """Sheet Shopee giữ đủ nội dung cũ; sheet TikTok là trạng thái trống
    trung thực, không số giả."""
    create_owner(client)
    r = client.get("/seeding")
    assert r.status_code == 200
    assert 'href="/seeding?sheet=shopee" class="tab active"' in r.text
    assert "Bước 1" in r.text
    rt = client.get("/seeding?sheet=tiktok")
    assert rt.status_code == 200
    assert 'href="/seeding?sheet=tiktok" class="tab active"' in rt.text
    assert "Sắp có" in rt.text
    assert "Bước 1" not in rt.text


def test_seeding_uses_base_font_no_override():
    """Trang Seeding dùng đúng font chuẩn của web: template không khai báo
    font riêng, toàn app chỉ có 1 font-family duy nhất ở body."""
    html = open("templates/seeding.html", encoding="utf-8").read()
    assert "font-family" not in html and "<style" not in html
    css = open("static/style.css", encoding="utf-8").read()
    assert css.count("font-family") == 1
