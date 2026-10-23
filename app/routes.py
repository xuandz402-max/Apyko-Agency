"""Routes: trang HTML (Jinja2) + JSON API. Mọi route đều qua kiểm tra quyền."""

import csv
import io
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates

from . import (
    affiliate,
    auth,
    backup,
    ceo,
    checklist,
    config,
    gmv_charts,
    importer,
    lessons,
    periods,
    pricing,
    rangeview,
    tiktok,
)
from . import database as db
from .auth import (
    ApiCanDeleteProducts,
    ApiCanEditProducts,
    ApiCanViewDaily,
    ApiCanViewGmv,
    ApiCanViewPricing,
    ApiCanViewProducts,
    ApiCanViewUni,
    ApiOwner,
    ApiUser,
)
from .calc import analyze_product
from .daily import calc_daily, period_totals, validate_daily_report
from .gmv import calc_gmv, validate_gmv_entry
from .validation import payload_from_input, validate_product

log = logging.getLogger("apyko.routes")

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(_PROJECT_DIR, "templates"))

router = APIRouter()

_EXPORT_FIELDS = [
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
    "notes",
]

_DEMO_PRODUCTS = [
    {
        "name": "[DEMO] Hộp carton sóng E 25x18x10cm",
        "sku": "DEMO-BOX-01",
        "category": "Vật tư đóng gói",
        "data_source": "demo",
        "selling_price": 4500,
        "cost_price": 2800,
        "packaging_cost": 0,
        "shipping_seller": 0,
        "platform_fee_rate": 9,
        "payment_fee_rate": 2.5,
        "ads_rate": 0,
        "affiliate_rate": 0,
        "other_cost": 300,
        "demand_score": 4,
        "competition_score": 3,
        "content_score": 2,
        "supply_score": 5,
        "status": "active",
        "is_demo": 1,
        "notes": "Dữ liệu demo — xóa sau khi dùng thử.",
    },
    {
        "name": "[DEMO] Túi niêm phong PE 28x38cm (100 túi)",
        "sku": "DEMO-BAG-02",
        "category": "Vật tư đóng gói",
        "data_source": "demo",
        "selling_price": 32000,
        "cost_price": 21000,
        "packaging_cost": 0,
        "shipping_seller": 0,
        "platform_fee_rate": 9,
        "payment_fee_rate": 2.5,
        "ads_rate": 5,
        "affiliate_rate": 0,
        "other_cost": 500,
        "demand_score": 4,
        "competition_score": 2,
        "content_score": 3,
        "supply_score": 4,
        "status": "active",
        "is_demo": 1,
        "notes": "Dữ liệu demo — xóa sau khi dùng thử.",
    },
    {
        "name": "[DEMO] Băng keo trong 48mm x 80y",
        "sku": "DEMO-TAPE-03",
        "category": "Vật tư đóng gói",
        "data_source": "demo",
        "selling_price": 18000,
        "cost_price": 12000,
        "packaging_cost": 0,
        "shipping_seller": 0,
        "platform_fee_rate": 9,
        "payment_fee_rate": 2.5,
        "ads_rate": 0,
        "affiliate_rate": 3,
        "other_cost": 200,
        "demand_score": 3,
        "competition_score": 2,
        "content_score": 2,
        "supply_score": 5,
        "status": "testing",
        "is_demo": 1,
        "notes": "Dữ liệu demo — xóa sau khi dùng thử.",
    },
]


def _safe_next(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/"


def _ctx(request: Request, user: dict, **kw) -> dict:
    base = {"request": request, "user": user, "app_name": config.APP_NAME}
    # Caller nào đã tự tính số thông báo chưa đọc (VD: trang /thong-bao) thì
    # truyền unread_notifications=... để _ctx khỏi hỏi DB thêm 1 lần nữa.
    if "unread_notifications" not in kw and user and user.get("id"):
        try:
            base["unread_notifications"] = db.notif_unread_count(user["id"])
        except Exception:
            base["unread_notifications"] = 0
    else:
        base["unread_notifications"] = 0
    base.update(kw)
    return base


# ------------------------------ public ------------------------------------


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/setup", response_class=HTMLResponse)
def page_setup(request: Request):
    if db.count_users() > 0:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("setup.html", _ctx(request, None))


@router.post("/setup")
async def page_setup_create(request: Request):
    if db.count_users() > 0:
        raise HTTPException(status_code=404)
    form = await request.form()
    username = (form.get("username") or "").strip()
    display = (form.get("display_name") or "").strip()
    pw = form.get("password") or ""
    pw2 = form.get("password2") or ""
    errors: dict[str, str] = {}
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
        errors["username"] = "Tên đăng nhập: 3–32 ký tự (chữ, số, _ . -)."  # noqa: RUF001
    if len(pw) < 8:
        errors["password"] = "Mật khẩu ít nhất 8 ký tự."
    if pw != pw2:
        errors["password2"] = "Mật khẩu nhập lại không khớp."
    if errors:
        return templates.TemplateResponse(
            "setup.html",
            _ctx(request, None, errors=errors, username=username, display_name=display),
            status_code=422,
        )
    uid = db.create_user(
        {
            "username": username,
            "display_name": display or username,
            "password_hash": auth.hash_password(pw),
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
        }
    )
    resp = RedirectResponse(url="/", status_code=303)
    auth.set_session_cookie(resp, auth.create_login_session(uid))
    return resp


@router.get("/login", response_class=HTMLResponse)
def page_login(request: Request, next: str | None = None):
    if db.count_users() == 0:
        return RedirectResponse(url="/setup", status_code=303)
    if auth.get_current_user(request):
        return RedirectResponse(url=_safe_next(next), status_code=303)
    return templates.TemplateResponse("login.html", _ctx(request, None, next=next or ""))


@router.post("/login")
async def page_login_submit(request: Request):
    form = await request.form()
    username = (form.get("username") or "").strip()
    pw = form.get("password") or ""
    next_url = _safe_next(form.get("next"))
    user = db.get_user_by_username(username)
    error = None
    if user is None or not user.get("password_hash"):
        error = "Sai tên đăng nhập hoặc mật khẩu."
    elif user.get("must_activate"):
        error = "Tài khoản chưa kích hoạt — hãy vào trang Kích hoạt để đặt mật khẩu."
    elif not user.get("is_active"):
        error = "Tài khoản đang bị khóa. Liên hệ chủ sở hữu."
    elif not auth.verify_password(pw, user["password_hash"]):
        error = "Sai tên đăng nhập hoặc mật khẩu."
    if error:
        return templates.TemplateResponse(
            "login.html",
            _ctx(request, None, error=error, username=username, next=next_url),
            status_code=422,
        )
    resp = RedirectResponse(url=next_url, status_code=303)
    auth.set_session_cookie(resp, auth.create_login_session(user["id"]))
    return resp


@router.get("/activate", response_class=HTMLResponse)
def page_activate(request: Request):
    if db.count_users() == 0:
        return RedirectResponse(url="/setup", status_code=303)
    return templates.TemplateResponse("activate.html", _ctx(request, None))


@router.post("/activate")
async def page_activate_submit(request: Request):
    form = await request.form()
    username = (form.get("username") or "").strip()
    code = auth.normalize_code(form.get("code"))
    pw = form.get("password") or ""
    pw2 = form.get("password2") or ""
    user = db.get_user_by_username(username)
    error = None
    if user is None or not user.get("must_activate"):
        error = "Tài khoản không tồn tại hoặc không cần kích hoạt."
    elif auth.normalize_code(user.get("activation_code")) != code or not code:
        error = "Mã kích hoạt không đúng."
    elif len(pw) < 8:
        error = "Mật khẩu ít nhất 8 ký tự."
    elif pw != pw2:
        error = "Mật khẩu nhập lại không khớp."
    if error:
        return templates.TemplateResponse(
            "activate.html",
            _ctx(request, None, error=error, username=username),
            status_code=422,
        )
    db.update_user(
        user["id"],
        {
            "password_hash": auth.hash_password(pw),
            "is_active": 1,
            "must_activate": 0,
            "activation_code": "",
        },
    )
    resp = RedirectResponse(url="/", status_code=303)
    auth.set_session_cookie(resp, auth.create_login_session(user["id"]))
    return resp


@router.get("/logout")
def page_logout(request: Request):
    auth.logout_request(request)
    resp = RedirectResponse(url="/login", status_code=303)
    auth.clear_session_cookie(resp)
    return resp


# ------------------------------ dashboard ---------------------------------


def _dashboard_data() -> dict:
    items = db.list_products()
    return {
        "total": len(items),
        "profitable": sum(1 for a in items if a["calc"]["profit"] > 0),
        "total_profit": round(sum(a["calc"]["profit"] for a in items)),
        "top": sorted(
            (a for a in items if a["score"]["score"] is not None),
            key=lambda a: a["score"]["score"],
            reverse=True,
        )[:8],
    }


@router.get("/")
def page_home(request: Request):
    """Trang chủ: không còn Dashboard riêng — chuyển thẳng tới trang đầu
    tiên trong sidebar mà user có quyền xem."""
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    if _ceo_can_view(user):
        target = "/ceo"
    elif user.get("can_view_products"):
        target = "/products"
    elif user.get("can_view_daily"):
        target = "/bao-cao"
    elif user.get("can_view_gmv"):
        target = "/gmv"
    elif user.get("can_view_affiliate"):
        target = "/affiliate"
    elif user.get("can_view_tiktok"):
        target = "/tiktok-onboard"
    elif user.get("can_view_pricing"):
        target = "/dinh-gia"
    elif user.get("can_view_cskh"):
        target = "/cskh"
    elif user.get("can_view_accounts"):
        target = "/accounts?tab=shop"
    elif user.get("can_view_uni"):
        target = "/uni"
    else:
        target = "/checklist"
    return RedirectResponse(url=target, status_code=303)


# ------------------------------ dashboard CEO -------------------------------


def _ceo_can_view(user: dict) -> bool:
    """Dashboard CEO: chủ sở hữu hoặc Leader/Quản trị checklist."""
    return bool(
        user.get("is_owner")
        or user.get("can_checklist_leader")
        or user.get("can_checklist_admin")
    )


@router.get("/ceo", response_class=HTMLResponse)
def page_ceo(
    request: Request,
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    if not _ceo_can_view(user):
        raise HTTPException(
            status_code=403, detail="Chỉ chủ sở hữu / Leader / Quản trị được xem."
        )
    # ----- khoảng xem kiểu Shopee Ads (?from&to, mặc định 7 ngày qua):
    # 4 thẻ chính + thẻ checklist là TỔNG của cả khoảng, so với khoảng
    # liền trước dài bằng nhau (rangeview + ceo.range_headline). Các khối
    # theo ngày (cảnh báo, nhân viên, doanh thu 7 ngày) neo tại ngày CUỐI
    # khoảng, kẹp không vượt quá hôm nay thật -----
    real_today = checklist.today_str()
    rng = rangeview.resolve_range(
        {"from": date_from, "to": date_to}, real_today
    )
    view_date = min(rng["cur_end"], real_today)
    is_today = view_date == real_today
    range_cards = ceo.cached_range_headline(rng["cur_start"], rng["cur_end"])

    now = checklist.now_vn()
    weekday_names = [
        "Thứ Hai",
        "Thứ Ba",
        "Thứ Tư",
        "Thứ Năm",
        "Thứ Sáu",
        "Thứ Bảy",
        "Chủ Nhật",
    ]
    now_text = (
        f"{weekday_names[now.weekday()]}, {now.day:02d}/{now.month:02d}/{now.year}"
        f" · {now.hour:02d}:{now.minute:02d}"
    )
    return templates.TemplateResponse(
        "ceo.html",
        _ctx(
            request,
            user,
            ov=ceo.cached_overview(view_date),
            today=view_date,
            view_date=view_date,
            is_today=is_today,
            rng=rng,
            range_cards=range_cards,
            now_text=now_text,
        ),
    )


# ------------------------------ products ----------------------------------


@router.get("/products", response_class=HTMLResponse)
def page_products(
    request: Request,
    q: str | None = None,
    category: str | None = None,
    status: str | None = None,
    sort: str = "updated_at",
    dir: str = "desc",
    msg: str | None = None,
):
    user, redir = auth.page_guard(request, "can_view_products")
    if redir:
        return redir
    products = db.list_products(
        q=q or None,
        category=category or None,
        status=status or None,
        sort=sort,
        dir=dir,
    )
    return templates.TemplateResponse(
        "products.html",
        _ctx(
            request,
            user,
            products=products,
            categories=db.distinct_categories(),
            q=q or "",
            category=category or "",
            status=status or "",
            sort=sort,
            dir=dir,
            msg=msg or "",
        ),
    )


@router.get("/products/new", response_class=HTMLResponse)
def page_product_new(request: Request):
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    return templates.TemplateResponse(
        "product_form.html",
        _ctx(request, user, product=None, errors={}, action="/products"),
    )


@router.post("/products")
async def page_product_create(request: Request):
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    form = await request.form()
    data = {k: v for k, v in form.items() if isinstance(v, str)}
    errors = validate_product(data)
    if errors:
        return templates.TemplateResponse(
            "product_form.html",
            _ctx(request, user, product=data, errors=errors, action="/products"),
            status_code=422,
        )
    db.create_product(payload_from_input(data))
    return RedirectResponse(url="/products?msg=created", status_code=303)


@router.get("/products/{product_id}", response_class=HTMLResponse)
def page_product_detail(product_id: int, request: Request):
    user, redir = auth.page_guard(request, "can_view_products")
    if redir:
        return redir
    p = db.get_product(product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy")
    analyzed = analyze_product(p)
    return templates.TemplateResponse(
        "product_detail.html",
        _ctx(
            request,
            user,
            product=analyzed["product"],
            calc={**analyzed["calc"], **analyzed["score"], "assumptions": analyzed["assumptions"]},
        ),
    )


@router.get("/products/{product_id}/edit", response_class=HTMLResponse)
def page_product_edit(product_id: int, request: Request):
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    p = db.get_product(product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy")
    return templates.TemplateResponse(
        "product_form.html",
        _ctx(request, user, product=p, errors={}, action=f"/products/{product_id}/edit"),
    )


@router.post("/products/{product_id}/edit")
async def page_product_update(product_id: int, request: Request):
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    if db.get_product(product_id) is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy")
    form = await request.form()
    data = {k: v for k, v in form.items() if isinstance(v, str)}
    errors = validate_product(data)
    if errors:
        data = dict(data)
        data["id"] = product_id
        return templates.TemplateResponse(
            "product_form.html",
            _ctx(request, user, product=data, errors=errors, action=f"/products/{product_id}/edit"),
            status_code=422,
        )
    db.update_product(product_id, payload_from_input(data))
    return RedirectResponse(url=f"/products/{product_id}?msg=updated", status_code=303)


@router.post("/products/{product_id}/delete")
async def page_product_delete(product_id: int, request: Request):
    user, redir = auth.page_guard(request, "can_delete_products")
    if redir:
        return redir
    db.delete_product(product_id)
    return RedirectResponse(url="/products?msg=deleted", status_code=303)


@router.get("/analysis", response_class=HTMLResponse)
def page_analysis(request: Request):
    user, redir = auth.page_guard(request, "can_view_products")
    if redir:
        return redir
    rows = db.list_products(sort="score", dir="desc")
    by_label: dict[str, int] = {}
    for a in rows:
        label = a["score"]["label"]
        by_label[label] = by_label.get(label, 0) + 1
    return templates.TemplateResponse(
        "analysis.html", _ctx(request, user, rows=rows, by_label=by_label)
    )


# ------------------------------ apyko uni ---------------------------------


@router.get("/uni", response_class=HTMLResponse)
def page_uni_list(request: Request):
    user, redir = auth.page_guard(request, "can_view_uni")
    if redir:
        return redir
    all_lessons = lessons.list_lessons()
    learned = db.get_learned_lessons(user["id"])
    done = sum(1 for les in all_lessons if les["id"] in learned)
    total = len(all_lessons)
    pct = round(done / total * 100) if total else 0
    return templates.TemplateResponse(
        "uni_list.html",
        _ctx(request, user, lessons=all_lessons, learned=learned, done=done, total=total, pct=pct),
    )


@router.get("/uni/{lesson_id}", response_class=HTMLResponse)
def page_uni_detail(lesson_id: str, request: Request):
    user, redir = auth.page_guard(request, "can_view_uni")
    if redir:
        return redir
    lesson = lessons.get_lesson(lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài học")
    learned = db.get_learned_lessons(user["id"])
    return templates.TemplateResponse(
        "uni_detail.html",
        _ctx(
            request,
            user,
            lesson=lesson,
            body_html=lessons.render_markdown(lesson["body_md"]),
            is_learned=lesson_id in learned,
        ),
    )


@router.post("/uni/{lesson_id}/learn")
async def page_uni_learn(lesson_id: str, request: Request):
    user, redir = auth.page_guard(request, "can_view_uni")
    if redir:
        return redir
    if lessons.get_lesson(lesson_id) is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài học")
    form = await request.form()
    learned = (form.get("learned") or "") == "1"
    db.set_lesson_learned(user["id"], lesson_id, learned)
    return RedirectResponse(url=f"/uni/{lesson_id}", status_code=303)


# ------------------------------ accounts (owner) ---------------------------


_PERM_FIELDS = [
    ("can_view_daily", "Xem Báo cáo ngày"),
    ("can_view_products", "Xem Sản phẩm"),
    ("can_view_pricing", "Xem Định giá sản phẩm"),
    ("can_view_gmv", "Xem GMV Max Shopee"),
    ("can_view_affiliate", "Xem Affiliate"),
    ("can_view_tiktok", "Xem TikTok Onboard"),
    ("can_view_uni", "Xem Apyko Uni"),
    ("can_view_cskh", "Xem Mẫu CSKH"),
    ("can_view_accounts", "Xem Quản lý tài khoản (kho)"),
    ("can_add_edit_products", "Thêm / sửa dữ liệu"),
    ("can_delete_products", "Xóa dữ liệu"),
    ("can_checklist_leader", "Leader checklist"),
    ("can_checklist_admin", "Quản trị checklist"),
]


def _valid_username(username: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username or ""))


# --- Kho tài khoản (vault): tab shop / noi-bo / ban-giao của /accounts ---
# /accounts KHÔNG có ?tab= giữ nguyên hành vi cũ (đăng nhập & phân quyền,
# chỉ chủ sở hữu) — các tab kho phải gọi đích danh. Mật khẩu (tài khoản
# shop lẫn nội bộ) chỉ render cho chủ sở hữu / người có quyền sửa; người
# xem thường không thấy giá trị mật khẩu ở bất cứ đâu trong HTML.

_VAULT_KINDS = ["Ngân hàng", "Shopee", "TikTok Shop", "Facebook", "Email", "Zalo", "Khác"]
_VAULT_TABS = ("shop", "noi-bo", "ban-giao", "dang-nhap")
_SHOP_PLATFORMS = ["Shopee", "TikTok Shop", "Lazada", "Khác"]
_SHOP_ROLES = ["Tài khoản chính", "Tài khoản phụ"]


def _vault_actor(user: dict) -> str:
    return (user.get("display_name") or user.get("username") or "").strip()


def _vault_tab_of(category: str) -> str:
    return "shop" if category == "shop" else "noi-bo"


def _vault_shop_copy_text(it: dict) -> str:
    """Text chép nhanh của 1 tài khoản shop (chỉ tạo cho người có quyền xem mật khẩu)."""
    lines = [f"Shop: {it.get('label') or ''} ({it.get('kind') or ''})"]
    if (it.get("username") or "").strip():
        lines.append(f"Tài khoản: {it['username']}")
    if (it.get("password") or "").strip():
        lines.append(f"Mật khẩu: {it['password']}")
    return "\n".join(lines)


def _vault_noibo_copy_text(it: dict) -> str:
    """Text chép nhanh đăng nhập + mật khẩu (chỉ tạo cho người có quyền xem)."""
    return (
        f"Tài khoản: {it.get('username') or ''}\n"
        f"Mật khẩu: {it.get('password') or ''}"
    )


def _vn_today_str() -> str:
    """Ngày hôm nay theo giờ Việt Nam, dạng DD/MM/YYYY."""
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%d/%m/%Y")


def _build_handover_text(
    assignee: str, internal: list, shops: list, can_see_pw: bool
) -> str:
    """Bản bàn giao tài khoản cho 1 nhân sự — text thuần để chép 1 lần.

    Dòng nào không có dữ liệu thì bỏ qua; mục nào trống thì bỏ cả mục.
    Người không có quyền xem mật khẩu nhận dòng thay thế cố định.
    """
    lines = [
        "THÔNG TIN BÀN GIAO TÀI KHOẢN",
        f"Nhân sự: {assignee}",
        f"Ngày: {_vn_today_str()}",
    ]
    if internal:
        lines += ["", "A. TÀI KHOẢN NỘI BỘ"]
        for i, it in enumerate(internal, 1):
            lines.append(f"{i}. [{it.get('kind') or 'Khác'}] {it.get('label') or ''}")
            if (it.get("username") or "").strip():
                lines.append(f"   Đăng nhập: {it['username']}")
            if (it.get("password") or "").strip():
                pw = it["password"] if can_see_pw else "(liên hệ quản lý để nhận)"
                lines.append(f"   Mật khẩu: {pw}")
            if (it.get("url") or "").strip():
                lines.append(f"   Link: {it['url']}")
            if (it.get("note") or "").strip():
                lines.append(f"   Ghi chú: {it['note']}")
    if shops:
        lines += ["", "B. TÀI KHOẢN SHOP PHỤ TRÁCH"]
        for i, it in enumerate(shops, 1):
            lines.append(f"{i}. [{it.get('kind') or 'Khác'}] {it.get('label') or ''}")
            if (it.get("account_holder") or "").strip():
                lines.append(f"   Loại tài khoản: {it['account_holder']}")
            if (it.get("username") or "").strip():
                lines.append(f"   Đăng nhập: {it['username']}")
            if (it.get("password") or "").strip():
                pw = it["password"] if can_see_pw else "(liên hệ quản lý để nhận)"
                lines.append(f"   Mật khẩu: {pw}")
            if (it.get("url") or "").strip():
                lines.append(f"   Link: {it['url']}")
            if (it.get("note") or "").strip():
                lines.append(f"   Ghi chú: {it['note']}")
    return "\n".join(lines)


def _accounts_base_ctx(user: dict, tab: str) -> dict:
    """Context mặc định của trang /accounts cho mọi tab (đủ biến cho template)."""
    is_owner = bool(user.get("is_owner"))
    can_edit = bool(user.get("can_add_edit_products"))
    return {
        "tab": tab,
        "q": "",
        "err": None,
        "msg": None,
        "error": None,
        "users": [],
        "perm_fields": _PERM_FIELDS,
        "new_code": "",
        "new_user": "",
        "items": [],
        "edit_item": None,
        "kinds": _VAULT_KINDS,
        "platforms": _SHOP_PLATFORMS,
        "roles": _SHOP_ROLES,
        "assignees": [],
        "assignee": "",
        "internal_items": [],
        "shop_items": [],
        "handover_text": "",
        "can_edit": can_edit,
        "can_delete": bool(user.get("can_delete_products")),
        "can_see_pw": is_owner or can_edit,
    }


@router.get("/accounts", response_class=HTMLResponse)
def page_accounts(
    request: Request,
    tab: str | None = None,
    q: str | None = None,
    assignee: str | None = None,
    edit: int | None = None,
    new_code: str | None = None,
    new_user: str | None = None,
    err: str | None = None,
    msg: str | None = None,
):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    if tab not in _VAULT_TABS:
        tab = "dang-nhap"
    ctx = _accounts_base_ctx(user, tab)
    ctx.update(q=q or "", err=err, msg=msg, new_code=new_code or "", new_user=new_user or "")
    is_owner = bool(user.get("is_owner"))
    if tab == "dang-nhap":
        if not is_owner:
            raise HTTPException(status_code=403, detail="Chỉ chủ sở hữu được thực hiện.")
        ctx["users"] = db.list_users()
        return templates.TemplateResponse("accounts.html", _ctx(request, user, **ctx))
    if not (is_owner or user.get("can_view_accounts")):
        raise HTTPException(status_code=403, detail="Tài khoản không có quyền này.")
    if tab in ("shop", "noi-bo"):
        category = "shop" if tab == "shop" else "noi_bo"
        items = db.vault_list(category, q)
        for it in items:
            it["has_password"] = bool((it.get("password") or "").strip())
            if ctx["can_see_pw"]:
                it["copy_text"] = (
                    _vault_shop_copy_text(it)
                    if category == "shop"
                    else _vault_noibo_copy_text(it)
                )
            else:
                # Người xem thường: mật khẩu không được xuất hiện trong HTML,
                # template chỉ biết tài khoản CÓ mật khẩu hay không để hiện •••.
                it["password"] = ""
                it["copy_text"] = ""
        ctx["items"] = items
        if edit:
            item = db.vault_get(edit)
            if item is not None and item["category"] == category:
                ctx["edit_item"] = item
    else:  # ban-giao
        names = db.vault_assignees()
        ctx["assignees"] = names
        chosen = (assignee or "").strip()
        if chosen and chosen in names:
            internal = db.vault_list("noi_bo", assignee=chosen)
            shops = db.vault_list("shop", assignee=chosen)
            ctx["assignee"] = chosen
            ctx["internal_items"] = internal
            ctx["shop_items"] = shops
            ctx["handover_text"] = _build_handover_text(
                chosen, internal, shops, ctx["can_see_pw"]
            )
    return templates.TemplateResponse("accounts.html", _ctx(request, user, **ctx))


@router.post("/accounts/create")
async def page_accounts_create(request: Request):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    if not user.get("is_owner"):
        raise HTTPException(status_code=403)
    form = await request.form()
    username = (form.get("username") or "").strip()
    display = (form.get("display_name") or "").strip() or username
    error = None
    if not _valid_username(username):
        error = "Tên đăng nhập: 3–32 ký tự (chữ, số, _ . -)."  # noqa: RUF001
    elif db.get_user_by_username(username):
        error = "Tên đăng nhập đã tồn tại."
    if error:
        ctx = _accounts_base_ctx(user, "dang-nhap")
        ctx.update(users=db.list_users(), error=error)
        return templates.TemplateResponse(
            "accounts.html",
            _ctx(request, user, **ctx),
            status_code=422,
        )
    code = auth.new_activation_code()
    db.create_user(
        {
            "username": username,
            "display_name": display,
            "password_hash": "",
            "is_owner": 0,
            "is_active": 0,
            "must_activate": 1,
            "activation_code": code,
            **{field: 1 if form.get(field) else 0 for field, _label in _PERM_FIELDS},
        }
    )
    return RedirectResponse(url=f"/accounts?new_user={username}&new_code={code}", status_code=303)


@router.post("/accounts/{user_id}/reset-code")
async def page_accounts_reset_code(user_id: int, request: Request):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    if not user.get("is_owner"):
        raise HTTPException(status_code=403)
    target = db.get_user(user_id)
    if target is None or target.get("is_owner"):
        raise HTTPException(status_code=404)
    code = auth.new_activation_code()
    db.update_user(
        user_id,
        {
            "activation_code": code,
            "must_activate": 1,
            "is_active": 0,
        },
    )
    db.revoke_user_sessions(user_id)
    return RedirectResponse(
        url=f"/accounts?new_user={target['username']}&new_code={code}", status_code=303
    )


@router.post("/accounts/{user_id}/toggle-lock")
async def page_accounts_toggle_lock(user_id: int, request: Request):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    if not user.get("is_owner"):
        raise HTTPException(status_code=403)
    target = db.get_user(user_id)
    if target is None or target.get("is_owner"):
        raise HTTPException(status_code=404)
    new_active = 0 if target.get("is_active") else 1
    db.update_user(user_id, {"is_active": new_active})
    if not new_active:
        db.revoke_user_sessions(user_id)
    return RedirectResponse(url="/accounts", status_code=303)


@router.post("/accounts/{user_id}/perms")
async def page_accounts_perms(user_id: int, request: Request):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    if not user.get("is_owner"):
        raise HTTPException(status_code=403)
    target = db.get_user(user_id)
    if target is None or target.get("is_owner"):
        raise HTTPException(status_code=404)
    form = await request.form()
    db.update_user(
        user_id,
        {field: 1 if form.get(field) else 0 for field, _label in _PERM_FIELDS},
    )
    return RedirectResponse(url="/accounts", status_code=303)


@router.post("/accounts/{user_id}/delete")
async def page_accounts_delete(user_id: int, request: Request):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    if not user.get("is_owner"):
        raise HTTPException(status_code=403)
    target = db.get_user(user_id)
    if target is None or target.get("is_owner") or target["id"] == user["id"]:
        raise HTTPException(status_code=404)
    db.delete_user(user_id)
    return RedirectResponse(url="/accounts", status_code=303)


# ------------------------------ kho tài khoản: thao tác ------------------------------


def _vault_payload(form, category: str) -> dict:
    """Đọc form thêm/sửa tài khoản kho.

    `shop` = tài khoản vận hành sàn của shop: cột account_holder lưu
    LOẠI tài khoản (chính/phụ), kind lưu nền tảng (Shopee/TikTok Shop...).
    """

    def _f(name: str) -> str:
        return (form.get(name) or "").strip()

    data = {
        "category": category,
        "kind": "",
        "label": _f("label"),
        "bank_name": _f("bank_name"),
        "account_number": _f("account_number"),
        "account_holder": _f("account_holder"),
        "username": _f("username"),
        "password": _f("password"),
        "url": _f("url"),
        "assignee": _f("assignee"),
        "note": _f("note"),
    }
    if category == "shop":
        kind = _f("kind")
        data["kind"] = kind if kind in _SHOP_PLATFORMS else "Shopee"
        role = _f("account_holder")
        data["account_holder"] = role if role in _SHOP_ROLES else "Tài khoản chính"
        data["bank_name"] = ""
        data["account_number"] = ""
    else:
        kind = _f("kind")
        data["kind"] = kind if kind in _VAULT_KINDS else "Khác"
    return data


@router.post("/accounts/vault/create")
async def page_vault_create(request: Request):
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    form = await request.form()
    category = form.get("category")
    if category not in ("shop", "noi_bo"):
        category = "shop"
    tab = _vault_tab_of(category)
    data = _vault_payload(form, category)
    if not data["label"]:
        return RedirectResponse(
            url=f"/accounts?tab={tab}&err=" + quote("Thiếu tên / nhãn tài khoản."),
            status_code=303,
        )
    db.vault_create(data, _vault_actor(user))
    return RedirectResponse(
        url=f"/accounts?tab={tab}&msg=" + quote("Đã thêm tài khoản vào kho."),
        status_code=303,
    )


@router.post("/accounts/vault/{item_id}/update")
async def page_vault_update(request: Request, item_id: int):
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    item = db.vault_get(item_id)
    if item is None:
        raise HTTPException(status_code=404)
    form = await request.form()
    data = _vault_payload(form, item["category"])
    tab = _vault_tab_of(item["category"])
    if not data["label"]:
        return RedirectResponse(
            url=f"/accounts?tab={tab}&edit={item_id}&err="
            + quote("Thiếu tên / nhãn tài khoản."),
            status_code=303,
        )
    db.vault_update(item_id, data, _vault_actor(user))
    return RedirectResponse(
        url=f"/accounts?tab={tab}&msg=" + quote("Đã lưu thay đổi."), status_code=303
    )


@router.post("/accounts/vault/{item_id}/delete")
def page_vault_delete(request: Request, item_id: int):
    user, redir = auth.page_guard(request, "can_delete_products")
    if redir:
        return redir
    item = db.vault_get(item_id)
    if item is None:
        raise HTTPException(status_code=404)
    tab = _vault_tab_of(item["category"])
    db.vault_delete(item_id)
    return RedirectResponse(
        url=f"/accounts?tab={tab}&msg=" + quote("Đã xóa tài khoản khỏi kho."),
        status_code=303,
    )


# ------------------------------ JSON API ----------------------------------


@router.get("/api/products")
def api_list_products(
    user: dict = ApiCanViewProducts,
    q: str | None = None,
    category: str | None = None,
    status: str | None = None,
    sort: str = "updated_at",
    dir: str = "desc",
):
    items = db.list_products(
        q=q or None,
        category=category or None,
        status=status or None,
        sort=sort,
        dir=dir,
    )
    return {"items": items, "total": len(items)}


@router.post("/api/products", status_code=201)
async def api_create_product(request: Request, user: dict = ApiCanEditProducts):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"errors": {"body": "Body phải là JSON hợp lệ."}}, status_code=422)
    if not isinstance(body, dict):
        return JSONResponse({"errors": {"body": "Body phải là một object JSON."}}, status_code=422)
    errors = validate_product(body)
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    pid = db.create_product(payload_from_input(body))
    return analyze_product(db.get_product(pid))


@router.get("/api/products/export")
def api_export_products(user: dict = ApiCanViewProducts):
    items = db.list_products(sort="updated_at", dir="desc")
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_EXPORT_FIELDS)
    writer.writeheader()
    for a in items:
        p = a["product"]
        writer.writerow({f: ("" if p.get(f) is None else p.get(f)) for f in _EXPORT_FIELDS})
    payload = buf.getvalue().encode("utf-8-sig")
    filename = "products_export_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/products/{product_id}")
def api_get_product(product_id: int, user: dict = ApiCanViewProducts):
    p = db.get_product(product_id)
    if p is None:
        return JSONResponse({"detail": "Không tìm thấy"}, status_code=404)
    return analyze_product(p)


@router.put("/api/products/{product_id}")
async def api_update_product(product_id: int, request: Request, user: dict = ApiCanEditProducts):
    existing = db.get_product(product_id)
    if existing is None:
        return JSONResponse({"detail": "Không tìm thấy"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"errors": {"body": "Body phải là JSON hợp lệ."}}, status_code=422)
    if not isinstance(body, dict):
        return JSONResponse({"errors": {"body": "Body phải là một object JSON."}}, status_code=422)
    merged = dict(existing)
    for key, value in body.items():
        if key != "id":
            merged[key] = value
    errors = validate_product(merged)
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    updated = db.update_product(product_id, payload_from_input(merged))
    return analyze_product(updated)


@router.delete("/api/products/{product_id}", status_code=204)
def api_delete_product(product_id: int, user: dict = ApiCanDeleteProducts):
    if not db.delete_product(product_id):
        return JSONResponse({"detail": "Không tìm thấy"}, status_code=404)
    return Response(status_code=204)


@router.post("/api/products/import")
async def api_import_products(
    user: dict = ApiCanEditProducts,
    file: Annotated[UploadFile | None, File()] = None,
):
    if file is None:
        return JSONResponse({"errors": {"file": "Thiếu file CSV (field 'file')."}}, status_code=422)
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return JSONResponse(
            {"errors": {"file": "Không đọc được file (cần encoding UTF-8)."}},
            status_code=422,
        )
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "name" not in reader.fieldnames:
        return JSONResponse(
            {"errors": {"file": "File trống hoặc sai header (thiếu cột 'name')."}},
            status_code=422,
        )
    imported = 0
    row_errors = []
    for i, row in enumerate(reader, start=2):
        data = {k: v for k, v in row.items() if k}
        errors = validate_product(data)
        if errors:
            msg = "; ".join(f"{k}: {v}" for k, v in errors.items())
            row_errors.append({"row": i, "error": msg})
            continue
        db.create_product(payload_from_input(data))
        imported += 1
    return {"imported": imported, "errors": row_errors}


@router.get("/api/analysis")
def api_analysis(user: dict = ApiCanViewProducts):
    items = db.list_products()
    by_label: dict[str, int] = {}
    for a in items:
        label = a["score"]["label"]
        by_label[label] = by_label.get(label, 0) + 1
    return {
        "total": len(items),
        "profitable": sum(1 for a in items if a["calc"]["profit"] > 0),
        "total_profit": round(sum(a["calc"]["profit"] for a in items)),
        "by_label": by_label,
    }


@router.post("/api/demo/seed")
def api_seed_demo(user: dict = ApiCanEditProducts):
    for demo in _DEMO_PRODUCTS:
        db.create_product(demo)
    return {"created": len(_DEMO_PRODUCTS)}


@router.delete("/api/demo")
def api_clear_demo(user: dict = ApiCanDeleteProducts):
    return {"deleted": db.clear_demo()}


@router.get("/api/uni")
def api_uni_list(user: dict = ApiCanViewUni):
    all_lessons = lessons.list_lessons()
    learned = db.get_learned_lessons(user["id"])
    return {
        "lessons": [
            {"id": les["id"], "title": les["title"], "learned": les["id"] in learned}
            for les in all_lessons
        ],
        "total": len(all_lessons),
        "done": sum(1 for les in all_lessons if les["id"] in learned),
    }


@router.get("/api/uni/{lesson_id}")
def api_uni_detail(lesson_id: str, user: dict = ApiCanViewUni):
    lesson = lessons.get_lesson(lesson_id)
    if lesson is None:
        return JSONResponse({"detail": "Không tìm thấy bài học"}, status_code=404)
    learned = db.get_learned_lessons(user["id"])
    return {
        "id": lesson["id"],
        "title": lesson["title"],
        "body_html": lessons.render_markdown(lesson["body_md"]),
        "learned": lesson_id in learned,
    }


@router.post("/api/uni/{lesson_id}/learn")
async def api_uni_learn(lesson_id: str, request: Request, user: dict = ApiCanViewUni):
    if lessons.get_lesson(lesson_id) is None:
        return JSONResponse({"detail": "Không tìm thấy bài học"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    db.set_lesson_learned(user["id"], lesson_id, bool((body or {}).get("learned")))
    return {"ok": True}


@router.get("/api/accounts")
def api_accounts_list(user: dict = ApiOwner):
    def _safe(u: dict) -> dict:
        u = dict(u)
        u.pop("password_hash", None)
        u.pop("activation_code", None)
        return u

    return {"users": [_safe(u) for u in db.list_users()]}


# ------------------------------ gmv max shopee ----------------------------


def _gmv_actor(user: dict) -> str:
    return (user.get("display_name") or user.get("username") or "").strip()


def _gmv_enrich(entry: dict) -> dict:
    enriched = dict(entry)
    enriched["calc"] = calc_gmv(enriched)
    return enriched


async def _gmv_json_body(request: Request):
    try:
        body = await request.json()
    except Exception:
        return None, JSONResponse(
            {"errors": {"body": "Body phải là JSON hợp lệ."}}, status_code=422
        )
    if not isinstance(body, dict):
        return None, JSONResponse(
            {"errors": {"body": "Body phải là một object JSON."}}, status_code=422
        )
    return body, None


def _fmt_money_vn(amount) -> str:
    """1234567 -> '1.234.567' (kiểu Việt Nam), khớp định dạng phía client."""
    return f"{int(round(amount)):,}".replace(",", ".")


@router.get("/gmv", response_class=HTMLResponse)
def page_gmv(
    request: Request,
    product_id: int | None = None,
    product: str | None = None,
    days: int | None = None,
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
):
    user, redir = auth.page_guard(request, "can_view_gmv")
    if redir:
        return redir
    _cl_safety_net(checklist.today_str())
    products = db.gmv_list_products()
    active = None
    if products:
        active = next((p for p in products if p["id"] == product_id), products[0])

    # --- biểu đồ + cảnh báo: validate chặt query, sai -> mặc định an toàn ---
    chart_days = days if days in (7, 14, 30) else 14
    chart_product_id = None
    if product and product != "all":
        try:
            candidate = int(product)
        except (TypeError, ValueError):
            candidate = None
        if candidate is not None and any(p["id"] == candidate for p in products):
            chart_product_id = candidate
    today = checklist.today_str()
    series = gmv_charts.build_series(chart_product_id, chart_days, today)
    chart_rows = [
        {
            "date": label,
            "gmv": series["gmv_vnd"][i],
            "cost": series["cost_vnd"][i],
            "roas": series["roas"][i],
            "gmv_fmt": (
                _fmt_money_vn(series["gmv_vnd"][i])
                if series["gmv_vnd"][i] is not None
                else "—"
            ),
            "cost_fmt": (
                _fmt_money_vn(series["cost_vnd"][i])
                if series["cost_vnd"][i] is not None
                else "—"
            ),
        }
        for i, label in enumerate(series["labels"])
    ]
    totals = gmv_charts.product_totals(chart_days, today)
    totals_max = max((t["gmv_vnd"] for t in totals), default=0)
    totals_view = [
        {
            **t,
            "gmv_fmt": _fmt_money_vn(t["gmv_vnd"]),
            "cost_fmt": _fmt_money_vn(t["cost_vnd"]),
            "bar_pct": round(t["gmv_vnd"] * 100 / totals_max, 1) if totals_max else 0,
        }
        for t in totals
    ]

    # --- dải so sánh theo khoảng (bộ chọn kiểu Shopee Ads: ?from&to,
    # mặc định 7 ngày qua; độc lập với ?days/?product của biểu đồ cũ) ---
    rng = rangeview.resolve_range(
        {"from": date_from, "to": date_to}, today
    )
    gmv_cur = gmv_charts.range_totals(rng["cur_start"], rng["cur_end"])
    gmv_prev = gmv_charts.range_totals(rng["prev_start"], rng["prev_end"])
    gmv_cmp = {
        "gmv_vnd": _per_metric(gmv_cur["gmv_vnd"], gmv_prev["gmv_vnd"]),
        "cost_vnd": _per_metric(gmv_cur["cost_vnd"], gmv_prev["cost_vnd"]),
        "roas": _per_metric(gmv_cur["roas"], gmv_prev["roas"]),
        "entries": gmv_cur["entries"],
        "has_data": gmv_cur["entries"] > 0,
    }
    # Sản phẩm đang xem (tab) phải giữ nguyên khi người dùng đổi khoảng.
    per_extra = f"&product_id={active['id']}" if active is not None else ""

    return templates.TemplateResponse(
        "gmv.html",
        _ctx(
            request,
            user,
            products=products,
            active=active,
            can_edit=bool(user.get("can_add_edit_products")),
            can_delete=bool(user.get("can_delete_products")),
            chart_series=series,
            chart_rows=chart_rows,
            chart_has_data=any(v is not None for v in series["gmv_vnd"]),
            chart_days=chart_days,
            chart_product=chart_product_id,
            chart_totals=totals_view,
            gmv_alerts=gmv_charts.gmv_alerts(today),
            roas_warn=gmv_charts.ROAS_WARN,
            rng=rng,
            per_extra=per_extra,
            gmv_cmp=gmv_cmp,
        ),
    )


@router.get("/api/gmv/products")
def api_gmv_list_products(user: dict = ApiCanViewGmv):
    return {"products": db.gmv_list_products()}


@router.post("/api/gmv/products", status_code=201)
async def api_gmv_create_product(request: Request, user: dict = ApiCanEditProducts):
    body, err = await _gmv_json_body(request)
    if err:
        return err
    name = (body.get("name") or "").strip() if isinstance(body.get("name"), str) else ""
    if not name:
        return JSONResponse({"errors": {"name": "Tên sản phẩm không được trống."}}, status_code=422)
    try:
        pid = db.gmv_create_product(name)
    except sqlite3.IntegrityError:
        return JSONResponse({"detail": "Tên sản phẩm đã tồn tại."}, status_code=409)
    return db.gmv_get_product(pid)


@router.patch("/api/gmv/products/{product_id}")
async def api_gmv_rename_product(
    product_id: int, request: Request, user: dict = ApiCanEditProducts
):
    body, err = await _gmv_json_body(request)
    if err:
        return err
    name = (body.get("name") or "").strip() if isinstance(body.get("name"), str) else ""
    if not name:
        return JSONResponse({"errors": {"name": "Tên sản phẩm không được trống."}}, status_code=422)
    try:
        renamed = db.gmv_rename_product(product_id, name)
    except sqlite3.IntegrityError:
        return JSONResponse({"detail": "Tên sản phẩm đã tồn tại."}, status_code=409)
    if renamed is None:
        return JSONResponse({"detail": "Không tìm thấy sản phẩm"}, status_code=404)
    return renamed


@router.delete("/api/gmv/products/{product_id}", status_code=204)
def api_gmv_delete_product(product_id: int, user: dict = ApiCanDeleteProducts):
    if not db.gmv_delete_product(product_id):
        return JSONResponse({"detail": "Không tìm thấy sản phẩm"}, status_code=404)
    return Response(status_code=204)


@router.get("/api/gmv/products/{product_id}/entries")
def api_gmv_list_entries(product_id: int, user: dict = ApiCanViewGmv):
    product = db.gmv_get_product(product_id)
    if product is None:
        return JSONResponse({"detail": "Không tìm thấy sản phẩm"}, status_code=404)
    return {
        "product": product,
        "entries": [_gmv_enrich(e) for e in db.gmv_list_entries(product_id)],
        "last_updated": db.gmv_last_updated(product_id),
    }


@router.post("/api/gmv/products/{product_id}/entries")
async def api_gmv_upsert_entry(product_id: int, request: Request, user: dict = ApiCanEditProducts):
    if db.gmv_get_product(product_id) is None:
        return JSONResponse({"detail": "Không tìm thấy sản phẩm"}, status_code=404)
    body, err = await _gmv_json_body(request)
    if err:
        return err
    clean, errors = validate_gmv_entry(body)
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    entry, created = db.gmv_upsert_entry(product_id, clean, _gmv_actor(user))
    return JSONResponse(_gmv_enrich(entry), status_code=201 if created else 200)


@router.put("/api/gmv/entries/{entry_id}")
async def api_gmv_update_entry(entry_id: int, request: Request, user: dict = ApiCanEditProducts):
    if db.gmv_get_entry(entry_id) is None:
        return JSONResponse({"detail": "Không tìm thấy dòng dữ liệu"}, status_code=404)
    body, err = await _gmv_json_body(request)
    if err:
        return err
    clean, errors = validate_gmv_entry(body)
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    try:
        updated = db.gmv_update_entry(entry_id, clean, _gmv_actor(user))
    except sqlite3.IntegrityError:
        return JSONResponse({"detail": "Ngày này đã có dòng dữ liệu."}, status_code=409)
    return _gmv_enrich(updated)


@router.delete("/api/gmv/entries/{entry_id}", status_code=204)
def api_gmv_delete_entry(entry_id: int, user: dict = ApiCanDeleteProducts):
    if not db.gmv_delete_entry(entry_id):
        return JSONResponse({"detail": "Không tìm thấy dòng dữ liệu"}, status_code=404)
    return Response(status_code=204)


# ------------------------------ báo cáo ngày ------------------------------


def _per_metric(cur, prev) -> dict:
    """Chỉ số kèm delta % so với kỳ trước (delta qua app.periods)."""
    return {"cur": cur, "prev": prev, "delta_pct": periods.delta_pct(cur, prev)}


def _daily_actor(user: dict) -> str:
    return (user.get("display_name") or user.get("username") or "").strip()


def _daily_enrich(entry: dict) -> dict:
    enriched = dict(entry)
    enriched["calc"] = calc_daily(enriched)
    return enriched


@router.get("/bao-cao", response_class=HTMLResponse)
def page_daily(
    request: Request,
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
):
    user, redir = auth.page_guard(request, "can_view_daily")
    if redir:
        return redir
    # Bộ chọn khoảng kiểu Shopee Ads: mặc định 30 ngày qua cho trang này.
    rng = rangeview.resolve_range(
        {"from": date_from, "to": date_to},
        checklist.today_str(),
        default="last30",
    )
    all_reports = db.daily_list()
    scoped = [
        r
        for r in all_reports
        if rng["cur_start"] <= r["date"] <= rng["cur_end"]
    ]
    cur_tot = period_totals(all_reports, rng["cur_start"], rng["cur_end"])
    prev_tot = period_totals(all_reports, rng["prev_start"], rng["prev_end"])
    daily_cmp = {
        "revenue": _per_metric(cur_tot["revenue"], prev_tot["revenue"]),
        "ads_cost": _per_metric(cur_tot["ads_cost"], prev_tot["ads_cost"]),
        "roas": _per_metric(cur_tot["roas"], prev_tot["roas"]),
        "count": cur_tot["count"],
        "has_data": cur_tot["count"] > 0,
    }
    return templates.TemplateResponse(
        "daily.html",
        _ctx(
            request,
            user,
            reports=[_daily_enrich(r) for r in scoped],
            can_edit=bool(user.get("can_add_edit_products")),
            can_delete=bool(user.get("can_delete_products")),
            rng=rng,
            daily_cmp=daily_cmp,
        ),
    )


@router.get("/api/daily")
def api_daily_list(user: dict = ApiCanViewDaily):
    return {"reports": [_daily_enrich(r) for r in db.daily_list()]}


@router.get("/api/daily/{report_date}")
def api_daily_get(report_date: str, user: dict = ApiCanViewDaily):
    entry = db.daily_get(report_date)
    if entry is None:
        return JSONResponse({"detail": "Không tìm thấy báo cáo ngày này"}, status_code=404)
    return _daily_enrich(entry)


@router.post("/api/daily")
async def api_daily_upsert(request: Request, user: dict = ApiCanEditProducts):
    body, err = await _gmv_json_body(request)
    if err:
        return err
    clean, errors = validate_daily_report(body)
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    entry, created = db.daily_upsert(clean, _daily_actor(user))
    return JSONResponse(_daily_enrich(entry), status_code=201 if created else 200)


@router.put("/api/daily/{report_date}")
async def api_daily_update(report_date: str, request: Request, user: dict = ApiCanEditProducts):
    if db.daily_get(report_date) is None:
        return JSONResponse({"detail": "Không tìm thấy báo cáo ngày này"}, status_code=404)
    body, err = await _gmv_json_body(request)
    if err:
        return err
    body = dict(body)
    if isinstance(body.get("date"), str) and body["date"].strip() != report_date:
        return JSONResponse(
            {"errors": {"date": "Ngày trong body phải trùng với ngày trên URL."}},
            status_code=422,
        )
    body["date"] = report_date
    clean, errors = validate_daily_report(body)
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    entry, _ = db.daily_upsert(clean, _daily_actor(user))
    return _daily_enrich(entry)


@router.delete("/api/daily/{report_date}", status_code=204)
def api_daily_delete(report_date: str, user: dict = ApiCanDeleteProducts):
    if not db.daily_delete(report_date):
        return JSONResponse({"detail": "Không tìm thấy báo cáo ngày này"}, status_code=404)
    return Response(status_code=204)


# --------------------- nạp dữ liệu từ Excel/CSV ---------------------------
# Kỷ luật: tải lên -> XEM TRƯỚC (chưa ghi gì) -> user bấm xác nhận mới ghi.
# Kết quả xem trước giữ trong RAM (stash) theo token ngẫu nhiên + user id,
# hết hạn 15 phút, dùng 1 lần — cùng pattern cache in-process của app/ceo.py.

_IMPORT_STASH_TTL = 15 * 60
_import_stash: dict = {}
_import_stash_lock = threading.Lock()


def _stash_put(user_id: int, payload: dict) -> str:
    token = secrets.token_urlsafe(24)
    now = time.monotonic()
    with _import_stash_lock:
        for key in [k for k, v in _import_stash.items() if v["expires"] <= now]:
            del _import_stash[key]
        _import_stash[token] = {
            **payload,
            "user_id": user_id,
            "expires": now + _IMPORT_STASH_TTL,
        }
    return token


def _stash_get(token: str, user_id: int, kind: str) -> dict | None:
    now = time.monotonic()
    with _import_stash_lock:
        item = _import_stash.get(token or "")
        if (
            item is None
            or item["expires"] <= now
            or item["user_id"] != user_id
            or item["kind"] != kind
        ):
            return None
        return item


def _stash_pop(token: str) -> None:
    with _import_stash_lock:
        _import_stash.pop(token or "", None)


def _norm_product_name(name: str) -> str:
    return " ".join((name or "").split()).lower()


def _import_error_page(request, user, message: str, back_url: str, status: int = 422):
    return templates.TemplateResponse(
        "import_preview.html",
        _ctx(request, user, kind="", fatal_error=message, back_url=back_url),
        status_code=status,
    )


def _import_summary(mapped: list) -> dict:
    return {
        "total": len(mapped),
        "ok": sum(1 for m in mapped if m["status"] == "ok"),
        "error": sum(1 for m in mapped if m["status"] == "error"),
        "dup": sum(1 for m in mapped if m["status"] == "dup"),
    }


@router.post("/gmv/import", response_class=HTMLResponse)
async def page_gmv_import(
    request: Request,
    file: Annotated[UploadFile | None, File()] = None,
    currency: Annotated[str, Form()] = "vnd",
    create_products: Annotated[str | None, Form()] = None,
):
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    if file is None or not file.filename:
        return _import_error_page(request, user, "Chưa chọn file để nạp.", "/gmv")
    raw = await file.read()
    try:
        headers, rows = importer.read_table(raw, file.filename)
        mapped = importer.map_gmv_rows(headers, rows, currency)
    except ValueError as e:
        return _import_error_page(request, user, str(e), "/gmv")
    want_create = create_products is not None
    existing = {_norm_product_name(p["name"]) for p in db.gmv_list_products()}
    new_products: list[str] = []
    for item in mapped:
        if item["status"] != "ok":
            continue
        key = _norm_product_name(item["product_name"])
        if key in existing:
            item["match"] = "existing"
        elif want_create:
            item["match"] = "new"
            if item["product_name"] not in new_products:
                new_products.append(item["product_name"])
        else:
            item["match"] = "missing"
            item["warnings"].append(
                "Sản phẩm chưa có trong hệ thống và chưa bật tạo mới — dòng này sẽ bị bỏ qua."
            )
    token = _stash_put(
        user["id"],
        {
            "kind": "gmv",
            "filename": file.filename,
            "currency": "rm" if currency == "rm" else "vnd",
            "create_products": want_create,
            "rows": mapped,
        },
    )
    return templates.TemplateResponse(
        "import_preview.html",
        _ctx(
            request,
            user,
            kind="gmv",
            filename=file.filename,
            currency="rm" if currency == "rm" else "vnd",
            rows=mapped,
            summary=_import_summary(mapped),
            new_products=new_products,
            unknown_columns=importer.unmatched_headers(headers, "gmv"),
            token=token,
            back_url="/gmv",
            confirm_url="/gmv/import/confirm",
            cancel_url="/gmv/import/cancel",
        ),
    )


@router.post("/gmv/import/confirm", response_class=HTMLResponse)
async def page_gmv_import_confirm(
    request: Request, token: Annotated[str, Form()] = ""
):
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    stash = _stash_get(token, user["id"], "gmv")
    if stash is None:
        return _import_error_page(
            request,
            user,
            "Phiên xem trước đã hết hạn hoặc không hợp lệ — chưa ghi gì cả. Hãy nạp lại file.",
            "/gmv",
            status=400,
        )
    _stash_pop(token)
    products = {_norm_product_name(p["name"]): p for p in db.gmv_list_products()}
    actor = _gmv_actor(user)
    created_products: list[str] = []
    n_created = n_updated = n_skipped = 0
    for item in stash["rows"]:
        if item["status"] != "ok":
            n_skipped += 1
            continue
        key = _norm_product_name(item["product_name"])
        product = products.get(key)
        if product is None:
            if not stash["create_products"]:
                n_skipped += 1
                continue
            try:
                pid = db.gmv_create_product(item["product_name"])
                product = db.gmv_get_product(pid)
                created_products.append(product["name"])
            except sqlite3.IntegrityError:
                product = next(
                    (
                        p
                        for p in db.gmv_list_products()
                        if _norm_product_name(p["name"]) == key
                    ),
                    None,
                )
                if product is None:
                    n_skipped += 1
                    continue
            products[key] = product
        _entry, created = db.gmv_upsert_entry(product["id"], item["data"], actor)
        if created:
            n_created += 1
        else:
            n_updated += 1
    return templates.TemplateResponse(
        "import_result.html",
        _ctx(
            request,
            user,
            kind="gmv",
            filename=stash["filename"],
            n_created=n_created,
            n_updated=n_updated,
            n_skipped=n_skipped,
            created_products=created_products,
            back_url="/gmv",
            back_label="🚀 Về GMV Max",
        ),
    )


@router.post("/gmv/import/cancel")
async def page_gmv_import_cancel(
    request: Request, token: Annotated[str, Form()] = ""
):
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    _stash_pop(token)
    return RedirectResponse(url="/gmv", status_code=303)


@router.post("/bao-cao/import", response_class=HTMLResponse)
async def page_daily_import(
    request: Request, file: Annotated[UploadFile | None, File()] = None
):
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    if file is None or not file.filename:
        return _import_error_page(request, user, "Chưa chọn file để nạp.", "/bao-cao")
    raw = await file.read()
    try:
        headers, rows = importer.read_table(raw, file.filename)
        mapped = importer.map_daily_rows(headers, rows)
    except ValueError as e:
        return _import_error_page(request, user, str(e), "/bao-cao")
    for item in mapped:
        if item["status"] in ("ok", "dup"):
            item["total_rev"] = calc_daily(item["data"])["total_rev"]
    token = _stash_put(
        user["id"],
        {"kind": "daily", "filename": file.filename, "rows": mapped},
    )
    return templates.TemplateResponse(
        "import_preview.html",
        _ctx(
            request,
            user,
            kind="daily",
            filename=file.filename,
            rows=mapped,
            summary=_import_summary(mapped),
            new_products=[],
            unknown_columns=importer.unmatched_headers(headers, "daily"),
            token=token,
            back_url="/bao-cao",
            confirm_url="/bao-cao/import/confirm",
            cancel_url="/bao-cao/import/cancel",
        ),
    )


@router.post("/bao-cao/import/confirm", response_class=HTMLResponse)
async def page_daily_import_confirm(
    request: Request, token: Annotated[str, Form()] = ""
):
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    stash = _stash_get(token, user["id"], "daily")
    if stash is None:
        return _import_error_page(
            request,
            user,
            "Phiên xem trước đã hết hạn hoặc không hợp lệ — chưa ghi gì cả. Hãy nạp lại file.",
            "/bao-cao",
            status=400,
        )
    _stash_pop(token)
    actor = _daily_actor(user)
    n_created = n_updated = n_skipped = 0
    for item in stash["rows"]:
        if item["status"] != "ok":
            n_skipped += 1
            continue
        _entry, created = db.daily_upsert(item["data"], actor)
        if created:
            n_created += 1
        else:
            n_updated += 1
    return templates.TemplateResponse(
        "import_result.html",
        _ctx(
            request,
            user,
            kind="daily",
            filename=stash["filename"],
            n_created=n_created,
            n_updated=n_updated,
            n_skipped=n_skipped,
            created_products=[],
            back_url="/bao-cao",
            back_label="📊 Về Báo cáo ngày",
        ),
    )


@router.post("/bao-cao/import/cancel")
async def page_daily_import_cancel(
    request: Request, token: Annotated[str, Form()] = ""
):
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    _stash_pop(token)
    return RedirectResponse(url="/bao-cao", status_code=303)


_DAILY_SAMPLE_HEADERS = [
    "Ngày",
    "Doanh thu sản phẩm",
    "Live",
    "Video",
    "Aff link",
    "Affiliate",
    "GMV quảng cáo",
    "Chi phí ads",
    "AOV",
    "Tỷ lệ chuyển đổi",
    "Ghi chú",
]


@router.get("/bao-cao/file-mau.csv")
def page_daily_sample_csv(request: Request):
    """File mẫu CSV cho nạp Báo cáo ngày (header + 1 dòng ví dụ)."""
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_DAILY_SAMPLE_HEADERS)
    writer.writerow(
        [
            "2026-10-19",
            5000000,
            1200000,
            800000,
            0,
            300000,
            2000000,
            500000,
            150000,
            "2.5",
            "DÒNG VÍ DỤ — xóa dòng này trước khi nạp file thật",
        ]
    )
    content = "\ufeff" + buf.getvalue()
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="apyko-bao-cao-mau.csv"'
        },
    )


# ------------------------------ daily checklist ---------------------------


def _cl_is_admin(user: dict) -> bool:
    return bool(user.get("is_owner") or user.get("can_checklist_admin"))


def _cl_is_leader(user: dict) -> bool:
    return bool(_cl_is_admin(user) or user.get("can_checklist_leader"))


def _cl_can_touch(user: dict, item: dict) -> bool:
    """Được sửa việc: leader/admin/owner hoặc chính nhân viên được giao."""
    if _cl_is_leader(user):
        return True
    return item.get("assignee_id") == user.get("id")


def _cl_valid_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


# Lưới an toàn là DỰ PHÒNG (scheduler nền đã tick mỗi 60s làm cùng việc,
# idempotent) nên throttle theo tiến trình: tối đa 1 lần / 60 giây cho mọi
# trang, tránh trả hàng chục câu query mỗi lần người dùng mở trang.
_SAFETY_NET_INTERVAL = 60  # giây
_safety_net_last_run = 0.0
_safety_net_lock = threading.Lock()


def _cl_safety_net(date_str: str) -> None:
    """Lưới an toàn khi mở trang: tạo việc + gửi nhắc (idempotent).

    Bị throttle 60 giây/toàn tiến trình — nhắc hạn chậm tối đa ~60 giây so
    với không throttle, đổi lại mở trang checklist/thông báo nhẹ đi rõ rệt.
    """
    global _safety_net_last_run
    now = time.monotonic()
    with _safety_net_lock:
        if now - _safety_net_last_run < _SAFETY_NET_INTERVAL:
            return
        _safety_net_last_run = now
    try:
        checklist.seed_defaults()
        checklist.generate_for_date(date_str)
        checklist.process_reminders(checklist.now_vn())
    except Exception:
        log.exception("Lỗi lưới an toàn Daily Checklist")
    # Cảnh báo GMV luôn tính theo ngày thật hôm nay (không theo ngày đang
    # xem ở trang checklist); dedupe theo ngày nên mở trang nào cũng an toàn.
    try:
        gmv_charts.sync_gmv_alert_notifications(checklist.today_str())
    except Exception:
        log.exception("Lỗi lưới an toàn cảnh báo GMV")


def _cl_enrich(item: dict, now, settings, users_map: dict, shops_map: dict) -> dict:
    enriched = dict(item)
    enriched["state"] = checklist.display_state(item, now, settings["due_soon_min"])
    assignee = users_map.get(item.get("assignee_id"))
    enriched["assignee_name"] = (
        (assignee.get("display_name") or assignee.get("username")) if assignee else ""
    )
    shop = shops_map.get(item.get("shop_id"))
    enriched["shop_name"] = shop["name"] if shop else ""
    return enriched


async def _cl_json_body(request: Request, required: bool = True):
    """Body JSON: required=True như module khác; False cho phép body trống."""
    try:
        body = await request.json()
    except Exception:
        if not required:
            return {}, None
        return None, JSONResponse(
            {"errors": {"body": "Body phải là JSON hợp lệ."}}, status_code=422
        )
    if not isinstance(body, dict):
        if not required:
            return {}, None
        return None, JSONResponse(
            {"errors": {"body": "Body phải là một object JSON."}}, status_code=422
        )
    return body, None


@router.get("/checklist", response_class=HTMLResponse)
def page_checklist(
    request: Request,
    date: str | None = None,
    assignee: int | None = None,
    shop: int | None = None,
):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    today = checklist.today_str()
    date_str = _cl_valid_date(date) or today
    _cl_safety_net(date_str)
    leader = _cl_is_leader(user)
    eff_assignee = assignee if leader else user["id"]
    items = db.cl_item_list(date_str, assignee_id=eff_assignee, shop_id=shop)
    settings = checklist.get_settings()
    now = checklist.now_vn()
    # Query 1 lần rồi dùng chung cho map hiển thị + dropdown trong template.
    users_list = db.list_users()
    shops_list = db.shop_list()
    users_map = {u["id"]: u for u in users_list}
    shops_map = {s["id"]: s for s in shops_list}
    enriched = [_cl_enrich(it, now, settings, users_map, shops_map) for it in items]
    groups = []
    for it in enriched:
        if groups and groups[-1]["name"] == it["group_name"]:
            groups[-1]["items"].append(it)
        else:
            groups.append({"name": it["group_name"] or "Khác", "items": [it]})
    return templates.TemplateResponse(
        "checklist.html",
        _ctx(
            request,
            user,
            date=date_str,
            today=today,
            groups=groups,
            is_leader=leader,
            is_admin=_cl_is_admin(user),
            users=users_list if leader else [],
            shops=shops_list,
            f_assignee=assignee,
            f_shop=shop,
        ),
    )


@router.get("/checklist/board", response_class=HTMLResponse)
def page_checklist_board(
    request: Request,
    date: str | None = None,
    assignee: int | None = None,
    shop: int | None = None,
    period: str | None = None,
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    if not _cl_is_leader(user):
        raise HTTPException(status_code=403, detail="Chỉ Leader/Quản trị được xem.")
    date_str = _cl_valid_date(date) or checklist.today_str()
    _cl_safety_net(date_str)
    # Kỳ tính quanh "ngày neo" (param date như cũ); mặc định day = đúng
    # ngày đang chọn như trước. Kỳ dài bị chặn 31 ngày (periods.cap_period)
    # vì tổng hợp phải cộng dồn board_stats từng ngày.
    per_info = periods.resolve_period(
        {"period": period, "from": date_from, "to": date_to}, date_str
    )
    per_info = periods.cap_period(per_info, max_days=31)
    users_list = db.list_users()  # 1 lần: board stats dùng lại + dropdown lọc
    now = checklist.now_vn()
    stats = checklist.board_range_stats(
        per_info["cur_start"],
        per_info["cur_end"],
        assignee_id=assignee,
        shop_id=shop,
        now=now,
        users=users_list,
    )
    prev_stats = checklist.board_range_stats(
        per_info["prev_start"],
        per_info["prev_end"],
        assignee_id=assignee,
        shop_id=shop,
        now=now,
        users=users_list,
    )
    # Delta % hoàn thành tính bằng ĐIỂM % (hiệu 2 tỷ lệ), chỉ khi cả 2 kỳ
    # đều có việc thực tế (total - cancelled > 0).
    pct_delta = None
    cur_tasks = stats["total"] - stats["cancelled"]
    prev_tasks = prev_stats["total"] - prev_stats["cancelled"]
    if cur_tasks > 0 and prev_tasks > 0:
        pct_delta = round(stats["pct"] - prev_stats["pct"], 1)
    # Giữ bộ lọc ngày neo / nhân viên / shop khi chuyển kỳ.
    per_extra = f"&date={date_str}"
    per_hidden = [("date", date_str)]
    if assignee is not None:
        per_extra += f"&assignee={assignee}"
        per_hidden.append(("assignee", str(assignee)))
    if shop is not None:
        per_extra += f"&shop={shop}"
        per_hidden.append(("shop", str(shop)))
    return templates.TemplateResponse(
        "checklist_board.html",
        _ctx(
            request,
            user,
            stats=stats,
            date=date_str,
            users=users_list,
            shops=db.shop_list(),
            f_assignee=assignee,
            f_shop=shop,
            per_info=per_info,
            per_extra=per_extra,
            per_hidden=per_hidden,
            pct_delta=pct_delta,
            prev_pct=prev_stats["pct"],
        ),
    )


@router.get("/checklist/admin", response_class=HTMLResponse)
def page_checklist_admin(request: Request):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    if not _cl_is_admin(user):
        raise HTTPException(status_code=403, detail="Chỉ Quản trị checklist được xem.")
    raw = dict(checklist.DEFAULT_SETTINGS)
    raw.update(db.cl_setting_get_all())
    return templates.TemplateResponse(
        "checklist_admin.html",
        _ctx(
            request,
            user,
            templates=db.cl_template_list(),
            shops=db.shop_list(),
            users=db.list_users(),
            settings=raw,
        ),
    )


@router.get("/thong-bao", response_class=HTMLResponse)
def page_notifications(request: Request):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    _cl_safety_net(checklist.today_str())
    notifs = db.notif_list(user["id"])
    unread = db.notif_unread_count(user["id"])
    return templates.TemplateResponse(
        "notifications.html",
        # unread_notifications=unread: _ctx khỏi COUNT thêm 1 lần nữa.
        _ctx(request, user, notifications=notifs, unread=unread, unread_notifications=unread),
    )


@router.post("/api/checklist/generate")
async def api_checklist_generate(request: Request, user: dict = ApiUser):
    if not _cl_is_leader(user):
        return JSONResponse({"detail": "Chỉ Leader/Quản trị được tạo checklist."}, status_code=403)
    body, err = await _cl_json_body(request)
    if err:
        return err
    date_str = _cl_valid_date(body.get("date")) or checklist.today_str()
    created = checklist.generate_for_date(date_str)
    return {"date": date_str, "created": created}


@router.post("/api/checklist/items/{item_id}/complete")
async def api_checklist_complete(item_id: int, request: Request, user: dict = ApiUser):
    item = db.cl_item_get(item_id)
    if item is None:
        return JSONResponse({"detail": "Không tìm thấy công việc."}, status_code=404)
    if not _cl_can_touch(user, item):
        return JSONResponse({"detail": "Bạn không được xử lý công việc này."}, status_code=403)
    body, err = await _cl_json_body(request, required=False)
    if err:
        return err
    actor = (user.get("display_name") or user.get("username") or "").strip()
    update = {
        "status": "done",
        "completed_by": actor,
        "completed_at": checklist.now_vn().isoformat(),
    }
    if "note" in body:
        note = body["note"]
        update["note"] = note.strip() if isinstance(note, str) else ""
    updated = db.cl_item_update(item_id, update)
    return _cl_enrich(
        updated,
        checklist.now_vn(),
        checklist.get_settings(),
        {u["id"]: u for u in db.list_users()},
        {s["id"]: s for s in db.shop_list()},
    )


@router.post("/api/checklist/items/{item_id}/reopen")
async def api_checklist_reopen(item_id: int, user: dict = ApiUser):
    item = db.cl_item_get(item_id)
    if item is None:
        return JSONResponse({"detail": "Không tìm thấy công việc."}, status_code=404)
    if not _cl_can_touch(user, item):
        return JSONResponse({"detail": "Bạn không được xử lý công việc này."}, status_code=403)
    updated = db.cl_item_update(
        item_id, {"status": "pending", "completed_by": "", "completed_at": ""}
    )
    return _cl_enrich(
        updated,
        checklist.now_vn(),
        checklist.get_settings(),
        {u["id"]: u for u in db.list_users()},
        {s["id"]: s for s in db.shop_list()},
    )


@router.post("/api/checklist/items/{item_id}/cancel")
async def api_checklist_cancel(item_id: int, user: dict = ApiUser):
    item = db.cl_item_get(item_id)
    if item is None:
        return JSONResponse({"detail": "Không tìm thấy công việc."}, status_code=404)
    if not _cl_can_touch(user, item):
        return JSONResponse({"detail": "Bạn không được xử lý công việc này."}, status_code=403)
    updated = db.cl_item_update(
        item_id, {"status": "cancelled", "completed_by": "", "completed_at": ""}
    )
    return _cl_enrich(
        updated,
        checklist.now_vn(),
        checklist.get_settings(),
        {u["id"]: u for u in db.list_users()},
        {s["id"]: s for s in db.shop_list()},
    )


@router.post("/api/checklist/items/{item_id}/note")
async def api_checklist_note(item_id: int, request: Request, user: dict = ApiUser):
    item = db.cl_item_get(item_id)
    if item is None:
        return JSONResponse({"detail": "Không tìm thấy công việc."}, status_code=404)
    if not _cl_can_touch(user, item):
        return JSONResponse({"detail": "Bạn không được xử lý công việc này."}, status_code=403)
    body, err = await _cl_json_body(request)
    if err:
        return err
    note = body.get("note")
    if not isinstance(note, str):
        return JSONResponse({"errors": {"note": "Ghi chú phải là chuỗi."}}, status_code=422)
    updated = db.cl_item_update(item_id, {"note": note.strip()})
    return _cl_enrich(
        updated,
        checklist.now_vn(),
        checklist.get_settings(),
        {u["id"]: u for u in db.list_users()},
        {s["id"]: s for s in db.shop_list()},
    )


@router.post("/api/checklist/items/{item_id}/assign")
async def api_checklist_assign(item_id: int, request: Request, user: dict = ApiUser):
    if not _cl_is_leader(user):
        return JSONResponse({"detail": "Chỉ Leader/Quản trị được phân công."}, status_code=403)
    item = db.cl_item_get(item_id)
    if item is None:
        return JSONResponse({"detail": "Không tìm thấy công việc."}, status_code=404)
    body, err = await _cl_json_body(request)
    if err:
        return err
    update: dict = {}
    for field, getter, label in (
        ("assignee_id", db.get_user, "Nhân viên"),
        ("shop_id", db.shop_get, "Shop"),
    ):
        if field in body:
            raw = body[field]
            if raw is None or raw == "":
                update[field] = None
            else:
                try:
                    ref_id = int(raw)
                except (TypeError, ValueError):
                    return JSONResponse(
                        {"errors": {field: f"{label} không hợp lệ."}}, status_code=422
                    )
                if getter(ref_id) is None:
                    return JSONResponse(
                        {"errors": {field: f"{label} không tồn tại."}}, status_code=422
                    )
                update[field] = ref_id
    updated = db.cl_item_update(item_id, update)
    return _cl_enrich(
        updated,
        checklist.now_vn(),
        checklist.get_settings(),
        {u["id"]: u for u in db.list_users()},
        {s["id"]: s for s in db.shop_list()},
    )


@router.post("/api/checklist/templates", status_code=201)
async def api_checklist_template_create(request: Request, user: dict = ApiUser):
    if not _cl_is_admin(user):
        return JSONResponse({"detail": "Chỉ Quản trị checklist được."}, status_code=403)
    body, err = await _cl_json_body(request)
    if err:
        return err
    clean, errors = checklist.validate_template_payload(body)
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    tid = db.cl_template_create(clean)
    return JSONResponse(db.cl_template_get(tid), status_code=201)


@router.put("/api/checklist/templates/{template_id}")
async def api_checklist_template_update(
    template_id: int, request: Request, user: dict = ApiUser
):
    if not _cl_is_admin(user):
        return JSONResponse({"detail": "Chỉ Quản trị checklist được."}, status_code=403)
    if db.cl_template_get(template_id) is None:
        return JSONResponse({"detail": "Không tìm thấy mẫu việc."}, status_code=404)
    body, err = await _cl_json_body(request)
    if err:
        return err
    clean, errors = checklist.validate_template_payload(body, partial=True)
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    return db.cl_template_update(template_id, clean)


@router.post("/api/checklist/templates/{template_id}/toggle")
async def api_checklist_template_toggle(template_id: int, user: dict = ApiUser):
    if not _cl_is_admin(user):
        return JSONResponse({"detail": "Chỉ Quản trị checklist được."}, status_code=403)
    tpl = db.cl_template_get(template_id)
    if tpl is None:
        return JSONResponse({"detail": "Không tìm thấy mẫu việc."}, status_code=404)
    return db.cl_template_update(template_id, {"is_active": 0 if tpl.get("is_active") else 1})


@router.delete("/api/checklist/templates/{template_id}", status_code=204)
async def api_checklist_template_delete(template_id: int, user: dict = ApiUser):
    if not _cl_is_admin(user):
        return JSONResponse({"detail": "Chỉ Quản trị checklist được."}, status_code=403)
    if not db.cl_template_delete(template_id):
        return JSONResponse({"detail": "Không tìm thấy mẫu việc."}, status_code=404)
    return Response(status_code=204)


@router.post("/api/checklist/shops", status_code=201)
async def api_checklist_shop_create(request: Request, user: dict = ApiUser):
    if not _cl_is_admin(user):
        return JSONResponse({"detail": "Chỉ Quản trị checklist được."}, status_code=403)
    body, err = await _cl_json_body(request)
    if err:
        return err
    name = body.get("name")
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        return JSONResponse({"errors": {"name": "Tên shop không được trống."}}, status_code=422)
    try:
        sid = db.shop_create(name)
    except sqlite3.IntegrityError:
        return JSONResponse({"detail": "Tên shop đã tồn tại."}, status_code=409)
    return JSONResponse(db.shop_get(sid), status_code=201)


@router.put("/api/checklist/shops/{shop_id}")
async def api_checklist_shop_update(shop_id: int, request: Request, user: dict = ApiUser):
    if not _cl_is_admin(user):
        return JSONResponse({"detail": "Chỉ Quản trị checklist được."}, status_code=403)
    if db.shop_get(shop_id) is None:
        return JSONResponse({"detail": "Không tìm thấy shop."}, status_code=404)
    body, err = await _cl_json_body(request)
    if err:
        return err
    name = body.get("name")
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        return JSONResponse({"errors": {"name": "Tên shop không được trống."}}, status_code=422)
    try:
        return db.shop_rename(shop_id, name)
    except sqlite3.IntegrityError:
        return JSONResponse({"detail": "Tên shop đã tồn tại."}, status_code=409)


@router.delete("/api/checklist/shops/{shop_id}", status_code=204)
async def api_checklist_shop_delete(shop_id: int, user: dict = ApiUser):
    if not _cl_is_admin(user):
        return JSONResponse({"detail": "Chỉ Quản trị checklist được."}, status_code=403)
    if db.shop_get(shop_id) is None:
        return JSONResponse({"detail": "Không tìm thấy shop."}, status_code=404)
    refs = db.shop_ref_count(shop_id)
    if refs > 0:
        return JSONResponse(
            {"detail": f"Không thể xóa: shop còn {refs} tham chiếu (mẫu việc / việc ngày)."},
            status_code=409,
        )
    db.shop_delete(shop_id)
    return Response(status_code=204)


@router.put("/api/checklist/settings")
async def api_checklist_settings_update(request: Request, user: dict = ApiUser):
    if not _cl_is_admin(user):
        return JSONResponse({"detail": "Chỉ Quản trị checklist được."}, status_code=403)
    body, err = await _cl_json_body(request)
    if err:
        return err
    clean, errors = checklist.validate_settings_payload(body)
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    for key, value in clean.items():
        db.cl_setting_set(key, value)
    raw = dict(checklist.DEFAULT_SETTINGS)
    raw.update(db.cl_setting_get_all())
    return {"settings": raw}


@router.get("/api/notifications")
def api_notifications_list(user: dict = ApiUser):
    return {
        "notifications": db.notif_list(user["id"]),
        "unread": db.notif_unread_count(user["id"]),
    }


@router.post("/api/notifications/read-all")
def api_notifications_read_all(user: dict = ApiUser):
    return {"updated": db.notif_mark_all_read(user["id"])}


@router.post("/api/notifications/{notif_id}/read")
def api_notification_read(notif_id: int, user: dict = ApiUser):
    notif = db.notif_get(notif_id)
    if notif is None:
        return JSONResponse({"detail": "Không tìm thấy thông báo."}, status_code=404)
    if notif.get("user_id") != user.get("id"):
        return JSONResponse({"detail": "Không phải thông báo của bạn."}, status_code=403)
    db.notif_mark_read(notif_id)
    return {"ok": True}


# ------------------------------ định giá sản phẩm ---------------------------
# Nguồn công thức + danh mục ngành + tham số mặc định: file Excel
# "Dự tính giá bán" của user (xem app/pricing.py). Mọi % qua API ở dạng
# người dùng (6 = 6%); DB lưu thập phân (0.06) — chuyển đổi ở pricing.py.


def _pricing_actor(user: dict) -> str:
    return (user.get("display_name") or user.get("username") or "").strip()


def _pricing_enrich(item: dict) -> dict:
    enriched = dict(item)
    enriched["calc"] = pricing.calc_pricing(enriched)
    cat = pricing.find_category(enriched.get("category_code"))
    enriched["category_small"] = cat["small"] if cat else ""
    return enriched


def _pricing_defaults() -> dict:
    """Tham số mặc định dạng DB (thập phân) dùng đổ vào validate."""
    return pricing.settings_to_defaults(db.pricing_setting_get_all())


@router.get("/dinh-gia", response_class=HTMLResponse)
def page_pricing(request: Request):
    # Xem: quyền riêng can_view_pricing (tách khỏi quyền Sản phẩm).
    user, redir = auth.page_guard(request, "can_view_pricing")
    if redir:
        return redir
    return templates.TemplateResponse(
        "pricing.html",
        _ctx(
            request,
            user,
            can_edit=bool(user.get("can_add_edit_products")),
            can_delete=bool(user.get("can_delete_products")),
            can_settings=bool(user.get("is_owner") or user.get("can_checklist_admin")),
        ),
    )


@router.get("/api/pricing/categories")
def api_pricing_categories(q: str = "", user: dict = ApiCanViewPricing):
    results = pricing.search_categories(q, limit=20)
    return {
        "categories": [
            {
                "code": c["code"],
                "fee_rate": c["fee_rate"],
                "fee_pct": round(c["fee_rate"] * 100, 4),
                "big": c["big"],
                "small": c["small"],
                "shop_type": c["shop_type"],
            }
            for c in results
        ]
    }


@router.get("/api/pricing/items")
def api_pricing_list_items(user: dict = ApiCanViewPricing):
    items = [_pricing_enrich(it) for it in db.pricing_item_list()]
    return {"items": items, "total": len(items)}


@router.post("/api/pricing/items", status_code=201)
async def api_pricing_create_item(request: Request, user: dict = ApiCanEditProducts):
    body, err = await _gmv_json_body(request)
    if err:
        return err
    clean, errors = pricing.validate_pricing_payload(body, _pricing_defaults())
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    item_id = db.pricing_item_create(clean, _pricing_actor(user))
    return JSONResponse(_pricing_enrich(db.pricing_item_get(item_id)), status_code=201)


@router.put("/api/pricing/items/{item_id}")
async def api_pricing_update_item(
    item_id: int, request: Request, user: dict = ApiCanEditProducts
):
    if db.pricing_item_get(item_id) is None:
        return JSONResponse({"detail": "Không tìm thấy sản phẩm."}, status_code=404)
    body, err = await _gmv_json_body(request)
    if err:
        return err
    clean, errors = pricing.validate_pricing_payload(body, _pricing_defaults())
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    updated = db.pricing_item_update(item_id, clean)
    return _pricing_enrich(updated)


@router.delete("/api/pricing/items/{item_id}", status_code=204)
def api_pricing_delete_item(item_id: int, user: dict = ApiCanDeleteProducts):
    if not db.pricing_item_delete(item_id):
        return JSONResponse({"detail": "Không tìm thấy sản phẩm."}, status_code=404)
    return Response(status_code=204)


@router.post("/api/pricing/reverse")
async def api_pricing_reverse(request: Request, user: dict = ApiCanViewPricing):
    """Tính NGƯỢC: giá vốn + % biên lãi mong muốn -> giá bán cần đặt."""
    body, err = await _gmv_json_body(request)
    if err:
        return err
    raw_target = body.get("target_margin_pct")
    try:
        target = float(raw_target)
    except (TypeError, ValueError):
        return JSONResponse(
            {"errors": {"target_margin_pct": "% biên lãi mong muốn phải là số."}},
            status_code=422,
        )
    if target >= 100:
        return JSONResponse(
            {"errors": {"target_margin_pct": "Biên lãi từ 100% trở lên không thể đạt được."}},
            status_code=422,
        )
    clean, errors = pricing.validate_pricing_payload(
        body, _pricing_defaults(), require_name=False
    )
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    price = pricing.price_for_margin(clean, target)
    if price is None:
        return JSONResponse(
            {
                "errors": {
                    "target_margin_pct": (
                        "Không khả thi với bộ phí hiện tại"
                        " (tổng các % phí quá cao so với biên lãi mong muốn)."
                    )
                }
            },
            status_code=422,
        )
    calc_in = dict(clean)
    calc_in["selling_price"] = price
    return {
        "selling_price": price,
        "target_margin_pct": target,
        "calc": pricing.calc_pricing(calc_in),
    }


@router.get("/api/pricing/settings")
def api_pricing_get_settings(user: dict = ApiCanViewPricing):
    return {"settings": pricing.settings_to_user_view(db.pricing_setting_get_all())}


@router.put("/api/pricing/settings")
async def api_pricing_update_settings(request: Request, user: dict = ApiUser):
    # Chủ sở hữu hoặc Quản trị checklist mới sửa được tham số mặc định.
    if not _cl_is_admin(user):
        return JSONResponse(
            {"detail": "Chỉ chủ sở hữu / Quản trị checklist được sửa tham số mặc định."},
            status_code=403,
        )
    body, err = await _gmv_json_body(request)
    if err:
        return err
    clean, errors = pricing.validate_settings_payload(body)
    if errors:
        return JSONResponse({"errors": errors}, status_code=422)
    for key, value in clean.items():
        db.pricing_setting_set(key, value)
    return {"settings": pricing.settings_to_user_view(db.pricing_setting_get_all())}


_PRICING_EXPORT_FIELDS = [
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
    "cat_fee",
    "pay_fee",
    "voucher_fee",
    "affiliate_fee",
    "ads_cost",
    "tax_fee",
    "fixed_fee",
    "total_cost",
    "profit",
    "margin_pct",
    "created_by",
    "updated_at",
]


@router.get("/api/pricing/export")
def api_pricing_export(user: dict = ApiCanViewPricing):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_PRICING_EXPORT_FIELDS)
    writer.writeheader()
    for item in db.pricing_item_list():
        enriched = _pricing_enrich(item)
        row = {f: enriched.get(f, "") for f in _PRICING_EXPORT_FIELDS}
        row.update(enriched["calc"])
        writer.writerow(
            {f: ("" if row.get(f) is None else row.get(f)) for f in _PRICING_EXPORT_FIELDS}
        )
    payload = buf.getvalue().encode("utf-8-sig")
    filename = "dinh_gia_export_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ------------------------------ sao lưu & khôi phục ---------------------------


def _require_owner(user: dict) -> None:
    if not user.get("is_owner"):
        raise HTTPException(status_code=403, detail="Chỉ chủ sở hữu được thực hiện.")


@router.get("/sao-luu", response_class=HTMLResponse)
def page_backup(
    request: Request,
    restored: int | None = None,
    msg: str | None = None,
    err: str | None = None,
):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    _require_owner(user)
    items = []
    if backup.is_local():
        for b in backup.list_backups():
            items.append(
                {
                    **b,
                    "mtime_text": b["mtime"].strftime("%d/%m/%Y %H:%M:%S"),
                    "size_kb": round(b["size"] / 1024, 1),
                }
            )
    return templates.TemplateResponse(
        "backup.html",
        _ctx(
            request,
            user,
            is_local=backup.is_local(),
            backups=items,
            restored=restored,
            msg=msg,
            err=err,
        ),
    )


@router.post("/sao-luu/tao")
def page_backup_create(request: Request):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    _require_owner(user)
    name = backup.create_backup("manual")
    if name is None:
        err = quote("Đang dùng database online (Turso) — sao lưu do cloud đảm nhiệm.")
        return RedirectResponse(url="/sao-luu?err=" + err, status_code=303)
    return RedirectResponse(
        url="/sao-luu?msg=" + quote(f"Đã tạo bản sao lưu {name}."),
        status_code=303,
    )


@router.get("/sao-luu/tai/{name}")
def page_backup_download(request: Request, name: str):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    _require_owner(user)
    try:
        path = backup.backup_path(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return FileResponse(path, filename=name, media_type="application/octet-stream")


@router.post("/sao-luu/xoa/{name}")
def page_backup_delete(request: Request, name: str):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    _require_owner(user)
    try:
        message = backup.delete_backup(name)
    except ValueError as e:
        return RedirectResponse(
            url="/sao-luu?err=" + quote(str(e)), status_code=303
        )
    return RedirectResponse(
        url="/sao-luu?msg=" + quote(message), status_code=303
    )


@router.post("/sao-luu/khoi-phuc/{name}")
def page_backup_restore(request: Request, name: str):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    _require_owner(user)
    try:
        message = backup.restore_backup(name)
    except ValueError as e:
        return RedirectResponse(
            url="/sao-luu?err=" + quote(str(e)), status_code=303
        )
    return RedirectResponse(
        url="/sao-luu?restored=1&msg=" + quote(message), status_code=303
    )


# ------------------------------ KPI nhân viên ---------------------------------


def _kpi_compute(date_from, date_to):
    """Số liệu KPI cho khoảng đang chọn + khoảng liền trước (dùng chung
    trang + CSV).

    Khoảng lấy từ bộ chọn kiểu Shopee Ads (?from&to, mặc định 7 ngày
    qua — app.rangeview). Trả (rng, rows, team). rows đã xếp hạng:
    % hoàn thành giảm dần, hòa thì ít quá hạn hơn đứng trên. Delta là
    ĐIỂM % (hiệu 2 tỷ lệ) như Bảng Leader; chỉ tính khi cả 2 khoảng đều
    có việc thực tế của nhân viên đó.
    """
    rng = rangeview.resolve_range(
        {"from": date_from, "to": date_to}, checklist.today_str()
    )
    users_list = db.list_users()
    now = checklist.now_vn()
    cur = checklist.board_range_stats(
        rng["cur_start"], rng["cur_end"], now=now, users=users_list
    )
    prev = checklist.board_range_stats(
        rng["prev_start"], rng["prev_end"], now=now, users=users_list
    )
    prev_by_id = {b["user_id"]: b for b in prev["per_user"]}
    rows = []
    for b in cur["per_user"]:
        pb = prev_by_id.get(b["user_id"])
        delta = None
        if b["total"] > 0 and pb is not None and pb["total"] > 0:
            delta = round(b["pct"] - pb["pct"], 1)
        rows.append(
            {
                "user_id": b["user_id"],
                "name": b["name"],
                "total": b["total"],
                "done": b["done"],
                "overdue": b["overdue"],
                "pct": b["pct"],
                "prev_pct": pb["pct"] if pb is not None else None,
                "delta": delta,
            }
        )
    rows.sort(key=lambda r: (-r["pct"], r["overdue"], r["name"]))
    cur_tasks = cur["total"] - cur["cancelled"]
    prev_tasks = prev["total"] - prev["cancelled"]
    team_delta = None
    if cur_tasks > 0 and prev_tasks > 0:
        team_delta = round(cur["pct"] - prev["pct"], 1)
    team = {
        "total": cur_tasks,
        "done": cur["done"],
        "overdue": cur["overdue"],
        "pct": cur["pct"],
        "prev_pct": prev["pct"],
        "delta": team_delta,
    }
    return rng, rows, team


@router.get("/kpi", response_class=HTMLResponse)
def page_kpi(
    request: Request,
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    if not _cl_is_leader(user):
        raise HTTPException(status_code=403, detail="Chỉ Leader/Quản trị được xem.")
    rng, rows, team = _kpi_compute(date_from, date_to)
    return templates.TemplateResponse(
        "kpi.html",
        _ctx(
            request,
            user,
            rng=rng,
            rows=rows,
            team=team,
        ),
    )


@router.get("/kpi/export")
def page_kpi_export(
    request: Request,
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    if not _cl_is_leader(user):
        raise HTTPException(status_code=403, detail="Chỉ Leader/Quản trị được xem.")
    rng, rows, team = _kpi_compute(date_from, date_to)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "Nhân viên",
            "Tổng việc",
            "Đã xong",
            "% hoàn thành",
            "Quá hạn",
            "Thay đổi điểm % so với kỳ trước",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r["name"],
                r["total"],
                r["done"],
                r["pct"],
                r["overdue"],
                "" if r["delta"] is None else f"{r['delta']:+.1f}",
            ]
        )
    writer.writerow(
        [
            "TOÀN TEAM",
            team["total"],
            team["done"],
            team["pct"],
            team["overdue"],
            "" if team["delta"] is None else f"{team['delta']:+.1f}",
        ]
    )
    payload = buf.getvalue().encode("utf-8-sig")
    filename = (
        f"kpi_{rng['cur_start']}_{rng['cur_end']}_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
        + ".csv"
    )
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ------------------------------ mẫu trả lời CSKH ------------------------------


def _cskh_actor(user: dict) -> str:
    return (user.get("display_name") or user.get("username") or "").strip()


@router.get("/cskh", response_class=HTMLResponse)
def page_cskh(
    request: Request,
    q: str | None = None,
    edit: int | None = None,
    err: str | None = None,
    msg: str | None = None,
):
    user, redir = auth.page_guard(request, "can_view_cskh")
    if redir:
        return redir
    items = db.cskh_list(q)
    groups: list[dict] = []
    for it in items:
        cat = it["category"] or "Khác"
        if groups and groups[-1]["name"] == cat:
            groups[-1]["items"].append(it)
        else:
            groups.append({"name": cat, "items": [it]})
    edit_item = db.cskh_get(edit) if edit else None
    return templates.TemplateResponse(
        "cskh.html",
        _ctx(
            request,
            user,
            groups=groups,
            total=len(items),
            q=q or "",
            edit_item=edit_item,
            can_edit=bool(user.get("can_add_edit_products")),
            can_delete=bool(user.get("can_delete_products")),
            err=err,
            msg=msg,
        ),
    )


async def _cskh_form_payload(request: Request):
    form = await request.form()
    title = (form.get("title") or "").strip()
    category = (form.get("category") or "").strip()
    content = (form.get("content") or "").strip()
    return title, category, content


@router.post("/cskh")
async def page_cskh_create(request: Request):
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    title, category, content = await _cskh_form_payload(request)
    if not title or not content:
        return RedirectResponse(
            url="/cskh?err=" + quote("Thiếu tiêu đề hoặc nội dung mẫu."),
            status_code=303,
        )
    db.cskh_upsert(
        {"title": title, "category": category, "content": content},
        _cskh_actor(user),
    )
    return RedirectResponse(
        url="/cskh?msg=" + quote("Đã thêm mẫu mới."), status_code=303
    )


@router.post("/cskh/{item_id}/edit")
async def page_cskh_edit(request: Request, item_id: int):
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    if db.cskh_get(item_id) is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy mẫu.")
    title, category, content = await _cskh_form_payload(request)
    if not title or not content:
        return RedirectResponse(
            url=f"/cskh?edit={item_id}&err=" + quote("Thiếu tiêu đề hoặc nội dung mẫu."),
            status_code=303,
        )
    db.cskh_upsert(
        {"id": item_id, "title": title, "category": category, "content": content},
        _cskh_actor(user),
    )
    return RedirectResponse(
        url="/cskh?msg=" + quote("Đã lưu thay đổi."), status_code=303
    )


@router.post("/cskh/{item_id}/delete")
def page_cskh_delete(request: Request, item_id: int):
    user, redir = auth.page_guard(request, "can_delete_products")
    if redir:
        return redir
    if not db.cskh_delete(item_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy mẫu.")
    return RedirectResponse(
        url="/cskh?msg=" + quote("Đã xóa mẫu."), status_code=303
    )


# ------------------------------ affiliate ----------------------------------
# Trang /affiliate gồm 2 tab: "theo-doi" (bảng tracker số tích lũy theo
# link) và "noi-dung" (bài "Shopee tiếp thị liên kết" nguyên văn từ file
# app/data/affiliate_deck.json). Tracker KHÔNG dùng thanh chọn kỳ: số liệu
# là tích lũy theo link (không phải theo ngày) nên lọc kỳ theo updated_at
# là vô nghĩa — thay bằng tìm kiếm tên sản phẩm/Sub ID + lọc nền tảng.


def _affiliate_rows(q: str | None, platform: str | None) -> list:
    rows = db.affiliate_list(q, platform)
    for row in rows:
        row["calc"] = affiliate.calc_affiliate(row)
    return rows


@router.get("/affiliate", response_class=HTMLResponse)
def page_affiliate(
    request: Request,
    tab: str | None = None,
    q: str | None = None,
    platform: str | None = None,
    edit: int | None = None,
    err: str | None = None,
    msg: str | None = None,
):
    user, redir = auth.page_guard(request, "can_view_affiliate")
    if redir:
        return redir
    tab = tab if tab in ("theo-doi", "noi-dung") else "theo-doi"
    platform = platform if platform in affiliate.PLATFORMS else None
    rows = _affiliate_rows(q, platform)
    edit_item = db.affiliate_get(edit) if edit and tab == "theo-doi" else None
    return templates.TemplateResponse(
        "affiliate.html",
        _ctx(
            request,
            user,
            tab=tab,
            rows=rows,
            totals=affiliate.affiliate_totals(rows),
            platforms=affiliate.PLATFORMS,
            q=q or "",
            platform=platform or "",
            edit_item=edit_item,
            deck=affiliate.load_deck() if tab == "noi-dung" else None,
            can_edit=bool(user.get("can_add_edit_products")),
            can_delete=bool(user.get("can_delete_products")),
            err=err,
            msg=msg,
        ),
    )


_AFFILIATE_CSV_FIELDS = [
    ("product_name", "Sản phẩm"),
    ("platform", "Nền tảng"),
    ("affiliate_link", "Link affiliate"),
    ("sub_id", "Sub ID"),
    ("commission_rate", "% hoa hồng"),
    ("clicks", "Click"),
    ("orders", "Đơn"),
    ("cvr", "CVR (%)"),
    ("commission_estimated", "Hoa hồng dự kiến (VNĐ)"),
    ("commission_received", "Hoa hồng thực nhận (VNĐ)"),
    ("epc", "EPC (VNĐ/click)"),
    ("data_source", "Nguồn dữ liệu"),
    ("note", "Ghi chú"),
    ("updated_by", "Cập nhật bởi"),
    ("updated_at", "Cập nhật lúc"),
]


@router.get("/affiliate/export")
def page_affiliate_export(
    request: Request,
    q: str | None = None,
    platform: str | None = None,
):
    user, redir = auth.page_guard(request, "can_view_affiliate")
    if redir:
        return redir
    platform = platform if platform in affiliate.PLATFORMS else None
    rows = _affiliate_rows(q, platform)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([label for _, label in _AFFILIATE_CSV_FIELDS])
    for row in rows:
        values = []
        for field, _label in _AFFILIATE_CSV_FIELDS:
            if field in ("cvr", "epc"):
                v = row["calc"][field]
                values.append("" if v is None else v)
            else:
                values.append(row.get(field, ""))
        writer.writerow(values)
    payload = buf.getvalue().encode("utf-8-sig")
    filename = "affiliate_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _affiliate_form_payload(request: Request) -> tuple:
    form = await request.form()
    return affiliate.validate_affiliate_payload(dict(form))


def _affiliate_err_redirect(errors: dict, edit_id: int | None = None):
    message = "; ".join(errors.values()) or "Dữ liệu chưa hợp lệ."
    url = "/affiliate?err=" + quote(message)
    if edit_id:
        url += f"&edit={edit_id}"
    return RedirectResponse(url=url, status_code=303)


@router.post("/affiliate")
async def page_affiliate_create(request: Request):
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    clean, errors = await _affiliate_form_payload(request)
    if errors:
        return _affiliate_err_redirect(errors)
    db.affiliate_upsert(clean, _cskh_actor(user))
    return RedirectResponse(
        url="/affiliate?msg=" + quote("Đã thêm link affiliate."), status_code=303
    )


@router.post("/affiliate/{item_id}/edit")
async def page_affiliate_edit(request: Request, item_id: int):
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    if db.affiliate_get(item_id) is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy link affiliate.")
    clean, errors = await _affiliate_form_payload(request)
    if errors:
        return _affiliate_err_redirect(errors, edit_id=item_id)
    clean["id"] = item_id
    db.affiliate_upsert(clean, _cskh_actor(user))
    return RedirectResponse(
        url="/affiliate?msg=" + quote("Đã lưu thay đổi."), status_code=303
    )


@router.post("/affiliate/{item_id}/delete")
def page_affiliate_delete(request: Request, item_id: int):
    user, redir = auth.page_guard(request, "can_delete_products")
    if redir:
        return redir
    if not db.affiliate_delete(item_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy link affiliate.")
    return RedirectResponse(
        url="/affiliate?msg=" + quote("Đã xóa link affiliate."), status_code=303
    )


# ------------------------------ tiktok onboard ------------------------------
# Lộ trình onboarding TikTok Shop: danh mục tĩnh 5 giai đoạn / 46 việc lấy
# nguyên văn từ file Excel của chủ shop (app/data/tiktok_onboard.json);
# DB chỉ lưu tiến độ từng việc + nhật ký đổi trạng thái. Validate theo
# sheet "Thiết kế web app" của file nguồn (xem app/tiktok.py).


def _tt_fmt_history_time(iso_utc: str) -> str:
    """Mốc UTC trong tt_history -> giờ Việt Nam 'DD/MM/YYYY HH:MM'."""
    from zoneinfo import ZoneInfo

    try:
        dt = datetime.fromisoformat(iso_utc)
    except (TypeError, ValueError):
        return iso_utc or ""
    if dt.tzinfo is None:
        from datetime import timezone

        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%d/%m/%Y %H:%M")


@router.get("/tiktok-onboard", response_class=HTMLResponse)
def page_tiktok_onboard(
    request: Request,
    tab: str | None = None,
    phase: str | None = None,
    status: str | None = None,
    q: str | None = None,
    err: str | None = None,
    msg: str | None = None,
):
    user, redir = auth.page_guard(request, "can_view_tiktok")
    if redir:
        return redir
    tab = tab if tab in ("danh-sach", "lich-su") else "danh-sach"
    all_tasks = tiktok.merge_progress(tiktok.list_tasks(), db.tt_progress_map())
    phase = phase if phase in tiktok.phase_names() else None
    status = status if status in tiktok.STATUSES else None
    filtered = tiktok.filter_tasks(all_tasks, phase=phase, status=status, q=q)
    history = []
    if tab == "lich-su":
        titles = {t["code"]: t["title"] for t in tiktok.list_tasks()}
        for h in db.tt_history_list(100):
            row = dict(h)
            row["title"] = titles.get(row["code"], "")
            row["changed_vn"] = _tt_fmt_history_time(row.get("changed_at") or "")
            row["old_class"] = tiktok.STATUS_CLASSES.get(row["old_status"], "")
            row["new_class"] = tiktok.STATUS_CLASSES.get(row["new_status"], "")
            history.append(row)
    return templates.TemplateResponse(
        "tiktok_onboard.html",
        _ctx(
            request,
            user,
            tab=tab,
            groups=tiktok.group_by_phase(filtered),
            summary=tiktok.summarize(all_tasks),
            phase_cards=tiktok.phase_summaries(all_tasks),
            phases=tiktok.list_phases(),
            statuses=tiktok.STATUSES,
            status_classes=tiktok.STATUS_CLASSES,
            phase=phase or "",
            status=status or "",
            q=q or "",
            shown=len(filtered),
            history=history,
            can_edit=bool(user.get("can_add_edit_products")),
            err=err,
            msg=msg,
        ),
    )


@router.post("/tiktok-onboard/update")
async def page_tiktok_update(request: Request):
    user, redir = auth.page_guard(request, "can_add_edit_products")
    if redir:
        return redir
    form = await request.form()
    data = dict(form)
    task = tiktok.get_task(str(data.get("code") or "").strip())
    if task is None:
        return RedirectResponse(
            url="/tiktok-onboard?err=" + quote("Mã công việc không tồn tại."),
            status_code=303,
        )
    _clean, errors = tiktok.update_progress(data, _cskh_actor(user), db)
    back = "/tiktok-onboard?phase=" + quote(task["phase"])
    if errors:
        message = "; ".join(errors.values()) or "Dữ liệu chưa hợp lệ."
        return RedirectResponse(url=back + "&err=" + quote(message), status_code=303)
    return RedirectResponse(
        url=back + "&msg=" + quote(f"Đã cập nhật việc {task['code']}."), status_code=303
    )
