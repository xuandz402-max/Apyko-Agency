"""Cache raw libsql connection theo thread cho backend Turso.

Mỗi lần libsql.connect() là một handshake TLS + Hrana về Tokyo (~0.5-1s),
trong khi một request gọi get_conn() nhiều lần. get_conn() phải:
- dùng chung 1 raw connection cho cùng thread (kiểm tra sức khỏe SELECT 1),
- kết nối lại khi connection cũ lỗi,
- 2 thread khác nhau -> 2 raw connection riêng,
- giữ nguyên ngữ nghĩa commit/rollback của khối with.

Ghi chú: Turso remote THẬT không test được ở đây; dùng libsql.connect() trỏ
file local (cùng libsql core engine) và monkeypatch để đếm số lần connect.
"""

import logging
import sys
import threading

import pytest

FAKE_URL = "libsql://fake-test.turso.io"
FAKE_TOKEN = "fake-token-khong-dung-that"


def _purge_app_modules():
    for name in [n for n in sys.modules if n == "app" or n.startswith("app.")]:
        sys.modules.pop(name)


def _setup_turso_env(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key-khong-dung-that")
    monkeypatch.setenv("SESSION_DAYS", "30")
    monkeypatch.setenv("TURSO_DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("TURSO_AUTH_TOKEN", FAKE_TOKEN)


def _counting_connect(monkeypatch, tmp_path, prefix):
    """Giả libsql.connect: đếm số lần gọi, trả về file libsql local thật."""
    import libsql

    real_connect = libsql.connect
    calls = []

    def fake_connect(url, auth_token=None):
        calls.append((url, auth_token))
        return real_connect(str(tmp_path / f"{prefix}-{len(calls)}.db"))

    monkeypatch.setattr(libsql, "connect", fake_connect)
    return calls


def _fresh_db(monkeypatch, tmp_path, prefix="pool"):
    _setup_turso_env(monkeypatch)
    calls = _counting_connect(monkeypatch, tmp_path, prefix)
    _purge_app_modules()
    import app.database as db

    db.init_db()
    return db, calls


@pytest.fixture()
def db_pair(tmp_path, monkeypatch):
    return _fresh_db(monkeypatch, tmp_path)


def test_same_thread_reuses_single_raw_connection(db_pair):
    """N lần get_conn() cùng thread -> libsql.connect đúng 1 lần (đã tính init_db)."""
    db, calls = db_pair
    assert len(calls) == 1  # chỉ lần init_db

    wrappers = [db.get_conn() for _ in range(10)]
    assert len(calls) == 1, f"muốn 1 connect, thực tế {len(calls)} lần"
    assert all(isinstance(w, db._TursoConnection) for w in wrappers)
    assert len({id(w._conn) for w in wrappers}) == 1  # dùng chung 1 raw


def test_dead_connection_reconnects(tmp_path, monkeypatch, caplog):
    """Connection chết (SELECT 1 lỗi) -> bỏ cũ, kết nối lại."""
    db, calls = _fresh_db(monkeypatch, tmp_path, prefix="dead")
    assert len(calls) == 1
    old_raw = db.get_conn()._conn

    class _DeadRaw:
        def __init__(self, raw):
            self._raw = raw

        def execute(self, *args, **kwargs):
            raise RuntimeError("connection reset by peer")

        def __getattr__(self, name):
            return getattr(self._raw, name)

    db._turso_tls.raw = _DeadRaw(old_raw)
    with caplog.at_level(logging.WARNING, logger="apyko.db"):
        w = db.get_conn()
    assert len(calls) == 2, f"muốn 2 connect (1 cũ + 1 mới), thực tế {len(calls)}"
    assert w._conn is not old_raw  # raw đã được thay
    assert not isinstance(w._conn, _DeadRaw)  # wrapper mới bọc raw thật
    assert any("kết nối lại" in r.message for r in caplog.records)
    # kết nối mới dùng được bình thường
    with w:
        row = w.execute("SELECT 1 AS one").fetchone()
    assert row["one"] == 1


def test_two_threads_get_separate_raw_connections(tmp_path, monkeypatch):
    """2 thread khác nhau -> 2 raw connection riêng; cùng thread vẫn dùng chung."""
    db, calls = _fresh_db(monkeypatch, tmp_path, prefix="threads")
    base_calls = len(calls)
    raws = []
    errors = []

    def worker():
        try:
            first = db.get_conn()
            for _ in range(3):  # cùng thread vẫn chung 1 raw
                assert db.get_conn()._conn is first._conn
            raws.append(first._conn)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"lỗi trong thread: {errors}"
    assert len(raws) == 2
    assert raws[0] is not raws[1]
    assert len(calls) == base_calls + 2  # mỗi thread 1 raw connection


def test_with_block_commit_rollback_on_shared_connection(db_pair):
    """Khối with vẫn commit khi xong, rollback khi lỗi — dù dùng chung raw."""
    db, _ = db_pair

    with db.get_conn() as conn:
        conn.execute("INSERT INTO gmv_products (name, created_at) VALUES (?, ?)", ("A", "t"))
    with db.get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) AS c FROM gmv_products").fetchone()["c"]
    assert n == 1

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom):
        with db.get_conn() as conn:
            conn.execute("INSERT INTO gmv_products (name, created_at) VALUES (?, ?)", ("B", "t"))
            raise _Boom()
    with db.get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) AS c FROM gmv_products").fetchone()["c"]
    assert n == 1  # dòng B đã rollback


def test_sqlite_fallback_not_cached(tmp_path, monkeypatch):
    """Nhánh SQLite local giữ nguyên: mỗi get_conn() là 1 connection mới."""
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key-khong-dung-that")
    monkeypatch.setenv("SESSION_DAYS", "30")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "local.db"))
    _purge_app_modules()
    import sqlite3

    from app.database import get_conn

    a, b = get_conn(), get_conn()
    assert isinstance(a, sqlite3.Connection) and isinstance(b, sqlite3.Connection)
    assert a is not b  # không cache cho SQLite local
    a.close()
    b.close()
