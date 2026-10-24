"""GMV chuyển từ RM sang VNĐ: migration một lần, form nhập VNĐ trực tiếp,
trang GMV không còn chữ RM."""

import sqlite3

from app import database as db
from conftest import create_owner

OLD_SCHEMA = """
CREATE TABLE gmv_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE gmv_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES gmv_products(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    clicks INTEGER NOT NULL DEFAULT 0,
    conversions INTEGER NOT NULL DEFAULT 0,
    revenue_rm REAL NOT NULL DEFAULT 0,
    ad_cost REAL NOT NULL DEFAULT 0,
    action_note TEXT DEFAULT '',
    updated_by TEXT DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE (product_id, date)
);
"""


def _old_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO gmv_products (name, created_at) VALUES ('SP CU', '2026-10-20T00:00:00')"
    )
    conn.execute(
        "INSERT INTO gmv_entries (product_id, date, views, clicks, conversions,"
        " revenue_rm, ad_cost, updated_at)"
        " VALUES (1, '2026-10-20', 100, 10, 2, 100, 30, '2026-10-20T00:00:00')"
    )
    conn.commit()
    return conn


def test_migration_converts_rm_to_vnd_exactly_once():
    conn = _old_db()
    db._migrate_gmv_currency_vnd(conn)
    conn.commit()
    row = conn.execute("SELECT * FROM gmv_entries WHERE id = 1").fetchone()
    assert row["revenue_vnd"] == 100 * 5300
    assert row["ad_cost"] == 30 * 5300
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(gmv_entries)").fetchall()}
    assert "revenue_rm" not in cols and "revenue_vnd" in cols
    flag = conn.execute(
        "SELECT value FROM app_meta WHERE key = 'gmv_currency_vnd'"
    ).fetchone()
    assert flag is not None
    # Chạy lần hai: không nhân đôi
    db._migrate_gmv_currency_vnd(conn)
    conn.commit()
    row = conn.execute("SELECT * FROM gmv_entries WHERE id = 1").fetchone()
    assert row["revenue_vnd"] == 100 * 5300
    assert row["ad_cost"] == 30 * 5300


def test_fresh_db_has_vnd_column_and_flag(client):
    create_owner(client)
    # DB mới qua init_db: cột đã là revenue_vnd, cờ đã ghi, không đổi số liệu
    r = client.post("/api/gmv/products", json={"name": "SP VND"})
    pid = r.json()["id"]
    r = client.post(
        f"/api/gmv/products/{pid}/entries",
        json={
            "date": "2026-10-20",
            "views": 100,
            "clicks": 10,
            "conversions": 2,
            "revenue_vnd": 530000,
            "ad_cost": 159000,
            "action_note": "",
        },
    )
    assert r.status_code == 201
    entry = r.json()
    assert entry["revenue_vnd"] == 530000  # ghi đúng số VNĐ nhập, không chia
    assert entry["ad_cost"] == 159000
    assert entry["calc"]["cpc"] == 15900
    assert entry["calc"]["aov"] == 265000


def test_gmv_page_has_no_rm_string(client):
    create_owner(client)
    r = client.get("/gmv")
    assert r.status_code == 200
    assert "RM" not in r.text
    assert "VNĐ" in r.text
    assert "5300" not in r.text
