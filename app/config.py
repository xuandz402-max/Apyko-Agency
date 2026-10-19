"""Cấu hình qua biến môi trường. Không hardcode secret."""

import os

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATABASE_PATH = os.environ.get("DATABASE_PATH") or os.path.join(
    _PROJECT_DIR, "data", "apyko_agency.db"
)
LESSONS_DIR = os.environ.get("LESSONS_DIR") or os.path.join(_PROJECT_DIR, "lessons")

SECRET_KEY = os.environ.get("SECRET_KEY", "")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "30"))

OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "").strip()
OWNER_PASSWORD = os.environ.get("OWNER_PASSWORD", "")

# Database online (Turso/libsql) — chống mất dữ liệu khi Render deploy lại.
# Đủ cả 2 biến -> dùng Turso remote; thiếu -> fallback SQLite file local.
TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")

APP_NAME = "Apyko Agency"
