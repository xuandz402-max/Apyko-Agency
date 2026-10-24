"""Test tự cập nhật (app/selfupdate.py). Toàn bộ test dùng fake network /
fake install, không chạm mạng thật, không thoát tiến trình."""

import io
import os
import zipfile

import pytest
from app import selfupdate


class _FakeResp:
    def __init__(self, code, data: bytes):
        self._code = code
        self._buf = io.BytesIO(data)

    def getcode(self):
        return self._code

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen_factory(version_body: bytes, zip_body: bytes | None = None, code=200):
    def fake(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "version.txt" in url:
            return _FakeResp(code, version_body)
        if zip_body is not None:
            return _FakeResp(code, zip_body)
        raise AssertionError(f"không ngờ tới URL {url}")

    return fake


def _write_version(install_dir, text):
    os.makedirs(os.path.join(install_dir, "app"), exist_ok=True)
    with open(os.path.join(install_dir, "app", "version.txt"), "w", encoding="utf-8") as fh:
        fh.write(text)


def _make_zipball(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            zf.writestr(f"repo-main/{path}", content)
    return buf.getvalue()


def test_local_version_ok_missing_garbage(tmp_path):
    assert selfupdate.local_version(str(tmp_path)) is None
    _write_version(str(tmp_path), "7\n")
    assert selfupdate.local_version(str(tmp_path)) == 7
    _write_version(str(tmp_path), "khong-phai-so")
    assert selfupdate.local_version(str(tmp_path)) is None


def test_update_available_matrix():
    assert selfupdate.update_available(1, 2) is True
    assert selfupdate.update_available(2, 2) is False
    assert selfupdate.update_available(3, 2) is False
    assert selfupdate.update_available(1, None) is False
    assert selfupdate.update_available(None, 1) is True  # chưa có file = coi như 0


def test_fetch_remote_version_ok_bad_status_garbage_error():
    assert selfupdate.fetch_remote_version(_fake_urlopen_factory(b"9\n")) == 9
    assert selfupdate.fetch_remote_version(_fake_urlopen_factory(b"9\n", code=404)) is None
    assert selfupdate.fetch_remote_version(_fake_urlopen_factory(b"xyz")) is None

    def boom(req, timeout=None):
        raise ConnectionError("mạng lỗi")

    assert selfupdate.fetch_remote_version(boom) is None


def _fake_install(tmp_path):
    root = tmp_path / "install"
    (root / "app").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "static").mkdir()
    (root / "templates").mkdir()
    (root / "lessons").mkdir()
    (root / "app" / "old.txt").write_text("cũ", encoding="utf-8")
    (root / "app" / "version.txt").write_text("1", encoding="utf-8")
    (root / "data" / "keep.db").write_text("DỮ LIỆU", encoding="utf-8")
    (root / "run.bat").write_text("LAUNCHER", encoding="utf-8")
    (root / "static" / "old.css").write_text("cũ", encoding="utf-8")
    return root


def test_apply_copies_only_allowed_dirs(tmp_path):
    install = _fake_install(tmp_path)
    zbytes = _make_zipball(
        {
            "app/new.txt": "mới",
            "app/version.txt": "2",
            "templates/new.html": "<html>",
            "static/new.css": "mới",
            "lessons/new.md": "# mới",
            "data/evil.db": "KHÔNG ĐƯỢC CHÉP",
            "run.bat": "KHÔNG ĐƯỢC CHÉP",
        }
    )
    zpath = tmp_path / "update.zip"
    zpath.write_bytes(zbytes)
    assert selfupdate.apply_zipball(str(install), str(zpath)) is True
    assert (install / "app" / "new.txt").read_text(encoding="utf-8") == "mới"
    assert (install / "app" / "version.txt").read_text(encoding="utf-8") == "2"
    assert (install / "templates" / "new.html").exists()
    assert (install / "static" / "new.css").exists()
    assert (install / "lessons" / "new.md").exists()
    # Ghi đè, không xóa file cũ; data/ và .bat tuyệt đối không đụng tới.
    assert (install / "app" / "old.txt").read_text(encoding="utf-8") == "cũ"
    assert (install / "data" / "keep.db").read_text(encoding="utf-8") == "DỮ LIỆU"
    assert not (install / "data" / "evil.db").exists()
    assert (install / "run.bat").read_text(encoding="utf-8") == "LAUNCHER"


def test_apply_invalid_zip_aborts_untouched(tmp_path):
    install = _fake_install(tmp_path)
    zpath = tmp_path / "bad.zip"
    zpath.write_bytes("không phải zip".encode())
    assert selfupdate.apply_zipball(str(install), str(zpath)) is False
    assert (install / "app" / "old.txt").read_text(encoding="utf-8") == "cũ"
    assert (install / "data" / "keep.db").read_text(encoding="utf-8") == "DỮ LIỆU"


def test_check_and_apply_full_flow(tmp_path, monkeypatch):
    install = _fake_install(tmp_path)
    zbytes = _make_zipball({"app/version.txt": "2", "app/new.txt": "mới"})
    fake = _fake_urlopen_factory(b"2\n", zbytes)
    monkeypatch.delenv("RENDER", raising=False)
    assert selfupdate.check_and_apply(str(install), fake) == "applied"
    assert (install / "app" / "version.txt").read_text(encoding="utf-8") == "2"
    assert (install / "data" / "keep.db").read_text(encoding="utf-8") == "DỮ LIỆU"
    # Lần 2: remote bằng local -> không cập nhật, không đụng file.
    assert selfupdate.check_and_apply(str(install), fake) == "no-update"


def test_check_and_apply_disabled_on_render(tmp_path, monkeypatch):
    install = _fake_install(tmp_path)
    monkeypatch.setenv("RENDER", "true")
    fake = _fake_urlopen_factory(b"99\n", b"zip")
    assert selfupdate.check_and_apply(str(install), fake) == "disabled"


def test_restart_bat_construction(tmp_path, monkeypatch):
    install = _fake_install(tmp_path)
    monkeypatch.delenv("PORT", raising=False)
    bat = selfupdate.build_restart_bat(str(install))
    assert "8000" in bat and "taskkill" in bat and "netstat" in bat
    assert "uvicorn app.main:app" in bat
    assert str(install) in bat
    # Chưa có python/ nhúng thì dùng interpreter hiện tại.
    assert "python.exe" not in selfupdate.python_executable(str(install))
    (install / "python").mkdir()
    (install / "python" / "python.exe").write_text("fake", encoding="utf-8")
    assert selfupdate.python_executable(str(install)).endswith("python.exe")
    bat2 = selfupdate.build_restart_bat(str(install))
    assert "python.exe" in bat2


def test_lock_prevents_concurrent_apply():
    assert selfupdate.acquire_lock() is True
    assert selfupdate.acquire_lock() is False
    selfupdate.release_lock()
    assert selfupdate.acquire_lock() is True
    selfupdate.release_lock()


def test_start_selfupdate_guards(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    assert selfupdate.start_selfupdate() is False
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("DISABLE_BACKGROUND", "1")
    assert selfupdate.start_selfupdate() is False
    # Ép môi trường không phải Windows: luồng cũng không khởi động.
    monkeypatch.delenv("DISABLE_BACKGROUND", raising=False)
    monkeypatch.setattr(os, "name", "posix")
    assert selfupdate.start_selfupdate() is False


def test_templates_cache_bust_with_version():
    base = open("templates/base.html", encoding="utf-8").read()
    assert "style.css?v={{ app_version }}" in base
    assert "date-vn.js?v={{ app_version }}" in base


def test_rendered_page_has_versioned_static(client):
    from tests.conftest import create_owner

    create_owner(client)
    r = client.get("/", follow_redirects=True)
    assert r.status_code == 200
    assert "style.css?v=" in r.text


@pytest.fixture(autouse=True)
def _clean_lock(tmp_path, monkeypatch):
    # Khóa test dùng thư mục tạm riêng, tránh kẹt khóa giữa các test.
    import tempfile

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    yield
    selfupdate.release_lock()
