"""Đo số câu SQL mỗi trang (nội bộ, KHÔNG giao user).

Mỗi `conn.execute()` qua _TursoConnection ≈ 1 vòng hỏi DB qua mạng về Turso
Tokyo = thời gian chờ chính trên Render. Dùng libsql file backend để chạy
đúng đường wrapper Turso (pattern từ tests/test_turso_wrapper.py).

Chạy: cd APYKO-AGENCY-DEPLOY && .venv/bin/python hidden_files/perf_count.py
"""

import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

_TMP = tempfile.mkdtemp(prefix="perf_")
os.environ["TURSO_DATABASE_URL"] = f"file:{_TMP}/perf.db"
os.environ["TURSO_AUTH_TOKEN"] = "x"
os.environ["DATABASE_PATH"] = f"{_TMP}/fallback.db"
os.environ["SECRET_KEY"] = "perf-secret-key"
os.environ["DISABLE_BACKGROUND"] = "1"

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_DIR)

from fastapi.testclient import TestClient  # noqa: E402

import app.auth as auth  # noqa: E402
import app.database as db  # noqa: E402
from app import checklist  # noqa: E402

db.init_db()

# ---------------- seed dữ liệu trạng thái ổn định ----------------
OWNER = {
    "username": "perf_owner",
    "display_name": "Chủ Shop",
    "password_hash": auth.hash_password("PerfPass1"),
    "is_owner": 1,
    "is_active": 1,
    "must_activate": 0,
    "activation_code": "",
    "can_view_products": 1,
    "can_add_edit_products": 1,
    "can_delete_products": 1,
    "can_view_uni": 1,
    "can_checklist_leader": 1,
    "can_checklist_admin": 1,
}
owner_id = db.create_user(OWNER)
staff_id = db.create_user(
    {**OWNER, "username": "perf_staff", "display_name": "Nhân viên", "is_owner": 0,
     "can_checklist_leader": 0, "can_checklist_admin": 0}
)
db.create_session(
    "perf-token",
    owner_id,
    (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
)

TODAY = checklist.today_str()
# Báo cáo ngày: 8 ngày gần nhất
for back in range(8):
    d = (datetime.now(timezone.utc) - timedelta(days=back)).date().isoformat()
    db.daily_upsert(
        {
            "date": d, "rev_product": 1000000, "rev_live": 500000, "rev_video": 300000,
            "rev_aff_link": 100000, "rev_affiliate": 50000, "ad_gmv": 800000,
            "ad_cost": 200000, "aov": 120000, "conv_rate": 3.5, "note": "",
        },
        "perf",
    )
# GMV: 2 sản phẩm × 10 ngày
for pid in (db.gmv_create_product("Sản phẩm A"), db.gmv_create_product("Sản phẩm B")):
    for back in range(10):
        d = (datetime.now(timezone.utc) - timedelta(days=back)).date().isoformat()
        db.gmv_upsert_entry(
            pid,
            {"date": d, "views": 1000, "clicks": 50, "conversions": 5,
             "revenue_rm": 100.0, "ad_cost": 30.0, "action_note": ""},
            "perf",
        )
# Checklist hôm nay: đã tạo sẵn (trạng thái ổn định sau deploy)
checklist.generate_for_date(TODAY)
items = db.cl_item_list(TODAY)
db.cl_item_update(items[0]["id"], {"status": "done", "completed_by": "perf"})

# ---------------- bộ đếm ----------------
counters = {"queries": 0, "conns": 0}
_real_get_conn = db.get_conn


class _CountingConn:
    def __init__(self, inner):
        self._inner = inner

    def execute(self, sql, params=()):
        counters["queries"] += 1
        return self._inner.execute(sql, params)

    def executescript(self, script):
        counters["scripts"] = counters.get("scripts", 0) + 1
        return self._inner.executescript(script)

    def commit(self):
        return self._inner.commit()

    def rollback(self):
        return self._inner.rollback()

    def close(self):
        return self._inner.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._inner.__exit__(exc_type, exc, tb)


def _counting_get_conn():
    counters["conns"] += 1
    return _CountingConn(_real_get_conn())


db.get_conn = _counting_get_conn

# ---------------- đo ----------------
client = TestClient(__import__("app.main", fromlist=["app"]).app)
client.cookies.set("apyko_session", "perf-token")

PAGES = ["/", "/ceo", "/ceo", "/checklist", "/checklist/board", "/gmv", "/bao-cao",
         "/thong-bao", "/uni"]


def measure(path):
    counters["queries"] = 0
    counters["conns"] = 0
    t0 = time.perf_counter()
    r = client.get(path)
    dt = (time.perf_counter() - t0) * 1000
    return r.status_code, counters["queries"], counters["conns"], dt


def run_pass(title):
    print(f"\n== {title} ==")
    print(f"{'trang':<20} {'http':<5} {'queries':<8} {'conns':<6} {'ms(backend file)'}")
    print("-" * 60)
    for i, path in enumerate(PAGES):
        status, q, c, dt = measure(path)
        label = path if PAGES.count(path) == 1 else f"{path}#{PAGES[:i].count(path)+1}"
        print(f"{label:<20} {status:<5} {q:<8} {c:<6} {dt:>7.1f}")


# Lượt 1: throttle lưới an toàn + cache CEO còn lạnh.
# Lượt 2 (ngay sau): trạng thái ổn định — throttle/cache đã ấm.
run_pass("PASS 1")
run_pass("PASS 2")
