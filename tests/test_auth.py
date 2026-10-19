"""Xác thực: setup, đăng nhập, kích hoạt, fail-closed."""

from conftest import activate, create_owner, create_staff, login, logout


def test_setup_first_run_only(client):
    r = client.get("/setup")
    assert r.status_code == 200
    assert "chủ sở hữu" in r.text.lower()
    create_owner(client)
    # Tạo owner rồi thì /setup phải 404
    assert client.get("/setup").status_code == 404
    assert client.post("/setup", data={}).status_code == 404


def test_setup_password_mismatch(client):
    r = client.post(
        "/setup",
        data={
            "username": "chushop",
            "display_name": "Chủ",
            "password": "matkhau123",
            "password2": "khacnhau",
        },
    )
    assert r.status_code == 422
    assert "không khớp" in r.text


def test_no_users_redirects_to_setup(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/setup"


def test_unauthenticated_redirects_to_login(client):
    create_owner(client)
    logout(client)
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login")
    # API thì 401 JSON, không redirect
    r = client.get("/api/products")
    assert r.status_code == 401


def test_login_wrong_password(client):
    create_owner(client)
    logout(client)
    r = login(client, "chushop", "sai-mat-khau")
    assert r.status_code == 422
    assert "Sai tên đăng nhập" in r.text


def test_login_ok_and_logout(client):
    create_owner(client)
    logout(client)
    r = login(client, "chushop", "matkhau123")
    assert r.status_code == 200
    assert "Dashboard" in r.text
    logout(client)
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303


def test_staff_activation_flow(client):
    create_owner(client)
    code = create_staff(client, "nhanvien01")
    assert code.startswith("APYK-")
    logout(client)
    # Chưa kích hoạt thì không đăng nhập được
    r = login(client, "nhanvien01", "matkhau123")
    assert r.status_code == 422
    assert "kích hoạt" in r.text
    # Kích hoạt bằng mã
    r = activate(client, "nhanvien01", code)
    assert r.status_code == 200
    assert "Dashboard" in r.text or "Sản phẩm" in r.text
    # Mã đã dùng 1 lần: kích hoạt lại phải lỗi
    logout(client)
    r = activate(client, "nhanvien01", code)
    assert r.status_code == 422


def test_activation_wrong_code(client):
    create_owner(client)
    create_staff(client, "nhanvien02")
    logout(client)
    r = activate(client, "nhanvien02", "APYK-SAI1-2345")
    assert r.status_code == 422
    assert "không đúng" in r.text


def test_fail_closed_tampered_cookie(client):
    create_owner(client)
    client.cookies.set("apyko_session", "token-gia-mao-khong-ton-tai")
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login")


def test_locked_account_cannot_login(client):
    create_owner(client)
    code = create_staff(client, "nhanvien03")
    logout(client)
    activate(client, "nhanvien03", code)
    logout(client)
    # Owner khóa tài khoản
    login(client, "chushop", "matkhau123")
    from app import database as db

    target = db.get_user_by_username("nhanvien03")
    r = client.post(f"/accounts/{target['id']}/toggle-lock", follow_redirects=False)
    assert r.status_code == 303
    logout(client)
    r = login(client, "nhanvien03", "matkhau123")
    assert r.status_code == 422
    assert "bị khóa" in r.text
