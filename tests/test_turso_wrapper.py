"""Regression: đường Turso/libsql (file backend) cho module Daily Checklist.

Lỗi đã bắt live (2026-10-20): libsql trả tên cột "key" thành "KEY" (từ khóa),
làm cl_setting_get_all() KeyError trên Turso dù SQLite local chạy đúng.
Test này chạy các hàm DB của checklist qua wrapper _TursoConnection bằng
file backend để chặn lỗi cùng lớp trong tương lai.

Lưu ý: phải import lại app.* sau khi set env (giống conftest.make_client)
vì config đọc biến môi trường lúc import và các test khác cũng làm vậy —
dùng module cũ sẽ lẫn đường kết nối SQLite/Turso giữa các test.
"""

import sys

import pytest


@pytest.fixture()
def turso_mods(tmp_path, monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", f"file:{tmp_path / 'turso.db'}")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "x")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "fallback.db"))
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key-khong-dung-that")
    monkeypatch.setenv("DISABLE_BACKGROUND", "1")
    for name in [n for n in sys.modules if n == "app" or n.startswith("app.")]:
        sys.modules.pop(name)
    import app.checklist as checklist
    import app.database as db

    assert db._turso_enabled()
    db.init_db()
    return db, checklist


def test_settings_roundtrip_via_turso_wrapper(turso_mods):
    db, checklist = turso_mods
    db.cl_setting_set("work_start", "08:00")
    db.cl_setting_set("work_end", "17:30")
    all_settings = db.cl_setting_get_all()
    assert all_settings["work_start"] == "08:00"
    assert all_settings["work_end"] == "17:30"


def test_get_settings_defaults_via_turso_wrapper(turso_mods):
    db, checklist = turso_mods
    s = checklist.get_settings()
    assert s["work_start"] == "08:00"
    assert s["work_end"] == "17:30"
    assert s["reminder_interval_min"] == 30
    assert s["due_soon_min"] == 30


def test_row_case_insensitive_fallback(turso_mods):
    db, checklist = turso_mods
    with db.get_conn() as conn:
        cur = conn.execute("SELECT key, value FROM checklist_settings")
        rows = cur.fetchall()
    row = rows[0]
    # libsql trả "KEY" hoa; wrapper phải cho phép đọc "key" thường
    assert row["key"] == row["KEY"]


def test_checklist_generate_and_list_via_turso_wrapper(turso_mods):
    db, checklist = turso_mods
    db.cl_template_create(
        {
            "group_name": "Nhóm test",
            "title": "Việc test",
            "sort": 1,
            "due_time": "09:00",
            "assignee_id": None,
            "shop_id": None,
            "is_active": 1,
        }
    )
    # init_db đã seed sẵn 20 mẫu mặc định + 1 mẫu của test này = 21
    created = checklist.generate_for_date("2026-10-21")
    assert created == 21
    assert checklist.generate_for_date("2026-10-21") == 0  # không trùng
    items = db.cl_item_list("2026-10-21")
    assert len(items) == 21
    mine = [it for it in items if it["title"] == "Việc test"]
    assert len(mine) == 1
    assert mine[0]["due_time"] == "09:00"
