"""Apyko Agency — FastAPI app.

Chạy: uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
Cấu hình qua biến môi trường, xem app/config.py và .env.example.
"""

import logging
import os
import threading
import time

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware

from . import auth, config, lessons
from . import database as db
from .routes import router

log = logging.getLogger("apyko")

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _StaticCacheMiddleware(BaseHTTPMiddleware):
    """Cho trình duyệt cache file tĩnh 10 phút (chuyển trang không tải lại CSS).

    max-age ngắn có chủ đích: tránh dính CSS cũ sau khi deploy (đã từng có
    sự cố giao diện lỗi vì cache trình duyệt giữ bản quá lâu). Chỉ áp dụng
    cho /static, KHÔNG áp dụng cho trang HTML.
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=600"
        return response


app = FastAPI(title=config.APP_NAME, docs_url="/docs", redoc_url=None)
# Nén gzip response >= 1KB: giảm băng thông HTML/JSON trên đường Render free.
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(_StaticCacheMiddleware)
app.mount("/static", StaticFiles(directory=os.path.join(_PROJECT_DIR, "static")), name="static")
app.include_router(router)


def _bootstrap_owner_from_env() -> None:
    """Tạo owner từ OWNER_USERNAME/OWNER_PASSWORD nếu có và chưa có user nào."""
    if db.count_users() > 0:
        return
    if not (config.OWNER_USERNAME and config.OWNER_PASSWORD):
        log.warning("Chưa có tài khoản nào. Mở /setup trên trình duyệt để tạo chủ sở hữu.")
        return
    if len(config.OWNER_PASSWORD) < 8:
        log.warning("OWNER_PASSWORD ngắn hơn 8 ký tự — bỏ qua, hãy dùng /setup.")
        return
    db.create_user(
        {
            "username": config.OWNER_USERNAME,
            "display_name": config.OWNER_USERNAME,
            "password_hash": auth.hash_password(config.OWNER_PASSWORD),
            "is_owner": 1,
            "is_active": 1,
            "must_activate": 0,
            "activation_code": "",
            "can_view_products": 1,
            "can_add_edit_products": 1,
            "can_delete_products": 1,
            "can_view_uni": 1,
            "can_view_daily": 1,
            "can_view_pricing": 1,
            "can_view_gmv": 1,
            "can_view_affiliate": 1,
            "can_view_tiktok": 1,
            "can_view_cskh": 1,
            "can_view_accounts": 1,
            "can_view_orders": 1,
            "can_view_order_finance": 1,
            "can_import_orders": 1,
            "can_export_orders": 1,
            "can_view_buyer_pii": 1,
        }
    )
    from . import sidebar as _sidebar

    _owner = db.get_user_by_username(config.OWNER_USERNAME)
    if _owner:
        db.sidebar_set_grants(_owner["id"], _sidebar.all_ids())
    log.warning("Đã tạo tài khoản chủ sở hữu '%s' từ biến môi trường.", config.OWNER_USERNAME)


_BG_THREAD_STARTED = False


def _checklist_tick() -> None:
    """Một vòng tạo checklist ngày + gửi nhắc hạn (idempotent, chống trùng)."""
    try:
        from . import checklist

        now = checklist.now_vn()
        made = checklist.generate_for_date(now.date().isoformat())
        sent = checklist.process_reminders(now)
        if made or sent:
            log.info("Checklist nền: tạo mới %d việc, gửi %d nhắc.", made, sent)
    except Exception:
        log.exception("Lỗi vòng lặp nền Daily Checklist")
    # Cảnh báo GMV Max chạy cùng nhịp tick 60 giây (dedupe theo ngày trong
    # gmv_charts nên không spam); lỗi ở đây không được làm hỏng checklist.
    try:
        from . import checklist, gmv_charts

        pushed = gmv_charts.sync_gmv_alert_notifications(checklist.today_str())
        if pushed:
            log.info("GMV nền: đã đẩy %d thông báo cảnh báo.", pushed)
    except Exception:
        log.exception("Lỗi vòng lặp nền cảnh báo GMV")
    # Sao lưu tự động 1 lần/ngày cho bản chạy máy tính (DB local); Turso tự
    # lo sao lưu nên maybe_daily_backup tự trả None. Lỗi không làm hỏng tick.
    try:
        from . import backup

        made_backup = backup.maybe_daily_backup()
        if made_backup:
            log.info("Sao lưu nền: đã tạo bản %s", made_backup)
    except Exception:
        log.exception("Lỗi vòng lặp nền sao lưu tự động")


def _checklist_loop() -> None:
    while True:
        _checklist_tick()
        time.sleep(60)


def _start_background() -> None:
    """Scheduler nền cho Daily Checklist. Tắt bằng DISABLE_BACKGROUND=1."""
    global _BG_THREAD_STARTED
    if _BG_THREAD_STARTED:
        return
    if os.environ.get("DISABLE_BACKGROUND") == "1":
        log.info("DISABLE_BACKGROUND=1 — bỏ qua scheduler nền Daily Checklist.")
        return
    _BG_THREAD_STARTED = True
    thread = threading.Thread(
        target=_checklist_loop, name="checklist-bg", daemon=True
    )
    thread.start()
    log.warning("Đã bật scheduler nền Daily Checklist (tick mỗi 60 giây).")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    seeded = db.gmv_seed_defaults()
    if seeded:
        log.warning("GMV Max: đã tạo sẵn %d sản phẩm (bảng đang trống).", seeded)
    _bootstrap_owner_from_env()
    _start_background()
    n = len(lessons.list_lessons())
    log.warning("Apyko Agency sẵn sàng — %d bài học Apyko Uni, DB: %s", n, config.DATABASE_PATH)
    if not config.SECRET_KEY:
        log.warning("SECRET_KEY chưa đặt — hãy đặt biến môi trường SECRET_KEY khi deploy.")
