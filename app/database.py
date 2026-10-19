"""Tầng lưu trữ SQLite (stdlib sqlite3).

Bảng:
- products: như bản MUSE-PRODUCT-RESEARCH.
- users: tài khoản (owner + nhân sự), cờ phân quyền, mã kích hoạt.
- sessions: token phiên đăng nhập.
- lesson_progress: tiến độ học Apyko Uni theo tài khoản.
- gmv_products / gmv_entries: theo dõi chỉ số quảng cáo Shopee GMV Max theo ngày.
- daily_reports: báo cáo doanh thu ngày (1 dòng / ngày), xuất ảnh PNG gửi Zalo.
"""

import os
import sqlite3
from datetime import datetime, timezone

from . import config
from .calc import analyze_product
from .gmv import GMV_SEED_PRODUCTS

PRODUCT_COLUMNS = [
    "id",
    "name",
    "sku",
    "category",
    "data_source",
    "selling_price",
    "cost_price",
    "packaging_cost",
    "shipping_seller",
    "platform_fee_rate",
    "payment_fee_rate",
    "ads_rate",
    "affiliate_rate",
    "other_cost",
    "demand_score",
    "competition_score",
    "content_score",
    "supply_score",
    "status",
    "is_demo",
    "notes",
    "updated_at",
]

USER_COLUMNS = [
    "id",
    "username",
    "display_name",
    "password_hash",
    "is_owner",
    "is_active",
    "must_activate",
    "activation_code",
    "can_view_products",
    "can_add_edit_products",
    "can_delete_products",
    "can_view_uni",
    "created_at",
    "updated_at",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sku TEXT NOT NULL DEFAULT '',
    category TEXT DEFAULT '',
    data_source TEXT DEFAULT '',
    selling_price REAL NOT NULL DEFAULT 0,
    cost_price REAL NOT NULL DEFAULT 0,
    packaging_cost REAL NOT NULL DEFAULT 0,
    shipping_seller REAL NOT NULL DEFAULT 0,
    platform_fee_rate REAL NOT NULL DEFAULT 0,
    payment_fee_rate REAL NOT NULL DEFAULT 0,
    ads_rate REAL NOT NULL DEFAULT 0,
    affiliate_rate REAL NOT NULL DEFAULT 0,
    other_cost REAL NOT NULL DEFAULT 0,
    demand_score INTEGER,
    competition_score INTEGER,
    content_score INTEGER,
    supply_score INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    is_demo INTEGER NOT NULL DEFAULT 0,
    notes TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL DEFAULT '',
    is_owner INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 0,
    must_activate INTEGER NOT NULL DEFAULT 0,
    activation_code TEXT DEFAULT '',
    can_view_products INTEGER NOT NULL DEFAULT 1,
    can_add_edit_products INTEGER NOT NULL DEFAULT 0,
    can_delete_products INTEGER NOT NULL DEFAULT 0,
    can_view_uni INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS lesson_progress (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lesson_id TEXT NOT NULL,
    learned INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, lesson_id)
);
CREATE TABLE IF NOT EXISTS gmv_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gmv_entries (
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
CREATE TABLE IF NOT EXISTS daily_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    rev_product REAL NOT NULL DEFAULT 0,
    rev_live REAL NOT NULL DEFAULT 0,
    rev_video REAL NOT NULL DEFAULT 0,
    rev_aff_link REAL NOT NULL DEFAULT 0,
    rev_affiliate REAL NOT NULL DEFAULT 0,
    ad_gmv REAL NOT NULL DEFAULT 0,
    ad_cost REAL NOT NULL DEFAULT 0,
    aov REAL NOT NULL DEFAULT 0,
    conv_rate REAL NOT NULL DEFAULT 0,
    note TEXT DEFAULT '',
    updated_by TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    parent = os.path.dirname(config.DATABASE_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)


# ------------------------------ products ----------------------------------


def _clean_product(d: dict, for_insert: bool = False) -> dict:
    data = {k: v for k, v in d.items() if k in PRODUCT_COLUMNS and k != "id"}
    if for_insert:
        data.setdefault("status", "active")
    data["updated_at"] = _utcnow()
    return data


def create_product(d: dict) -> int:
    data = _clean_product(d, for_insert=True)
    cols = list(data.keys())
    placeholders = ", ".join("?" for _ in cols)
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO products ({', '.join(cols)}) VALUES ({placeholders})",
            [data[c] for c in cols],
        )
        return cur.lastrowid


def get_product(product_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return dict(row) if row is not None else None


_VALID_SORTS = {"name", "selling_price", "profit", "margin", "score", "updated_at"}


def _sort_value(item: dict, sort: str):
    if sort == "name":
        return item["product"]["name"] or ""
    if sort == "selling_price":
        return item["product"]["selling_price"]
    if sort == "profit":
        return item["calc"]["profit"]
    if sort == "margin":
        return item["calc"]["margin"]
    if sort == "score":
        return item["score"]["score"]
    return item["product"]["updated_at"] or ""


def list_products(
    q: str | None = None,
    category: str | None = None,
    status: str | None = None,
    sort: str = "updated_at",
    dir: str = "desc",
) -> list:
    if sort not in _VALID_SORTS:
        sort = "updated_at"
    reverse = (dir or "desc").lower() != "asc"
    clauses: list[str] = []
    params: list = []
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        clauses.append("(name LIKE ? ESCAPE '\\' OR sku LIKE ? ESCAPE '\\')")
        params.extend([like, like])
    if category:
        clauses.append("category = ?")
        params.append(category)
    if status:
        clauses.append("status = ?")
        params.append(status)
    sql = "SELECT * FROM products"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    items = [analyze_product(dict(r)) for r in rows]
    with_value = [it for it in items if _sort_value(it, sort) is not None]
    without_value = [it for it in items if _sort_value(it, sort) is None]
    with_value.sort(key=lambda it: _sort_value(it, sort), reverse=reverse)
    return with_value + without_value


def update_product(product_id: int, d: dict) -> dict | None:
    data = _clean_product(d)
    if not data:
        return get_product(product_id)
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE products SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
            [*data.values(), product_id],
        )
        if cur.rowcount == 0:
            return None
    return get_product(product_id)


def delete_product(product_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        return cur.rowcount > 0


def clear_demo() -> int:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM products WHERE is_demo = 1")
        return cur.rowcount


def distinct_categories() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM products "
            "WHERE category IS NOT NULL AND category != '' ORDER BY category"
        ).fetchall()
    return [r["category"] for r in rows]


# ------------------------------- users ------------------------------------


def count_users() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    return row["c"]


def _clean_user(d: dict) -> dict:
    return {k: v for k, v in d.items() if k in USER_COLUMNS and k != "id"}


def create_user(d: dict) -> int:
    data = _clean_user(d)
    data["created_at"] = _utcnow()
    data["updated_at"] = _utcnow()
    cols = list(data.keys())
    placeholders = ", ".join("?" for _ in cols)
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO users ({', '.join(cols)}) VALUES ({placeholders})",
            [data[c] for c in cols],
        )
        return cur.lastrowid


def get_user(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row is not None else None


def get_user_by_username(username: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    return dict(row) if row is not None else None


def list_users() -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY is_owner DESC, id ASC").fetchall()
    return [dict(r) for r in rows]


def update_user(user_id: int, d: dict) -> dict | None:
    data = _clean_user(d)
    if not data:
        return get_user(user_id)
    data["updated_at"] = _utcnow()
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE users SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
            [*data.values(), user_id],
        )
        if cur.rowcount == 0:
            return None
    return get_user(user_id)


def delete_user(user_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cur.rowcount > 0


# ------------------------------ sessions ----------------------------------


def create_session(token: str, user_id: int, expires_at: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at, revoked)"
            " VALUES (?, ?, ?, ?, 0)",
            (token, user_id, _utcnow(), expires_at),
        )


def get_session(token: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
    return dict(row) if row is not None else None


def revoke_user_sessions(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET revoked = 1 WHERE user_id = ?", (user_id,))


def delete_session(token: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


# --------------------------- lesson progress ------------------------------


def get_learned_lessons(user_id: int) -> set:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT lesson_id FROM lesson_progress WHERE user_id = ? AND learned = 1",
            (user_id,),
        ).fetchall()
    return {r["lesson_id"] for r in rows}


def set_lesson_learned(user_id: int, lesson_id: str, learned: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO lesson_progress (user_id, lesson_id, learned, updated_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(user_id, lesson_id) DO UPDATE SET learned = ?, updated_at = ?",
            (user_id, lesson_id, 1 if learned else 0, _utcnow(), 1 if learned else 0, _utcnow()),
        )


# --------------------------- gmv max shopee -------------------------------


def gmv_list_products() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT p.id, p.name, p.created_at,"
            " COUNT(e.id) AS entry_count, MAX(e.updated_at) AS last_entry_at"
            " FROM gmv_products p LEFT JOIN gmv_entries e ON e.product_id = p.id"
            " GROUP BY p.id ORDER BY p.id ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def gmv_get_product(product_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM gmv_products WHERE id = ?", (product_id,)).fetchone()
    return dict(row) if row is not None else None


def gmv_create_product(name: str) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("Tên sản phẩm không được trống.")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO gmv_products (name, created_at) VALUES (?, ?)", (name, _utcnow())
        )
        return cur.lastrowid


def gmv_rename_product(product_id: int, name: str) -> dict | None:
    name = (name or "").strip()
    if not name:
        raise ValueError("Tên sản phẩm không được trống.")
    with get_conn() as conn:
        cur = conn.execute("UPDATE gmv_products SET name = ? WHERE id = ?", (name, product_id))
        if cur.rowcount == 0:
            return None
    return gmv_get_product(product_id)


def gmv_delete_product(product_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM gmv_products WHERE id = ?", (product_id,))
        return cur.rowcount > 0


def gmv_list_entries(product_id: int) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM gmv_entries WHERE product_id = ? ORDER BY date ASC", (product_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def gmv_get_entry(entry_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM gmv_entries WHERE id = ?", (entry_id,)).fetchone()
    return dict(row) if row is not None else None


def gmv_last_updated(product_id: int) -> str | None:
    """Mốc thay đổi mới nhất (dùng cho polling)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(updated_at) AS m FROM ("
            " SELECT updated_at FROM gmv_entries WHERE product_id = ?"
            " UNION ALL SELECT created_at FROM gmv_products WHERE id = ?)",
            (product_id, product_id),
        ).fetchone()
    return row["m"] if row is not None else None


def gmv_upsert_entry(product_id: int, data: dict, updated_by: str) -> tuple:
    """Thêm dòng theo ngày; ngày đã tồn tại thì cập nhật. Trả về (entry, created)."""
    now = _utcnow()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM gmv_entries WHERE product_id = ? AND date = ?",
            (product_id, data["date"]),
        ).fetchone()
        if existing is not None:
            conn.execute(
                "UPDATE gmv_entries SET views = ?, clicks = ?, conversions = ?,"
                " revenue_rm = ?, ad_cost = ?, action_note = ?,"
                " updated_by = ?, updated_at = ? WHERE id = ?",
                (
                    data["views"],
                    data["clicks"],
                    data["conversions"],
                    data["revenue_rm"],
                    data["ad_cost"],
                    data["action_note"],
                    updated_by,
                    now,
                    existing["id"],
                ),
            )
            entry_id = existing["id"]
            created = False
        else:
            cur = conn.execute(
                "INSERT INTO gmv_entries (product_id, date, views, clicks, conversions,"
                " revenue_rm, ad_cost, action_note, updated_by, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    product_id,
                    data["date"],
                    data["views"],
                    data["clicks"],
                    data["conversions"],
                    data["revenue_rm"],
                    data["ad_cost"],
                    data["action_note"],
                    updated_by,
                    now,
                ),
            )
            entry_id = cur.lastrowid
            created = True
        row = conn.execute("SELECT * FROM gmv_entries WHERE id = ?", (entry_id,)).fetchone()
    return dict(row), created


def gmv_update_entry(entry_id: int, data: dict, updated_by: str) -> dict | None:
    """Sửa dòng theo id. Raise sqlite3.IntegrityError nếu đổi ngày gây trùng."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE gmv_entries SET date = ?, views = ?, clicks = ?, conversions = ?,"
            " revenue_rm = ?, ad_cost = ?, action_note = ?,"
            " updated_by = ?, updated_at = ? WHERE id = ?",
            (
                data["date"],
                data["views"],
                data["clicks"],
                data["conversions"],
                data["revenue_rm"],
                data["ad_cost"],
                data["action_note"],
                updated_by,
                _utcnow(),
                entry_id,
            ),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM gmv_entries WHERE id = ?", (entry_id,)).fetchone()
    return dict(row) if row is not None else None


def gmv_delete_entry(entry_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM gmv_entries WHERE id = ?", (entry_id,))
        return cur.rowcount > 0


# --------------------------- báo cáo ngày -------------------------------


DAILY_COLUMNS = [
    "rev_product",
    "rev_live",
    "rev_video",
    "rev_aff_link",
    "rev_affiliate",
    "ad_gmv",
    "ad_cost",
    "aov",
    "conv_rate",
    "note",
]


def daily_list() -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM daily_reports ORDER BY date DESC").fetchall()
    return [dict(r) for r in rows]


def daily_get(report_date: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM daily_reports WHERE date = ?", (report_date,)).fetchone()
    return dict(row) if row is not None else None


def daily_upsert(data: dict, updated_by: str) -> tuple:
    """Nhập báo cáo theo ngày; ngày đã tồn tại thì cập nhật. Trả về (entry, created)."""
    now = _utcnow()
    values = [data.get(c, 0 if c != "note" else "") for c in DAILY_COLUMNS]
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM daily_reports WHERE date = ?", (data["date"],)
        ).fetchone()
        if existing is not None:
            conn.execute(
                f"UPDATE daily_reports SET {', '.join(f'{c} = ?' for c in DAILY_COLUMNS)},"
                " updated_by = ?, updated_at = ? WHERE id = ?",
                (*values, updated_by, now, existing["id"]),
            )
            entry_id = existing["id"]
            created = False
        else:
            cols = ", ".join(["date", *DAILY_COLUMNS, "updated_by", "updated_at"])
            placeholders = ", ".join("?" for _ in range(len(DAILY_COLUMNS) + 3))
            cur = conn.execute(
                f"INSERT INTO daily_reports ({cols}) VALUES ({placeholders})",
                (data["date"], *values, updated_by, now),
            )
            entry_id = cur.lastrowid
            created = True
        row = conn.execute("SELECT * FROM daily_reports WHERE id = ?", (entry_id,)).fetchone()
    return dict(row), created


def daily_delete(report_date: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM daily_reports WHERE date = ?", (report_date,))
        return cur.rowcount > 0


def gmv_seed_defaults() -> int:
    """Tạo sẵn 5 sản phẩm rỗng khi bảng đang trống hoàn toàn.

    Không seed lại khi đã có dữ liệu (tránh trùng). Trả về số sản phẩm đã tạo.
    """
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM gmv_products").fetchone()
        if row["c"] > 0:
            return 0
        now = _utcnow()
        for name in GMV_SEED_PRODUCTS:
            conn.execute(
                "INSERT OR IGNORE INTO gmv_products (name, created_at) VALUES (?, ?)",
                (name, now),
            )
    return len(GMV_SEED_PRODUCTS)
