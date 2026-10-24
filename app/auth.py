"""Xác thực & phân quyền (chỉ dùng stdlib: hashlib + secrets).

- Mật khẩu: PBKDF2-HMAC-SHA256, salt riêng từng user, pepper = SECRET_KEY.
- Phiên: token ngẫu nhiên lưu DB, cookie HttpOnly.
- Mã kích hoạt: chuỗi dễ đọc, dùng 1 lần khi nhân sự kích hoạt tài khoản.
- Fail-closed: mọi dependency trả về None/403 khi thiếu danh tính hoặc
  thiếu quyền; không bao giờ "mở" khi không xác minh được.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from . import config
from . import database as db

SESSION_COOKIE = "apyko_session"
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # bỏ ký tự dễ nhầm


def _pepper() -> bytes:
    return config.SECRET_KEY.encode("utf-8")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", _pepper() + password.encode("utf-8"), salt, 200_000)
    return f"pbkdf2$200000${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            _pepper() + password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iters),
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def new_activation_code() -> str:
    # Dạng APYK-XXXX-XXXX, dễ đọc qua điện thoại
    def part():
        return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))

    return f"APYK-{part()}-{part()}"


def normalize_code(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "")


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def create_login_session(user_id: int) -> str:
    token = new_session_token()
    expires = datetime.now(timezone.utc) + timedelta(days=config.SESSION_DAYS)
    db.create_session(token, user_id, expires.isoformat())
    return token


def _session_user(token: str | None) -> dict | None:
    """Trả về user nếu session hợp lệ; ngược lại None (fail-closed)."""
    if not token:
        return None
    sess = db.get_session(token)
    if sess is None or sess.get("revoked"):
        return None
    try:
        exp = datetime.fromisoformat(sess["expires_at"])
    except Exception:
        return None
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < datetime.now(timezone.utc):
        return None
    user = db.get_user(sess["user_id"])
    if user is None or not user.get("is_active"):
        return None
    # Grant sidebar (registry) gắn vào user dict để cổng route + sidebar
    # dùng chung; chủ sở hữu luôn có đủ mọi grant (xem app/sidebar.py).
    from . import sidebar as _sidebar

    if user.get("is_owner"):
        user["sidebar_grants"] = set(_sidebar.all_ids())
    else:
        user["sidebar_grants"] = db.sidebar_grants(user["id"])
    return user


def get_current_user(request: Request) -> dict | None:
    """User hiện tại hoặc None. Không raise — dùng cho template/hiển thị."""
    return _session_user(request.cookies.get(SESSION_COOKIE))


def _login_redirect(request: Request) -> RedirectResponse:
    next_url = request.url.path
    if request.query_params:
        next_url += "?" + str(request.query_params)
    return RedirectResponse(url=f"/login?next={next_url}", status_code=303)


def _deny(status: int, detail: str):
    raise HTTPException(status_code=status, detail=detail)


def api_user(request: Request) -> dict:
    """Dependency cho API: bắt buộc đăng nhập (401 nếu không)."""
    if db.count_users() == 0:
        _deny(401, "Chưa khởi tạo.")
    user = get_current_user(request)
    if user is None:
        _deny(401, "Bạn cần đăng nhập.")
    return user


def api_perm(perm: str):
    """Factory cho API: bắt buộc có quyền `perm` (fail-closed)."""

    def _dep(request: Request) -> dict:
        user = api_user(request)
        if not user.get(perm):
            _deny(403, "Tài khoản không có quyền này.")
        return user

    return _dep


def api_sidebar(sidebar_id: str):
    """Factory cho API: bắt buộc có grant sidebar `sidebar_id` (fail-closed).

    Dùng cho các API thuộc 1 mục sidebar (thay cho api_perm("can_view_*")
    cũ — các cột cờ sidebar đã nghỉ hưu, xem app/sidebar.py).
    """

    def _dep(request: Request) -> dict:
        from . import sidebar as _sidebar

        user = api_user(request)
        if not _sidebar.has_grant(user, sidebar_id):
            _deny(403, "Tài khoản không có quyền này.")
        return user

    return _dep


def api_owner(request: Request) -> dict:
    """Dependency cho API: chỉ owner (fail-closed)."""
    user = api_user(request)
    if not user.get("is_owner"):
        _deny(403, "Chỉ chủ sở hữu được thực hiện.")
    return user


# Dependencies cho API
ApiUser = Depends(api_user)
ApiOwner = Depends(api_owner)
ApiCanViewProducts = Depends(api_sidebar("products"))
ApiCanViewDaily = Depends(api_sidebar("daily"))
ApiCanViewPricing = Depends(api_sidebar("pricing"))
ApiCanViewGmv = Depends(api_sidebar("gmv"))
ApiCanViewAffiliate = Depends(api_sidebar("affiliate"))
ApiCanEditProducts = Depends(api_perm("can_add_edit_products"))
ApiCanDeleteProducts = Depends(api_perm("can_delete_products"))
ApiCanViewUni = Depends(api_sidebar("uni"))


def page_guard_sidebar(request: Request, sidebar_id: str):
    """Cổng route trang thuộc 1 mục sidebar: đăng nhập + grant sidebar.

    Trả về (user, None) hoặc (None, redirect/403) như page_guard.
    """
    from . import sidebar as _sidebar

    user, redir = page_guard(request)
    if redir:
        return None, redir
    if not _sidebar.has_grant(user, sidebar_id):
        raise HTTPException(status_code=403, detail="Tài khoản không có quyền này.")
    return user, None


def page_guard(request: Request, perm: str | None = None):
    """Dùng trong HTML route: trả về (user, None) hoặc (None, redirect/403).

    - Chưa khởi tạo tài khoản nào → về /setup.
    - Chưa đăng nhập → về /login?next=...
    - Thiếu quyền → raise 403.
    """
    if db.count_users() == 0:
        return None, RedirectResponse(url="/setup", status_code=303)
    user = get_current_user(request)
    if user is None:
        next_url = request.url.path
        if request.query_params:
            next_url += "?" + str(request.query_params)
        return None, RedirectResponse(url=f"/login?next={next_url}", status_code=303)
    if perm and not user.get(perm):
        raise HTTPException(status_code=403, detail="Tài khoản không có quyền này.")
    return user, None


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=config.SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def logout_request(request: Request) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.delete_session(token)
