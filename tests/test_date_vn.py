"""Ô nhập ngày DD/MM/YYYY + giờ HH:MM kiểu VN (static/date-vn.js).

Kiểm ở mức render + hợp đồng server:
- Mọi trang có ô ngày render ô text có class date-vn + placeholder,
  KHÔNG còn <input type="date"> / type="time" ở bất kỳ trang nào.
- File /static/date-vn.js được phục vụ và được nạp từ layout.
- Server vẫn nhận ISO như cũ (không đổi route/tham số).
- Hàm thuần của date-vn.js được kiểm bằng node (bỏ qua nếu máy không có node).
"""

import os
import shutil
import subprocess

from conftest import create_owner

_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _assert_vn_date_page(html):
    assert 'type="date"' not in html
    assert "date-vn" in html
    assert 'placeholder="DD/MM/YYYY"' in html


def _assert_range_picker_page(html):
    """Trang đã chuyển sang bộ chọn khoảng kiểu Shopee Ads: không còn ô
    ngày native, có panel lịch + preset của bộ chọn (data-rp / rp-preset)."""
    assert 'type="date"' not in html
    assert "data-rp" in html
    assert "rp-preset" in html
    assert "7 ngày qua" in html


def test_ceo_page_uses_vn_date_inputs(client):
    create_owner(client)
    r = client.get("/ceo")
    assert r.status_code == 200
    # Dashboard CEO không còn ô gõ ngày: chọn khoảng bằng lịch của bộ chọn
    _assert_range_picker_page(r.text)
    assert "/static/date-vn.js" in r.text


def test_daily_page_uses_vn_date_inputs(client):
    create_owner(client)
    r = client.get("/bao-cao")
    assert r.status_code == 200
    _assert_vn_date_page(r.text)


def test_gmv_page_uses_vn_date_inputs(client):
    create_owner(client)
    # Ô ngày VN nằm ở form nhập dòng — form chỉ hiện khi đã có sản phẩm
    from app import database as db

    db.gmv_create_product("SP DATE VN")
    r = client.get("/gmv")
    assert r.status_code == 200
    _assert_vn_date_page(r.text)


def test_checklist_pages_use_vn_date_inputs(client):
    create_owner(client)
    for url in ("/checklist", "/checklist/board"):
        r = client.get(url)
        assert r.status_code == 200, url
        _assert_vn_date_page(r.text)
    # /kpi đã chuyển sang bộ chọn khoảng (lịch + preset), không còn ô gõ ngày
    r = client.get("/kpi")
    assert r.status_code == 200
    _assert_range_picker_page(r.text)


def test_checklist_admin_uses_vn_time_inputs(client):
    create_owner(client)
    r = client.get("/checklist/admin")
    assert r.status_code == 200
    assert 'type="time"' not in r.text
    assert "time-vn" in r.text
    assert 'placeholder="HH:MM"' in r.text


def test_no_native_date_or_time_inputs_left_in_templates():
    tpl_dir = os.path.join(_PROJECT, "templates")
    offenders = []
    for name in os.listdir(tpl_dir):
        if not name.endswith(".html"):
            continue
        with open(os.path.join(tpl_dir, name), encoding="utf-8") as f:
            text = f.read()
        if 'type="date"' in text or 'type="time"' in text:
            offenders.append(name)
    assert offenders == []


def test_date_vn_js_is_served(client):
    create_owner(client)
    r = client.get("/static/date-vn.js")
    assert r.status_code == 200
    assert "DateVN" in r.text


def test_server_still_accepts_iso_params(client):
    """Hợp đồng không đổi: server vẫn nhận ngày ISO trên query như trước."""
    create_owner(client)
    r = client.get("/checklist?date=2026-10-20")
    assert r.status_code == 200
    assert 'value="2026-10-20"' in r.text  # value trong HTML giữ ISO


def test_date_vn_pure_functions_with_node():
    node = shutil.which("node")
    if not node:
        import pytest

        pytest.skip("máy không có node")
    script = os.path.join(_PROJECT, "tests", "date_vn_node_test.js")
    r = subprocess.run(
        [node, script], capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ALL PASS" in r.stdout
