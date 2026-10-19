"""Routes: trang HTML (Jinja2) + JSON API. Mọi route đều qua kiểm tra quyền."""

import csv
import io
import os
import re
import sqlite3
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates

from . import auth, config, lessons
from . import database as db
from .auth import (
    ApiCanDeleteProducts,
    ApiCanEditProducts,
    ApiCanViewProducts,
    ApiCanViewUni,
    ApiOwner,
)
from .calc import analyze_product
from .gmv import calc_gmv, validate_gmv_entry
from .validation import payload_from_input, validate_product

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


@router.get("/", response_class=HTMLResponse)
def page_dashboard(request: Request):
    user, redir = auth.page_guard(request, "can_view_products")
    if redir:
        return redir
    data = _dashboard_data()
    data["uni_total"] = len(lessons.list_lessons())
    return templates.TemplateResponse("dashboard.html", _ctx(request, user, **data))


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
    ("can_view_products", "Xem sản phẩm"),
    ("can_add_edit_products", "Thêm / sửa sản phẩm"),
    ("can_delete_products", "Xóa sản phẩm"),
    ("can_view_uni", "Xem Apyko Uni"),
]


def _valid_username(username: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username or ""))


@router.get("/accounts", response_class=HTMLResponse)
def page_accounts(request: Request, new_code: str | None = None, new_user: str | None = None):
    user, redir = auth.page_guard(request)
    if redir:
        return redir
    if not user.get("is_owner"):
        raise HTTPException(status_code=403, detail="Chỉ chủ sở hữu được thực hiện.")
    return templates.TemplateResponse(
        "accounts.html",
        _ctx(
            request,
            user,
            users=db.list_users(),
            perm_fields=_PERM_FIELDS,
            new_code=new_code or "",
            new_user=new_user or "",
        ),
    )


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
        users = db.list_users()
        return templates.TemplateResponse(
            "accounts.html",
            _ctx(request, user, users=users, perm_fields=_PERM_FIELDS, error=error),
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
            "can_view_products": 1 if form.get("can_view_products") else 0,
            "can_add_edit_products": 1 if form.get("can_add_edit_products") else 0,
            "can_delete_products": 1 if form.get("can_delete_products") else 0,
            "can_view_uni": 1 if form.get("can_view_uni") else 0,
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
        {
            "can_view_products": 1 if form.get("can_view_products") else 0,
            "can_add_edit_products": 1 if form.get("can_add_edit_products") else 0,
            "can_delete_products": 1 if form.get("can_delete_products") else 0,
            "can_view_uni": 1 if form.get("can_view_uni") else 0,
        },
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


@router.get("/gmv", response_class=HTMLResponse)
def page_gmv(request: Request, product_id: int | None = None):
    user, redir = auth.page_guard(request, "can_view_products")
    if redir:
        return redir
    products = db.gmv_list_products()
    active = None
    if products:
        active = next((p for p in products if p["id"] == product_id), products[0])
    return templates.TemplateResponse(
        "gmv.html",
        _ctx(
            request,
            user,
            products=products,
            active=active,
            can_edit=bool(user.get("can_add_edit_products")),
            can_delete=bool(user.get("can_delete_products")),
        ),
    )


@router.get("/api/gmv/products")
def api_gmv_list_products(user: dict = ApiCanViewProducts):
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
def api_gmv_list_entries(product_id: int, user: dict = ApiCanViewProducts):
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
