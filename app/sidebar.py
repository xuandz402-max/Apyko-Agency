"""Sidebar registry — NGUỒN DUY NHẤT cho sidebar + phân quyền sidebar.

Quy tắc (user chốt 24/10): thêm sidebar = thêm 1 entry vào SIDEBAR_ITEMS,
không còn bước thêm cờ tay. Form phân quyền trong Quản lý tài khoản render
checkbox sidebar bằng cách lặp registry này; sidebar hiển thị + cổng route
kiểm tra grant store (bảng user_sidebar_perms) thay vì cột can_view_*.

Các mục NGOẠI LỆ không nằm trong registry (giữ luật riêng, không ép qua
grant store):
- Dashboard CEO: chủ sở hữu hoặc Leader/Quản trị checklist.
- Bảng Leader + KPI nhân viên: Leader/Quản trị checklist.
- Mẫu checklist: chủ sở hữu hoặc Quản trị checklist.
- Sao lưu & Khôi phục: chỉ chủ sở hữu.
- Daily Checklist + Thông báo từng mở cho mọi user đã đăng nhập nên nay là
  mục registry thường, migration cấp grant cho toàn bộ user hiện hữu và
  mặc định bật cho tài khoản mới (xem database._migrate_sidebar_grants).
"""

SIDEBAR_ITEMS = [
    {"id": "products", "label": "Sản phẩm", "route": "/products",
     "icon": "📦", "icon_img": "", "active": "products", "default": True},
    {"id": "analysis", "label": "Phân tích", "route": "/analysis",
     "icon": "📈", "icon_img": "", "active": "analysis", "default": False},
    {"id": "seeding", "label": "Seeding", "route": "/seeding",
     "icon": "🌱", "icon_img": "", "active": "seeding", "default": False},
    {"id": "pricing", "label": "Định giá sản phẩm", "route": "/dinh-gia",
     "icon": "🏷️", "icon_img": "", "active": "pricing", "default": False},
    {"id": "gmv", "label": "GMV Max Shopee", "route": "/gmv",
     "icon": "📣", "icon_img": "", "active": "gmv", "default": False},
    {"id": "affiliate", "label": "Affiliate", "route": "/affiliate",
     "icon": "🔗", "icon_img": "", "active": "affiliate", "default": False},
    {"id": "tiktok", "label": "TikTok Onboard", "route": "/tiktok-onboard",
     "icon": "", "icon_img": "/static/tiktok-icon.png", "active": "tiktok_onboard",
     "default": False},
    {"id": "shopee_onboard", "label": "Shopee Onboard", "route": "/shopee-onboard",
     "icon": "", "icon_img": "/static/shopee-icon.svg", "active": "shopee_onboard",
     "default": False},
    {"id": "daily", "label": "Báo cáo ngày", "route": "/bao-cao",
     "icon": "📊", "icon_img": "", "active": "daily", "default": False},
    {"id": "cskh", "label": "Mẫu CSKH", "route": "/cskh",
     "icon": "💬", "icon_img": "", "active": "cskh", "default": False},
    {"id": "checklist", "label": "Daily Checklist", "route": "/checklist",
     "icon": "✅", "icon_img": "", "active": "checklist", "default": True},
    {"id": "notifications", "label": "Thông báo", "route": "/thong-bao",
     "icon": "🔔", "icon_img": "", "active": "notifications", "default": True},
    {"id": "uni", "label": "Apyko Uni", "route": "/uni",
     "icon": "🎓", "icon_img": "", "active": "uni", "default": True},
    {"id": "accounts", "label": "Quản lý tài khoản", "route": "/accounts?tab=shop",
     "icon": "👥", "icon_img": "", "active": "accounts", "default": False},
]


def all_ids():
    return [it["id"] for it in SIDEBAR_ITEMS]


def default_ids():
    return [it["id"] for it in SIDEBAR_ITEMS if it["default"]]


def by_id(sidebar_id):
    for it in SIDEBAR_ITEMS:
        if it["id"] == sidebar_id:
            return it
    return None


def form_label(item):
    """Nhãn checkbox phân quyền cho 1 mục sidebar (dạng 'Xem ...')."""
    return "Xem " + item["label"]


def has_grant(user, sidebar_id):
    """Chủ sở hữu bypass mọi grant; user thường cần grant row."""
    if not user:
        return False
    if user.get("is_owner"):
        return True
    grants = user.get("sidebar_grants") or set()
    return sidebar_id in grants


def _is_leader(user):
    return bool(
        user.get("is_owner")
        or user.get("can_checklist_leader")
        or user.get("can_checklist_admin")
    )


def _is_cl_admin(user):
    return bool(user.get("is_owner") or user.get("can_checklist_admin"))


def build_nav(user, unread=0):
    """Danh sách mục sidebar đã lọc theo quyền, đúng thứ tự nav cũ.

    Mỗi mục: {label, route, icon, icon_img, active, badge}. Các mục ngoại lệ
    (CEO, Bảng Leader, KPI, Mẫu checklist, Sao lưu) chèn đúng vị trí cũ.
    """
    if not user:
        return []
    nav = []
    if _is_leader(user):
        nav.append({"label": "Dashboard CEO", "route": "/ceo", "icon": "👑",
                    "icon_img": "", "active": "ceo", "badge": 0})
    for item in SIDEBAR_ITEMS:
        if not has_grant(user, item["id"]):
            continue
        entry = {"label": item["label"], "route": item["route"],
                 "icon": item["icon"], "icon_img": item["icon_img"],
                 "active": item["active"], "badge": 0}
        if item["id"] == "notifications" and unread:
            entry["badge"] = unread
        nav.append(entry)
        if item["id"] == "checklist":
            if _is_leader(user):
                nav.append({"label": "Bảng Leader", "route": "/checklist/board",
                            "icon": "📋", "icon_img": "", "active": "checklist_board",
                            "badge": 0})
                nav.append({"label": "KPI nhân viên", "route": "/kpi",
                            "icon": "🏆", "icon_img": "", "active": "kpi",
                            "badge": 0})
            if _is_cl_admin(user):
                nav.append({"label": "Mẫu checklist", "route": "/checklist/admin",
                            "icon": "⚙️", "icon_img": "", "active": "checklist_admin",
                            "badge": 0})
    if user.get("is_owner"):
        nav.append({"label": "Sao lưu & Khôi phục", "route": "/sao-luu",
                    "icon": "💾", "icon_img": "", "active": "backup", "badge": 0})
    return nav
