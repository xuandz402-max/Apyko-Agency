"""Backend Turso (libsql): chọn backend theo env, wrapper tương thích sqlite3.Row,
chuẩn hoá lỗi IntegrityError, init_db và API 409 trên cả 2 backend.

Ghi chú kiểm chứng: Turso remote THẬT không test được trong môi trường này
(cần tài khoản turso.tech để tạo database). Test dùng libsql.connect() trỏ file
local — cùng libsql core engine với Turso remote — và monkeypatch libsql.connect
để kiểm tra nhánh chọn backend theo biến môi trường.
"""

import os
import sqlite3
import sys

import pytest

from conftest import create_owner

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

FAKE_URL = "libsql://fake-test.turso.io"
FAKE_TOKEN = "fake-token-chi-dung-cho-test"


def _purge_app_modules():
    for name in [n for n in sys.modules if n == "app" or n.startswith("app.")]:
        sys.modules.pop(name)


def _setup_env(monkeypatch, tmp_path, turso=True):
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key-khong-dung-that")
    monkeypatch.setenv("SESSION_DAYS", "30")
    if turso:
        monkeypatch.setenv("TURSO_DATABASE_URL", FAKE_URL)
        monkeypatch.setenv("TURSO_AUTH_TOKEN", FAKE_TOKEN)
    else:
        monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
        monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "local.db"))


def _fake_turso_connect(monkeypatch, tmp_path):
    """Giả libsql.connect: ghi lại args, trả về file libsql local (cùng engine)."""
    import libsql

    real_connect = libsql.connect
    calls = []

    def fake_connect(url, auth_token=None):
        calls.append((url, auth_token))
        return real_connect(str(tmp_path / "turso-test.db"))

    monkeypatch.setattr(libsql, "connect", fake_connect)
    return calls


@pytest.fixture()
def turso_db(tmp_path, monkeypatch):
    """Module app.database mới import, backend Turso (giả bằng file libsql local)."""
    _setup_env(monkeypatch, tmp_path, turso=True)
    _fake_turso_connect(monkeypatch, tmp_path)
    _purge_app_modules()
    import app.database as db

    db.init_db()
    return db


def test_get_conn_fallback_sqlite_when_env_missing(tmp_path, monkeypatch):
    _setup_env(monkeypatch, tmp_path, turso=False)
    _purge_app_modules()
    from app.database import get_conn

    conn = get_conn()
    assert isinstance(conn, sqlite3.Connection)
    conn.close()


def test_get_conn_fallback_when_only_one_turso_var(tmp_path, monkeypatch):
    _setup_env(monkeypatch, tmp_path, turso=True)
    monkeypatch.delenv("TURSO_AUTH_TOKEN")  # thiếu 1 biến -> fallback
    _purge_app_modules()
    from app.database import get_conn

    conn = get_conn()
    assert isinstance(conn, sqlite3.Connection)
    conn.close()


def test_get_conn_selects_turso_when_env_set(tmp_path, monkeypatch):
    _setup_env(monkeypatch, tmp_path, turso=True)
    calls = _fake_turso_connect(monkeypatch, tmp_path)
    _purge_app_modules()
    from app.database import _TursoConnection, get_conn

    conn = get_conn()
    assert isinstance(conn, _TursoConnection)
    assert calls == [(FAKE_URL, FAKE_TOKEN)]


def test_turso_row_wrapper_parity(turso_db):
    with turso_db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO gmv_products (name, created_at) VALUES (?, ?)",
            ("Liềm", "2024-01-01T00:00:00"),
        )
        pid = cur.lastrowid
        assert pid is not None
    with turso_db.get_conn() as conn:
        row = conn.execute("SELECT * FROM gmv_products WHERE id = ?", (pid,)).fetchone()
    assert row["name"] == "Liềm"  # truy cập theo tên cột như sqlite3.Row
    assert row["id"] == pid
    assert row[0] == pid  # truy cập theo index
    d = dict(row)  # chuyển thành dict
    assert d["name"] == "Liềm" and d["id"] == pid
    assert "name" in row.keys() and len(row) == len(row.keys())


def test_turso_unique_violation_maps_to_integrity_error(turso_db):
    turso_db.gmv_create_product("Trùng tên")
    with pytest.raises(sqlite3.IntegrityError):
        turso_db.gmv_create_product("Trùng tên")


def test_turso_init_db_creates_all_tables_and_idempotent(turso_db, tmp_path):
    import libsql

    conn = libsql.connect(str(tmp_path / "turso-test.db"))
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {
        "products",
        "users",
        "sessions",
        "lesson_progress",
        "gmv_products",
        "gmv_entries",
        "daily_reports",
    } <= tables
    turso_db.init_db()  # chạy lại không lỗi


def test_turso_with_block_commit_and_rollback(turso_db):
    from app.database import get_conn

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO gmv_products (name, created_at) VALUES (?, ?)", ("A", "t")
        )
    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) AS c FROM gmv_products").fetchone()["c"]
    assert n == 1
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO gmv_products (name, created_at) VALUES (?, ?)", ("B", "t")
            )
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) AS c FROM gmv_products").fetchone()["c"]
    assert n == 1  # dòng B đã rollback như sqlite3


def test_turso_pragma_failure_tolerated(tmp_path, monkeypatch, caplog):
    _setup_env(monkeypatch, tmp_path, turso=True)
    import libsql

    real_connect = libsql.connect

    class _NoPragmaConn:
        def __init__(self, raw):
            self._raw = raw

        def execute(self, sql, params=()):
            if sql.strip().upper().startswith("PRAGMA"):
                raise Exception("PRAGMA không hỗ trợ ở remote")
            return self._raw.execute(sql, params)

        def __getattr__(self, name):
            return getattr(self._raw, name)

    def fake_connect(url, auth_token=None):
        return _NoPragmaConn(real_connect(str(tmp_path / "turso-test.db")))

    monkeypatch.setattr(libsql, "connect", fake_connect)
    _purge_app_modules()
    from app.database import _TursoConnection, get_conn

    with caplog.at_level("WARNING", logger="apyko.db"):
        conn = get_conn()
    assert isinstance(conn, _TursoConnection)
    assert any("PRAGMA" in r.message for r in caplog.records)


def _make_turso_client(tmp_path, monkeypatch):
    _setup_env(monkeypatch, tmp_path, turso=True)
    _fake_turso_connect(monkeypatch, tmp_path)
    _purge_app_modules()
    from app.database import init_db
    from app.main import app
    from fastapi.testclient import TestClient

    init_db()
    return TestClient(app)


def test_api_409_duplicate_gmv_product_on_turso_backend(tmp_path, monkeypatch):
    """Vi phạm UNIQUE qua backend Turso vẫn trả 409 như SQLite (routes.py giữ nguyên)."""
    client = _make_turso_client(tmp_path, monkeypatch)
    create_owner(client)
    r1 = client.post("/api/gmv/products", json={"name": "Ốc nở"})
    assert r1.status_code == 201, r1.text
    r2 = client.post("/api/gmv/products", json={"name": "Ốc nở"})
    assert r2.status_code == 409
    assert "đã tồn tại" in r2.json()["detail"]
