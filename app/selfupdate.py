"""Tự cập nhật khi app đang chạy (chỉ bản chạy máy tính Windows, không chạy trên Render).

Cơ chế: luồng nền mỗi 10 phút so sánh ``app/version.txt`` local với file cùng
tên trên nhánh main của repo GitHub public. Bản remote mới hơn -> tải zipball,
ghi đè CHỈ ``app/``, ``templates/``, ``static/``, ``lessons/`` rồi khởi động
lại app bằng file .bat phụ trợ (tạo lúc chạy trong thư mục tạm, KHÔNG commit
vào repo). Mọi lỗi mạng / file hỏng đều bỏ qua lặng lẽ, app cũ vẫn chạy.

Quy tắc đẩy bản mới (xem SELFUPDATE.md): mỗi lần push phải tăng số trong
``app/version.txt`` lên 1 trước khi push, nếu không app đang chạy sẽ không
tự cập nhật.
"""

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

log = logging.getLogger("apyko")

REMOTE_VERSION_URL = (
    "https://raw.githubusercontent.com/xuandz402-max/Apyko-Agency/main/app/version.txt"
)
ZIPBALL_URL = "https://codeload.github.com/xuandz402-max/Apyko-Agency/zip/refs/heads/main"
POLL_SECONDS = 600  # 10 phút
USER_AGENT = "ApykoAgencySelfUpdate/1.0"
# Chỉ các thư mục này được ghi đè khi cập nhật. data/, python/, wheels/,
# .env.local và mọi file .bat/launcher KHÔNG BAO GIỜ bị đụng tới.
ALLOWED_TOP_DIRS = ("app", "templates", "static", "lessons")
_LOCK_DIRNAME = "apyko-selfupdate.lock"
_LOCK_STALE_SECONDS = 3600

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_STARTED = False


def project_dir() -> str:
    """Thư mục gốc của bản cài đặt (thư mục cha của package app/)."""
    return _PROJECT_DIR


def local_version(install_dir: str | None = None) -> int | None:
    """Đọc số bản local từ app/version.txt. None nếu thiếu file / sai định dạng."""
    path = os.path.join(install_dir or _PROJECT_DIR, "app", "version.txt")
    try:
        with open(path, encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def fetch_remote_version(urlopen=None) -> int | None:
    """Lấy số bản remote. Mọi lỗi (mạng, timeout, HTTP khác 200, nội dung
    không phải số nguyên) đều trả None — không bao giờ làm hỏng app."""
    opener = urlopen or urllib.request.urlopen
    try:
        req = urllib.request.Request(REMOTE_VERSION_URL, headers={"User-Agent": USER_AGENT})
        with opener(req, timeout=10) as resp:
            if resp.getcode() != 200:
                return None
            return int(resp.read().decode("utf-8", "ignore").strip())
    except Exception:
        return None


def update_available(local: int | None, remote: int | None) -> bool:
    """Remote mới hơn local thì cần cập nhật. Local thiếu file coi như 0
    (bản cũ chưa có version.txt vẫn tự cập nhật lên được)."""
    if remote is None:
        return False
    return remote > (local or 0)


def _download_zipball(dest_path: str, urlopen=None) -> bool:
    opener = urlopen or urllib.request.urlopen
    try:
        req = urllib.request.Request(ZIPBALL_URL, headers={"User-Agent": USER_AGENT})
        with opener(req, timeout=60) as resp:
            if resp.getcode() != 200:
                return False
            with open(dest_path, "wb") as fh:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    fh.write(chunk)
    except Exception:
        return False
    else:
        return True


def _zip_top_dir(names) -> str:
    """Thư mục gốc duy nhất trong zipball (dạng '<repo>-main/...')."""
    tops = {n.split("/", 1)[0] for n in names if "/" in n}
    if len(tops) == 1:
        return next(iter(tops))
    return ""


def apply_zipball(install_dir: str, zip_path: str) -> bool:
    """Ghi đè các thư mục cho phép từ zipball. Zip hỏng -> False và KHÔNG
    đụng gì tới bản cài đặt. Ghi đè giống cap-nhat: file mới đè file cũ,
    file cũ không có trong bản mới vẫn giữ nguyên."""
    if not zipfile.is_zipfile(zip_path):
        return False
    tmpdir = tempfile.mkdtemp(prefix="apyko-update-")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            if zf.testzip() is not None:
                return False
            names = zf.namelist()
            top = _zip_top_dir(names)
            zf.extractall(tmpdir)
        extracted = os.path.join(tmpdir, top) if top else tmpdir
        for dirname in ALLOWED_TOP_DIRS:
            src = os.path.join(extracted, dirname)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(install_dir, dirname), dirs_exist_ok=True)
    except Exception:
        log.exception("Tự cập nhật: lỗi khi ghi đè file")
        return False
    else:
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _lock_path() -> str:
    return os.path.join(tempfile.gettempdir(), _LOCK_DIRNAME)


def acquire_lock() -> bool:
    """Khóa chống 2 lần cập nhật chạy đồng thời. Khóa quá 1 giờ coi là
    khóa mồ côi (lần cập nhật trước crash) và được chiếm lại."""
    path = _lock_path()
    try:
        os.mkdir(path)
    except FileExistsError:
        try:
            with open(os.path.join(path, "ts"), encoding="utf-8") as fh:
                ts = float(fh.read().strip())
        except (OSError, ValueError):
            ts = 0
        if time.time() - ts < _LOCK_STALE_SECONDS:
            return False
        shutil.rmtree(path, ignore_errors=True)
        try:
            os.mkdir(path)
        except FileExistsError:
            return False
    try:
        with open(os.path.join(path, "ts"), "w", encoding="utf-8") as fh:
            fh.write(str(time.time()))
    except OSError:
        pass
    return True


def release_lock() -> None:
    shutil.rmtree(_lock_path(), ignore_errors=True)


def check_and_apply(install_dir: str | None = None, urlopen=None) -> str:
    """Một vòng kiểm tra + cập nhật. Trả về: disabled | no-update |
    applied | failed | locked. Không bao giờ raise ra ngoài."""
    install_dir = install_dir or _PROJECT_DIR
    if os.environ.get("RENDER"):
        return "disabled"
    try:
        if not update_available(local_version(install_dir), fetch_remote_version(urlopen)):
            return "no-update"
        if not acquire_lock():
            return "locked"
        tmpzip = None
        try:
            fd, tmpzip = tempfile.mkstemp(prefix="apyko-update-", suffix=".zip")
            os.close(fd)
            if not _download_zipball(tmpzip, urlopen):
                return "failed"
            return "applied" if apply_zipball(install_dir, tmpzip) else "failed"
        finally:
            release_lock()
            if tmpzip:
                try:
                    os.unlink(tmpzip)
                except OSError:
                    pass
    except Exception:
        log.exception("Tự cập nhật: lỗi ngoài dự kiến")
        return "failed"


def python_executable(install_dir: str) -> str:
    """Python của bản cài đặt: ưu tiên python/ nhúng (gói Windows), nếu
    không có thì dùng chính interpreter đang chạy app."""
    embedded = os.path.join(install_dir, "python", "python.exe")
    if os.path.exists(embedded):
        return embedded
    return sys.executable


def build_restart_bat(install_dir: str, port: int | None = None) -> str:
    """Nội dung file .bat khởi động lại app trên Windows: chờ 3 giây cho
    tiến trình cũ thoát, kill tiến trình còn giữ cổng, rồi chạy lại app
    bằng đúng lệnh của launcher (uvicorn, cổng 8000 mặc định)."""
    port = port or int(os.environ.get("PORT", "8000"))
    pyexe = python_executable(install_dir)
    lines = [
        "@echo off",
        "timeout /t 3 /nobreak >nul",
        # Kill tiến trình đang LISTENING trên cổng (giống launcher run-app-v4).
        "for /f \"tokens=5\" %%a in "
        f"('netstat -ano ^| findstr \":{port}\" ^| findstr LISTENING') "
        "do taskkill /F /PID %%a >nul 2>&1",
        f"cd /d \"{install_dir}\"",
        f"start \"Apyko Agency\" /min \"{pyexe}\" -m uvicorn app.main:app "
        f"--host 0.0.0.0 --port {port}",
    ]
    return "\r\n".join(lines) + "\r\n"


def spawn_restart_helper(install_dir: str) -> str:
    """Ghi file .bat phụ trợ ra thư mục tạm và chạy nó tách khỏi tiến
    trình app (chỉ thật sự spawn trên Windows; hệ khác chỉ trả về đường
    dẫn để test logic)."""
    fd, bat_path = tempfile.mkstemp(prefix="apyko-restart-", suffix=".bat")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        fh.write(build_restart_bat(install_dir))
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0)
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(
            ["cmd", "/c", bat_path],
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
    return bat_path


def request_restart(install_dir: str | None = None) -> None:
    """Khởi động lại: spawn helper rồi thoát tiến trình để nhường cổng.
    KHÔNG gọi hàm này trong test (nó kết thúc tiến trình)."""
    install_dir = install_dir or _PROJECT_DIR
    spawn_restart_helper(install_dir)
    log.warning("Tự cập nhật: đã áp bản mới, khởi động lại app.")
    os._exit(0)


def selfupdate_loop() -> None:
    """Vòng lặp nền: kiểm tra ngay khi khởi động, sau đó mỗi 10 phút."""
    while True:
        try:
            if check_and_apply() == "applied":
                request_restart()
        except Exception:
            log.exception("Tự cập nhật: lỗi vòng lặp")
        time.sleep(POLL_SECONDS)


def start_selfupdate() -> bool:
    """Khởi động luồng tự cập nhật. Chỉ chạy trên Windows bản máy tính:
    không chạy trên Render, không chạy khi DISABLE_BACKGROUND=1, không
    chạy trên Linux (môi trường dev/CI)."""
    global _STARTED
    if _STARTED:
        return False
    if os.environ.get("RENDER"):
        log.info("RENDER — tắt tự cập nhật (chỉ dành cho bản chạy máy tính).")
        return False
    if os.environ.get("DISABLE_BACKGROUND") == "1":
        return False
    if os.name != "nt":
        log.info("Tự cập nhật chỉ chạy trên Windows — bỏ qua.")
        return False
    _STARTED = True
    thread = threading.Thread(target=selfupdate_loop, name="selfupdate-bg", daemon=True)
    thread.start()
    log.warning("Đã bật tự cập nhật (kiểm tra bản mới mỗi 10 phút).")
    return True
