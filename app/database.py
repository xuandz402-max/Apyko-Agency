"""Tầng lưu trữ: SQLite local (stdlib sqlite3) hoặc Turso (libsql) trên cloud.

Chọn backend qua biến môi trường TURSO_DATABASE_URL + TURSO_AUTH_TOKEN (xem config):
- đủ cả 2  -> Turso remote qua libsql (dữ liệu không mất khi Render deploy lại)
- thiếu     -> SQLite file local như cũ (dev/test offline)

Mọi truy vấn đi qua get_conn(); code nghiệp vụ không đổi.
"""

import logging
import os
import sqlite3
import threading
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
    "can_checklist_leader",
    "can_checklist_admin",
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
CREATE TABLE IF NOT EXISTS shops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checklist_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0,
    due_time TEXT NOT NULL DEFAULT '09:00',
    assignee_id INTEGER,
    shop_id INTEGER,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checklist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    template_id INTEGER,
    group_name TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0,
    due_time TEXT NOT NULL DEFAULT '09:00',
    assignee_id INTEGER,
    shop_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    note TEXT DEFAULT '',
    completed_by TEXT DEFAULT '',
    completed_at TEXT DEFAULT '',
    due_notified_at TEXT,
    last_reminder_at TEXT,
    reminder_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (date, template_id)
);
CREATE TABLE IF NOT EXISTS checklist_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    item_id INTEGER,
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    link TEXT NOT NULL DEFAULT '',
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gmv_alert_log (
    dedupe_key TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pricing_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category_code TEXT DEFAULT '',
    category_fee_rate REAL NOT NULL DEFAULT 0,
    cost_price INTEGER NOT NULL DEFAULT 0,
    selling_price INTEGER NOT NULL DEFAULT 0,
    pay_rate REAL NOT NULL DEFAULT 0,
    voucher_rate REAL NOT NULL DEFAULT 0,
    voucher_cap INTEGER NOT NULL DEFAULT 0,
    affiliate_rate REAL NOT NULL DEFAULT 0,
    pi_ship INTEGER NOT NULL DEFAULT 0,
    infra_fee INTEGER NOT NULL DEFAULT 0,
    ads_rate REAL NOT NULL DEFAULT 0,
    tax_rate REAL NOT NULL DEFAULT 0,
    created_by TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pricing_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS cskh_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    updated_by TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);
"""

# Migration cộng thêm cho các DB đã tồn tại trước module Daily Checklist:
# 2 cột quyền mới trên bảng users (ALTER TABLE chạy khi cột còn thiếu).
_USER_MIGRATION_COLUMNS = [
    ("can_checklist_leader", "INTEGER NOT NULL DEFAULT 0"),
    ("can_checklist_admin", "INTEGER NOT NULL DEFAULT 0"),
]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


log = logging.getLogger("apyko.db")


class _Row:
    """Hàng kết quả tương thích sqlite3.Row cho backend Turso/libsql.

    libsql trả về tuple thuần; wrapper này hỗ trợ row["col"], row[0],
    dict(row), len(row), keys() và iteration như sqlite3.Row.
    """

    __slots__ = ("_keys", "_map", "_values")

    def __init__(self, keys, values):
        self._keys = list(keys)
        self._values = tuple(values)
        self._map = dict(zip(self._keys, self._values, strict=True))

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return self._map[key]
            except KeyError:
                # libsql/Turso có thể chuẩn hoá HOA tên cột là từ khóa
                # (ví dụ "key" -> "KEY"); thử khớp không phân biệt hoa/thường
                # trước khi bỏ cuộc. Khớp chính xác vẫn được ưu tiên.
                lowered = key.lower()
                for k, v in self._map.items():
                    if k.lower() == lowered:
                        return v
                raise
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return list(self._keys)

    def __repr__(self):
        return f"_Row({self._map!r})"


def _is_libsql_integrity_error(exc: BaseException) -> bool:
    """libsql 0.1.x ném ValueError thuần cho lỗi constraint của SQLite core."""
    return isinstance(exc, ValueError) and "constraint failed" in str(exc).lower()


class _TursoCursor:
    """Cursor bọc libsql: fetch trả về _Row thay vì tuple thuần."""

    def __init__(self, raw_cursor):
        self._cur = raw_cursor

    @property
    def description(self):
        return self._cur.description

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    def _keys(self):
        desc = self._cur.description
        return [d[0] for d in desc] if desc else []

    def fetchone(self):
        row = self._cur.fetchone()
        return None if row is None else _Row(self._keys(), row)

    def fetchall(self):
        keys = self._keys()
        return [_Row(keys, r) for r in self._cur.fetchall()]

    def __iter__(self):
        keys = self._keys()
        for r in self._cur:
            yield _Row(keys, r)


class _TursoConnection:
    """Connection bọc libsql cho Turso remote, API giống sqlite3.Connection.

    - Lỗi constraint của libsql (ValueError "... constraint failed ...") được
      chuẩn hoá thành sqlite3.IntegrityError ngay tại biên, nên code gọi
      (VD: routes.py bắt sqlite3.IntegrityError) hoạt động y hệt cả 2 backend.
    - Khối `with` commit khi hết khối không lỗi, rollback khi có lỗi (như sqlite3).
    """

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, sql, params=()):
        try:
            raw_cur = self._conn.execute(sql, params)
        except ValueError as e:
            if _is_libsql_integrity_error(e):
                raise sqlite3.IntegrityError(str(e)) from e
            raise
        return _TursoCursor(raw_cur)

    def executescript(self, script):
        return self._conn.executescript(script)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # Như sqlite3: hết khối with mà không lỗi -> commit, có lỗi -> rollback.
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        return False


def _turso_enabled() -> bool:
    return bool(config.TURSO_DATABASE_URL and config.TURSO_AUTH_TOKEN)


# Cache raw libsql connection theo thread. Mỗi lần libsql.connect() là một
# handshake TLS + Hrana về Tokyo (~0.5-1s), trong khi một request gọi
# get_conn() nhiều lần -> trang chậm vài giây. FastAPI chạy sync routes trên
# threadpool nên 1 raw connection / thread là an toàn (libsql thread-safe);
# _TursoConnection.__exit__ chỉ commit/rollback, không close, nên dùng chung
# raw connection không đổi ngữ nghĩa. SQLite local mở file rất rẻ -> không cache.
_turso_tls = threading.local()


def _new_turso_raw():
    """Tạo raw libsql connection mới + PRAGMA foreign_keys (chỉ lúc tạo mới)."""
    import libsql

    raw = libsql.connect(config.TURSO_DATABASE_URL, auth_token=config.TURSO_AUTH_TOKEN)
    try:
        raw.execute("PRAGMA foreign_keys = ON")
    except Exception as e:  # remote có thể không hỗ trợ PRAGMA này
        log.warning("Turso: bỏ qua PRAGMA foreign_keys (%s)", e)
    return raw


def _turso_raw():
    """Raw connection dùng chung của thread hiện tại; chết thì kết nối lại.

    Kiểm tra sức khỏe bằng SELECT 1 mỗi lần lấy: rẻ hơn handshake mới rất
    nhiều, và bắt được trường hợp server đóng connection idle lâu.
    """
    raw = getattr(_turso_tls, "raw", None)
    if raw is not None:
        try:
            raw.execute("SELECT 1")
        except Exception as e:
            log.warning("Turso: connection cũ lỗi (%s), kết nối lại", e)
            _turso_tls.raw = None
        else:
            return raw
    raw = _new_turso_raw()
    _turso_tls.raw = raw
    return raw


def get_conn() -> "sqlite3.Connection | _TursoConnection":
    """Kết nối DB: Turso (libsql) nếu đủ 2 biến môi trường, ngược lại SQLite local."""
    if _turso_enabled():
        return _TursoConnection(_turso_raw())
    parent = os.path.dirname(config.DATABASE_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate_users_columns(conn) -> None:
    """Thêm cột quyền checklist vào bảng users của DB cũ (idempotent)."""
    rows = conn.execute("PRAGMA table_info(users)").fetchall()
    existing = {r["name"] for r in rows}
    for col, ddl in _USER_MIGRATION_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)
        _migrate_users_columns(conn)
    pricing_seed_settings()
    cskh_seed_defaults()
    # Import trễ để tránh vòng lặp module (checklist.py dùng database.py).
    from . import checklist

    checklist.seed_defaults()


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


def gmv_all_entries() -> list:
    """Toàn bộ entry GMV trong 1 query, sắp theo product rồi ngày tăng dần.

    Dùng cho trang tổng hợp (Dashboard CEO) để khỏi query theo từng sản
    phẩm: thứ tự trong mỗi sản phẩm khớp gmv_list_entries (date ASC).
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM gmv_entries ORDER BY product_id ASC, date ASC"
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


# --------------------------- daily checklist ------------------------------
# CRUD thuần cho module Daily Checklist. Logic nghiệp vụ (tạo việc theo
# ngày, trạng thái hiển thị, nhắc hạn, thống kê) nằm ở app/checklist.py.


def shop_list() -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM shops ORDER BY id ASC").fetchall()
    return [dict(r) for r in rows]


def shop_get(shop_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
    return dict(row) if row is not None else None


def shop_create(name: str) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("Tên shop không được trống.")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO shops (name, created_at) VALUES (?, ?)", (name, _utcnow())
        )
        return cur.lastrowid


def shop_rename(shop_id: int, name: str) -> dict | None:
    name = (name or "").strip()
    if not name:
        raise ValueError("Tên shop không được trống.")
    with get_conn() as conn:
        cur = conn.execute("UPDATE shops SET name = ? WHERE id = ?", (name, shop_id))
        if cur.rowcount == 0:
            return None
    return shop_get(shop_id)


def shop_ref_count(shop_id: int) -> int:
    """Số template/item đang tham chiếu shop (để chặn xóa shop đang dùng)."""
    with get_conn() as conn:
        a = conn.execute(
            "SELECT COUNT(*) AS c FROM checklist_templates WHERE shop_id = ?", (shop_id,)
        ).fetchone()
        b = conn.execute(
            "SELECT COUNT(*) AS c FROM checklist_items WHERE shop_id = ?", (shop_id,)
        ).fetchone()
    return (a["c"] or 0) + (b["c"] or 0)


def shop_delete(shop_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM shops WHERE id = ?", (shop_id,))
        return cur.rowcount > 0


CL_TEMPLATE_COLUMNS = [
    "group_name",
    "title",
    "sort",
    "due_time",
    "assignee_id",
    "shop_id",
    "is_active",
]


def cl_template_list() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM checklist_templates ORDER BY sort ASC, id ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def cl_template_get(template_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM checklist_templates WHERE id = ?", (template_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def cl_template_create(d: dict) -> int:
    data = {k: v for k, v in d.items() if k in CL_TEMPLATE_COLUMNS}
    data["created_at"] = _utcnow()
    data["updated_at"] = _utcnow()
    cols = list(data.keys())
    placeholders = ", ".join("?" for _ in cols)
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO checklist_templates ({', '.join(cols)}) VALUES ({placeholders})",
            [data[c] for c in cols],
        )
        return cur.lastrowid


def cl_template_update(template_id: int, d: dict) -> dict | None:
    data = {k: v for k, v in d.items() if k in CL_TEMPLATE_COLUMNS}
    if not data:
        return cl_template_get(template_id)
    data["updated_at"] = _utcnow()
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE checklist_templates SET {', '.join(f'{k} = ?' for k in data)}"
            " WHERE id = ?",
            [*data.values(), template_id],
        )
        if cur.rowcount == 0:
            return None
    return cl_template_get(template_id)


def cl_template_delete(template_id: int) -> bool:
    """Xóa mẫu việc; các item đã tạo từ mẫu này được giữ nguyên."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM checklist_templates WHERE id = ?", (template_id,))
        return cur.rowcount > 0


def cl_item_list(
    date_str: str,
    assignee_id: int | None = None,
    shop_id: int | None = None,
    status: str | None = None,
) -> list:
    clauses = ["date = ?"]
    params: list = [date_str]
    if assignee_id is not None:
        clauses.append("assignee_id = ?")
        params.append(assignee_id)
    if shop_id is not None:
        clauses.append("shop_id = ?")
        params.append(shop_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM checklist_items WHERE "
            + " AND ".join(clauses)
            + " ORDER BY sort ASC, id ASC",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def cl_item_get(item_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM checklist_items WHERE id = ?", (item_id,)).fetchone()
    return dict(row) if row is not None else None


def cl_item_count(date_str: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM checklist_items WHERE date = ?", (date_str,)
        ).fetchone()
    return row["c"]


CL_ITEM_UPDATE_COLUMNS = [
    "status",
    "note",
    "completed_by",
    "completed_at",
    "assignee_id",
    "shop_id",
    "due_notified_at",
    "last_reminder_at",
    "reminder_count",
]


def cl_item_update(item_id: int, d: dict) -> dict | None:
    data = {k: v for k, v in d.items() if k in CL_ITEM_UPDATE_COLUMNS}
    if not data:
        return cl_item_get(item_id)
    data["updated_at"] = _utcnow()
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE checklist_items SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
            [*data.values(), item_id],
        )
        if cur.rowcount == 0:
            return None
    return cl_item_get(item_id)


def cl_setting_get_all() -> dict:
    with get_conn() as conn:
        # Alias bắt buộc: libsql/Turso trả tên cột "key" thành "KEY" (từ khóa)
        # nên đọc r["key"] sẽ KeyError trên Turso dù SQLite local chạy đúng.
        rows = conn.execute(
            "SELECT key AS setting_key, value AS setting_value"
            " FROM checklist_settings"
        ).fetchall()
    return {r["setting_key"]: r["setting_value"] for r in rows}


def cl_setting_set(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO checklist_settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = ?",
            (key, value, value),
        )


def notif_create(user_id: int, item_id, title: str, body: str, link: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO notifications (user_id, item_id, title, body, link, is_read,"
            " created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (user_id, item_id, title, body, link, _utcnow()),
        )
        return cur.lastrowid


def notif_list(user_id: int, limit: int = 100) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def notif_get(notif_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM notifications WHERE id = ?", (notif_id,)).fetchone()
    return dict(row) if row is not None else None


def notif_unread_count(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0",
            (user_id,),
        ).fetchone()
    return row["c"]


def notif_mark_read(notif_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notif_id,))
        return cur.rowcount > 0


def notif_mark_all_read(user_id: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0",
            (user_id,),
        )
        return cur.rowcount


# ------------------------------ định giá sản phẩm ---------------------------
# Các % trong pricing_items / pricing_settings lưu dạng THẬP PHÂN như file
# Excel gốc (0.06 = 6%); chuyển đổi % người dùng <-> thập phân nằm trọn ở
# app/pricing.py (validate_pricing_payload / settings_to_user_view).

PRICING_ITEM_COLUMNS = [
    "id",
    "name",
    "category_code",
    "category_fee_rate",
    "cost_price",
    "selling_price",
    "pay_rate",
    "voucher_rate",
    "voucher_cap",
    "affiliate_rate",
    "pi_ship",
    "infra_fee",
    "ads_rate",
    "tax_rate",
    "created_by",
    "created_at",
    "updated_at",
]

# Tham số mặc định từ sheet "Tham số mặc định" của file "Dự tính giá bán":
# phí thanh toán 6%, Voucher Xtra 0% (trần 50.000đ), Affiliate 0%,
# Pi Ship 2.700đ/đơn, hạ tầng 3.000đ/đơn, thuế khấu trừ 1,5%.
PRICING_SETTING_DEFAULTS = {
    "pay_rate": "0.06",
    "voucher_rate": "0.0",
    "voucher_cap": "50000",
    "affiliate_rate": "0.0",
    "pi_ship": "2700",
    "infra_fee": "3000",
    "tax_rate": "0.015",
}


def pricing_seed_settings() -> None:
    """Gieo 7 tham số mặc định nếu bảng pricing_settings còn thiếu (idempotent)."""
    with get_conn() as conn:
        for key, value in PRICING_SETTING_DEFAULTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO pricing_settings (key, value) VALUES (?, ?)",
                (key, value),
            )


def pricing_setting_get_all() -> dict:
    with get_conn() as conn:
        # Alias bắt buộc như cl_setting_get_all: libsql/Turso trả tên cột
        # "key" thành "KEY" nên đọc r["key"] sẽ KeyError trên Turso.
        rows = conn.execute(
            "SELECT key AS setting_key, value AS setting_value FROM pricing_settings"
        ).fetchall()
    return {r["setting_key"]: r["setting_value"] for r in rows}


def pricing_setting_set(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO pricing_settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = ?",
            (key, value, value),
        )


def _clean_pricing_item(d: dict, for_insert: bool = False) -> dict:
    data = {k: v for k, v in d.items() if k in PRICING_ITEM_COLUMNS and k != "id"}
    if not for_insert:
        # Người tạo + thời điểm tạo không đổi khi sửa.
        data.pop("created_by", None)
        data.pop("created_at", None)
    data["updated_at"] = _utcnow()
    return data


def pricing_item_create(d: dict, created_by: str = "") -> int:
    data = _clean_pricing_item(d, for_insert=True)
    data["created_by"] = created_by
    data["created_at"] = _utcnow()
    cols = list(data.keys())
    placeholders = ", ".join("?" for _ in cols)
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO pricing_items ({', '.join(cols)}) VALUES ({placeholders})",
            [data[c] for c in cols],
        )
        return cur.lastrowid


def pricing_item_get(item_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM pricing_items WHERE id = ?", (item_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def pricing_item_list() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pricing_items ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def pricing_item_update(item_id: int, d: dict) -> dict | None:
    data = _clean_pricing_item(d)
    if not data:
        return pricing_item_get(item_id)
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE pricing_items SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
            [*data.values(), item_id],
        )
        if cur.rowcount == 0:
            return None
    return pricing_item_get(item_id)


def pricing_item_delete(item_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM pricing_items WHERE id = ?", (item_id,))
        return cur.rowcount > 0


# ------------------------------ mẫu trả lời CSKH ------------------------------
# Thư viện mẫu chăm sóc khách hàng: nhân viên sao chép nhanh khi chat với
# khách. Biến giữ chỗ trong nội dung: {ten_khach}, {ma_don}, {san_pham}
# (người dùng tự thay khi dán sang kênh chat — app không tự điền).

CSKH_COLUMNS = ["id", "title", "category", "content", "updated_by", "updated_at"]

# 6 mẫu khởi đầu TRUNG TÍNH — chỉ gieo khi bảng trống, chủ shop sửa/xóa tùy ý.
CSKH_SEED_TEMPLATES = [
    {
        "title": "Chào khách, hỏi nhu cầu",
        "category": "Chào hỏi",
        "content": (
            "Chào {ten_khach}, shop cảm ơn bạn đã quan tâm đến {san_pham}. "
            "Bạn cần shop tư vấn thêm điều gì ạ?"
        ),
    },
    {
        "title": "Xin mã đơn để kiểm tra",
        "category": "Tra cứu đơn",
        "content": (
            "Dạ {ten_khach} cho shop xin mã đơn hàng để shop kiểm tra "
            "tình trạng đơn cho bạn nhé."
        ),
    },
    {
        "title": "Hẹn giao lại",
        "category": "Vận chuyển",
        "content": (
            "Dạ đơn {ma_don} của {ten_khach} chưa giao thành công, shop đã "
            "hẹn đơn vị vận chuyển giao lại cho bạn. Bạn để ý điện thoại "
            "giúp shop nhé."
        ),
    },
    {
        "title": "Hướng dẫn đổi / trả hàng",
        "category": "Đổi trả / bảo hành",
        "content": (
            "Dạ shop hỗ trợ đổi/trả cho đơn {ma_don} ạ. {ten_khach} gửi giúp "
            "shop hình ảnh hoặc video sản phẩm lúc nhận hàng để shop xử lý "
            "nhanh nhất cho bạn nhé."
        ),
    },
    {
        "title": "Cảm ơn sau khi mua",
        "category": "Sau mua",
        "content": (
            "Shop cảm ơn {ten_khach} đã ủng hộ {san_pham}. Chúc bạn dùng "
            "sản phẩm thật hài lòng ạ!"
        ),
    },
    {
        "title": "Xin đánh giá 5 sao",
        "category": "Đánh giá",
        "content": (
            "Dạ nếu {ten_khach} hài lòng với {san_pham}, bạn cho shop xin "
            "đánh giá 5 sao để shop có thêm động lực nhé. Shop cảm ơn bạn "
            "nhiều ạ!"
        ),
    },
]


def cskh_seed_defaults() -> int:
    """Gieo 6 mẫu CSKH khởi đầu CHỈ khi bảng đang trống. Trả số mẫu đã gieo."""
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM cskh_templates").fetchone()
        if row["c"]:
            return 0
        now = _utcnow()
        for tpl in CSKH_SEED_TEMPLATES:
            conn.execute(
                "INSERT INTO cskh_templates (title, category, content, updated_by,"
                " updated_at) VALUES (?, ?, ?, '', ?)",
                (tpl["title"], tpl["category"], tpl["content"], now),
            )
        return len(CSKH_SEED_TEMPLATES)


def cskh_list(q: str | None = None) -> list:
    """Danh sách mẫu CSKH; `q` lọc theo tiêu đề/danh mục/nội dung (LIKE)."""
    sql = "SELECT * FROM cskh_templates"
    params: list = []
    if q and q.strip():
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        sql += (
            " WHERE (title LIKE ? ESCAPE '\\' OR category LIKE ? ESCAPE '\\'"
            " OR content LIKE ? ESCAPE '\\')"
        )
        params.extend([like, like, like])
    sql += " ORDER BY category ASC, title ASC, id ASC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def cskh_get(template_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM cskh_templates WHERE id = ?", (template_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def cskh_upsert(d: dict, updated_by: str = "") -> int:
    """Thêm mới hoặc cập nhật mẫu CSKH (theo "id" nếu có). Trả về id của mẫu."""
    data = {k: v for k, v in d.items() if k in CSKH_COLUMNS and k != "id"}
    data["updated_by"] = updated_by
    data["updated_at"] = _utcnow()
    template_id = d.get("id")
    with get_conn() as conn:
        if template_id:
            cur = conn.execute(
                f"UPDATE cskh_templates SET {', '.join(f'{k} = ?' for k in data)}"
                " WHERE id = ?",
                [*data.values(), template_id],
            )
            if cur.rowcount:
                return int(template_id)
        cols = list(data.keys())
        placeholders = ", ".join("?" for _ in cols)
        cur = conn.execute(
            f"INSERT INTO cskh_templates ({', '.join(cols)}) VALUES ({placeholders})",
            [data[c] for c in cols],
        )
        return cur.lastrowid


def cskh_delete(template_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM cskh_templates WHERE id = ?", (template_id,))
        return cur.rowcount > 0
