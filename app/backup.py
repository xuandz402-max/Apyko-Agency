"""Sao lưu + khôi phục dữ liệu — CHỈ cho bản chạy máy tính (DB SQLite local).

- Bản sao tạo bằng sqlite3 backup API (bản sao NHẤT QUÁN ngay cả khi app
  đang chạy), lưu ở thư mục `backups/` cạnh thư mục chứa file DB
  (DB ở <project>/data/*.db thì backups là <project>/backups; trường hợp
  khác thì nằm trong chính thư mục chứa DB).
- Giữ tối đa 30 bản mới nhất, bản cũ hơn tự bị dọn sau mỗi lần tạo mới.
- Backend Turso (cloud): sao lưu do Turso quản lý -> các hàm ở đây trả
  None / báo không áp dụng, giao diện hiện rõ trạng thái.
- Khôi phục: validate file (đúng thư mục, đúng SQLite, đủ bảng cốt lõi)
  -> tự sao lưu bản hiện tại (reason "pre-restore") -> chép đè file DB.
  Sau khi khôi phục PHẢI tắt app mở lại để mọi kết nối dùng dữ liệu mới.
"""

import logging
import os
import re
import shutil
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config

log = logging.getLogger("apyko.backup")

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
KEEP_BACKUPS = 30
CORE_TABLES = {"users", "daily_reports", "gmv_products"}
_NAME_RE = re.compile(r"^apyko-\d{8}-\d{6}-[a-z0-9-]+\.db$")


def _turso_enabled() -> bool:
    return bool(config.TURSO_DATABASE_URL and config.TURSO_AUTH_TOKEN)


def is_local() -> bool:
    """True khi app đang dùng SQLite file local (sao lưu khả dụng)."""
    return not _turso_enabled()


def backups_dir() -> str:
    """Thư mục chứa các bản sao lưu.

    DATABASE_PATH chuẩn là <project>/data/apyko_agency.db -> backups nằm ở
    <project>/backups (cạnh thư mục data). DATABASE_PATH tùy biến khác
    (VD test) -> <thư mục chứa DB>/backups cho gọn và cô lập.
    """
    db_dir = os.path.dirname(os.path.abspath(config.DATABASE_PATH))
    if os.path.basename(db_dir) == "data":
        return os.path.join(os.path.dirname(db_dir), "backups")
    return os.path.join(db_dir, "backups")


def _clean_reason(reason: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", (reason or "manual").lower()).strip("-")
    return cleaned or "manual"


def _prune() -> None:
    """Dọn thư mục backups: chỉ giữ KEEP_BACKUPS bản mới nhất."""
    names = _backup_names()
    for name in names[KEEP_BACKUPS:]:
        try:
            os.remove(os.path.join(backups_dir(), name))
        except OSError:
            log.warning("Không xóa được bản sao lưu cũ: %s", name)


def _backup_names() -> list[str]:
    """Tên file sao lưu hợp lệ trong thư mục, mới nhất trước (timestamp trong tên)."""
    folder = backups_dir()
    if not os.path.isdir(folder):
        return []
    names = [n for n in os.listdir(folder) if _NAME_RE.match(n)]
    return sorted(names, reverse=True)


def create_backup(reason: str = "manual") -> str | None:
    """Tạo 1 bản sao lưu nhất quán; trả về tên file. Turso -> None."""
    if _turso_enabled():
        return None
    folder = backups_dir()
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now(VN_TZ).strftime("%Y%m%d-%H%M%S")
    name = f"apyko-{stamp}-{_clean_reason(reason)}.db"
    dest = os.path.join(folder, name)
    src = sqlite3.connect(config.DATABASE_PATH)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    _prune()
    log.info("Đã tạo bản sao lưu %s", name)
    return name


def maybe_daily_backup() -> str | None:
    """Tự sao lưu 1 lần mỗi ngày (giờ VN): hôm nay đã có bản nào thì bỏ qua."""
    if _turso_enabled():
        return None
    prefix = "apyko-" + datetime.now(VN_TZ).strftime("%Y%m%d") + "-"
    if any(n.startswith(prefix) for n in _backup_names()):
        return None
    return create_backup("auto")


def list_backups() -> list[dict]:
    """Danh sách bản sao lưu: [{name, size, mtime}] — mới nhất trước."""
    folder = backups_dir()
    out = []
    for name in _backup_names():
        path = os.path.join(folder, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        out.append(
            {
                "name": name,
                "size": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime, VN_TZ),
            }
        )
    return out


def backup_path(name: str) -> str:
    """Đường dẫn tuyệt đối của 1 bản sao lưu theo tên — chặn path traversal.

    Tên phải đúng định dạng bản sao lưu, không chứa '/', và sau khi resolve
    vẫn phải nằm trong thư mục backups. Sai -> ValueError.
    """
    if not name or os.path.basename(name) != name or not _NAME_RE.match(name):
        raise ValueError("Tên file sao lưu không hợp lệ.")
    folder = os.path.realpath(backups_dir())
    path = os.path.realpath(os.path.join(folder, name))
    if os.path.dirname(path) != folder:
        raise ValueError("Tên file sao lưu không hợp lệ.")
    if not os.path.isfile(path):
        raise ValueError("Không tìm thấy bản sao lưu.")
    return path


def restore_backup(name: str) -> str:
    """Khôi phục dữ liệu từ 1 bản sao lưu. Trả về thông báo cho người dùng.

    An toàn: tự sao lưu trạng thái HIỆN TẠI (reason "pre-restore") trước
    khi chép đè, nên khôi phục nhầm vẫn quay lại được. Sau khôi phục cần
    tắt app và mở lại.
    """
    if _turso_enabled():
        raise ValueError("Khôi phục chỉ áp dụng cho bản chạy máy tính (DB local).")
    src_path = backup_path(name)
    # Validate: mở read-only, phải là SQLite đọc được + đủ bảng cốt lõi.
    conn = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    except sqlite3.Error as e:
        raise ValueError("File sao lưu không phải SQLite hợp lệ.") from e
    finally:
        conn.close()
    missing = CORE_TABLES - tables
    if missing:
        raise ValueError(
            "File sao lưu thiếu bảng cốt lõi: " + ", ".join(sorted(missing)) + "."
        )
    if os.path.isfile(config.DATABASE_PATH):
        create_backup("pre-restore")
    shutil.copyfile(src_path, config.DATABASE_PATH)
    log.warning("Đã khôi phục dữ liệu từ bản sao lưu %s", name)
    return (
        f"Đã khôi phục dữ liệu từ bản {name}. "
        "Hãy tắt app và mở lại để dùng dữ liệu đã khôi phục."
    )
