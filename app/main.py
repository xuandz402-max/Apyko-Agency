"""Apyko Agency — FastAPI app.

Chạy: uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
Cấu hình qua biến môi trường, xem app/config.py và .env.example.
"""

import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import auth, config, lessons
from . import database as db
from .routes import router

log = logging.getLogger("apyko")

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = FastAPI(title=config.APP_NAME, docs_url="/docs", redoc_url=None)
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
        }
    )
    log.warning("Đã tạo tài khoản chủ sở hữu '%s' từ biến môi trường.", config.OWNER_USERNAME)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    seeded = db.gmv_seed_defaults()
    if seeded:
        log.warning("GMV Max: đã tạo sẵn %d sản phẩm (bảng đang trống).", seeded)
    _bootstrap_owner_from_env()
    n = len(lessons.list_lessons())
    log.warning("Apyko Agency sẵn sàng — %d bài học Apyko Uni, DB: %s", n, config.DATABASE_PATH)
    if not config.SECRET_KEY:
        log.warning("SECRET_KEY chưa đặt — hãy đặt biến môi trường SECRET_KEY khi deploy.")
