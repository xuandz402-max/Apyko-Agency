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
