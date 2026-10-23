"""Apyko Uni: 58 bài nguyên văn, render Markdown, tiến độ theo tài khoản."""

from app import lessons
from conftest import create_owner


def test_58_lessons_loaded_in_order():
    all_lessons = lessons.list_lessons()
    assert len(all_lessons) == 58
    assert all_lessons[0]["title"] == "Vì sao phải định vị Brand ?"
    assert all_lessons[21]["title"] == "6 Giá trị cốt lõi Apyko Uni Group"
    assert all_lessons[57]["title"] == "Check Tồn kho"
    ids = [les["id"] for les in all_lessons]
    assert len(set(ids)) == 58  # id duy nhất
    assert ids == sorted(ids)  # đúng thứ tự file 00-57


def test_no_tabcom_anywhere():
    for les in lessons.list_lessons():
        blob = (les["title"] + "\n" + les["body_md"]).lower()
        assert "tabcom" not in blob, f"còn chữ tabcom trong bài {les['id']}"


def test_render_markdown_table_heading_bold_list():
    html = lessons.render_markdown(
        "## Tiêu đề\n\nĐoạn **đậm** và *nghiêng*.\n\n"
        "| A | B |\n|---|---|\n| 1 | 2 |\n\n- mục một\n- mục hai\n"
    )
    assert "<h2>Tiêu đề</h2>" in html
    assert "<strong>đậm</strong>" in html
    assert "<em>nghiêng</em>" in html
    assert "<table" in html and "<th>A</th>" in html and "<td>2</td>" in html
    assert "<ul>" in html and "<li>mục một</li>" in html


def test_render_escapes_html():
    html = lessons.render_markdown("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_uni_pages_require_perm(client):
    create_owner(client)
    r = client.get("/uni")
    assert r.status_code == 200
    assert "Apyko Uni" in r.text
    assert "58" in r.text


def test_lesson_detail_and_learn_progress(client):
    create_owner(client)
    all_lessons = lessons.list_lessons()
    lid = all_lessons[0]["id"]
    r = client.get(f"/uni/{lid}")
    assert r.status_code == 200
    assert all_lessons[0]["title"] in r.text
    assert "Chưa học" in r.text
    # Đánh dấu đã học
    r = client.post(f"/uni/{lid}/learn", data={"learned": "1"}, follow_redirects=False)
    assert r.status_code == 303
    r = client.get(f"/uni/{lid}")
    assert "Đã học" in r.text
    r = client.get("/uni")
    assert "1/58" in r.text
    # API cũng thấy
    r = client.get("/api/uni")
    body = r.json()
    assert body["total"] == 58
    assert body["done"] == 1


def test_lesson_404(client):
    create_owner(client)
    assert client.get("/uni/khong-ton-tai").status_code == 404


def test_render_markdown_image():
    html = lessons.render_markdown("![Mô tả ảnh](/static/lesson-images/x.png)")
    assert '<img src="/static/lesson-images/x.png"' in html
    assert 'class="lesson-img"' in html
    # Link thường vẫn render như cũ, không bị lẫn với ảnh
    html2 = lessons.render_markdown("[Shopee](https://shopee.vn)")
    assert '<a href="https://shopee.vn"' in html2
    assert "<img" not in html2


def test_lesson_56_cskh_content(client):
    create_owner(client)
    lesson = lessons.get_lesson("56-cskh-loi-sai-hay-gap")
    assert lesson is not None
    r = client.get("/uni/56-cskh-loi-sai-hay-gap")
    assert r.status_code == 200
    html = r.text
    assert "Quy định khi chat với khách hàng" in html
    assert "Không giao dịch bên ngoài sàn TMĐT" in html
    assert "Phạt 100k/lần viết tắt khi chat" in html
    assert "Khách hỏi có ship ngoài không" in html
    assert "chụp giúp em màn hình phần thông tin đơn hàng" in html
    assert '<img src="/static/lesson-images/cskh-thong-tin-don-hang.png"' in html
    # File ảnh tĩnh phục vụ được
    assert client.get("/static/lesson-images/cskh-thong-tin-don-hang.png").status_code == 200


def test_render_table_without_separator():
    md = "| Loại combo | Mục đích |\n| Lấy đánh giá | Gom đánh giá |\n| Lấy số bán | Tăng đơn |"
    html = lessons.render_markdown(md)
    assert '<table class="md-table">' in html
    assert "<th>Loại combo</th>" in html
    assert "<td>Lấy đánh giá</td>" in html
    assert "|" not in html.replace('<div class="md-table-wrap">', "")


def test_render_table_numeric_first_col_no_fake_header():
    md = "| 1 | Xác định mục tiêu |\n| 2 | Chia bậc |"
    html = lessons.render_markdown(md)
    assert '<table class="md-table">' in html
    assert "<thead>" not in html
    assert "<td>1</td>" in html


def test_render_loose_numbered_list_single_ol():
    md = "1. Mục một\n\n1. Mục hai\n\n1. Mục ba"
    html = lessons.render_markdown(md)
    assert html.count("<ol>") == 1
    assert html.count("<li>") == 3
