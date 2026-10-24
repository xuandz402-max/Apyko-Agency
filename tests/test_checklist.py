"""Daily Checklist: generate idempotent, trạng thái, nhắc hạn, phân quyền, board."""

from datetime import datetime
from zoneinfo import ZoneInfo

from conftest import activate, create_owner, create_staff, login, logout

VN = ZoneInfo("Asia/Ho_Chi_Minh")
MON = "2026-10-19"  # Thứ 2
TUE = "2026-10-20"  # Thứ 3


def _db():
    from app import database as db

    return db


def _cl():
    from app import checklist

    return checklist


def _vn(h, m, day=MON):
    y, mo, d = int(day[:4]), int(day[5:7]), int(day[8:10])
    return datetime(y, mo, d, h, m, tzinfo=VN)


def _owner_and_staff(client, staff_name="nv_a",
                      staff_perms=("sidebar_checklist", "sidebar_notifications")):
    """Tạo owner + 1 nhân sự đã kích hoạt. Trả về (db, cl, staff_user)."""
    create_owner(client)
    db = _db()
    code = create_staff(client, staff_name, perms=staff_perms)
    logout(client)
    activate(client, staff_name, code)
    staff = db.get_user_by_username(staff_name)
    logout(client)
    return db, _cl(), staff


def _assign_first_template_to(db, user_id):
    tpl = db.cl_template_list()[0]
    db.cl_template_update(tpl["id"], {"assignee_id": user_id})
    return tpl["id"]


# --- 1. generate tạo đủ 20 items -------------------------------------------


def test_generate_creates_20_items(client):
    create_owner(client)
    db, cl, _ = _db(), _cl(), None
    cl.seed_defaults()
    created = cl.generate_for_date(MON)
    assert created == 20
    assert db.cl_item_count(MON) == 20
    groups = {i["group_name"] for i in db.cl_item_list(MON)}
    assert len(groups) == 6


# --- 2. chạy lại không trùng ------------------------------------------------


def test_generate_idempotent(client):
    create_owner(client)
    db, cl, _ = _db(), _cl(), None
    cl.seed_defaults()
    assert cl.generate_for_date(MON) == 20
    assert cl.generate_for_date(MON) == 0
    assert db.cl_item_count(MON) == 20


# --- 3. complete lưu DB, đọc lại vẫn done ----------------------------------


def test_complete_persists(client):
    db, cl, staff = _owner_and_staff(client, "nv_a")
    tpl_id = _assign_first_template_to(db, staff["id"])
    cl.generate_for_date(MON)
    item = next(i for i in db.cl_item_list(MON) if i["template_id"] == tpl_id)
    login(client, "nv_a", "matkhau123")
    r = client.post(
        f"/api/checklist/items/{item['id']}/complete", json={"note": "đã kiểm tra xong"}
    )
    assert r.status_code == 200
    saved = db.cl_item_get(item["id"])
    assert saved["status"] == "done"
    assert saved["completed_by"] == "nv_a"
    assert saved["completed_at"]
    assert saved["note"] == "đã kiểm tra xong"
    # Trang checklist của nhân sự hiển thị bình thường
    assert client.get("/checklist").status_code == 200


# --- 4. đến hạn chuyển trạng thái + tạo đúng 1 thông báo --------------------


def test_due_and_overdue_notification(client):
    db, cl, staff = _owner_and_staff(client, "nv_b")
    # Item quá hạn: due 08:30, now 09:00
    tpl = db.cl_template_list()[0]  # due mặc định 08:30
    db.cl_template_update(tpl["id"], {"assignee_id": staff["id"]})
    cl.generate_for_date(MON)
    items = db.cl_item_list(MON)
    it_a = next(i for i in items if i["template_id"] == tpl["id"])
    # Item sắp đến hạn: due 10:00 -> now 09:00 nằm trong due_soon 30 phút
    tpl2 = next(t for t in db.cl_template_list() if t["due_time"] == "10:00")
    it_b = next(i for i in items if i["template_id"] == tpl2["id"])

    now = _vn(8, 45)
    assert cl.display_state(it_a, now) == "overdue"
    assert cl.display_state(it_b, now) == "pending"
    # Item due 09:00: cách hạn 15 phút <= due_soon 30 -> 'due'
    it_c = next(i for i in items if i["due_time"] == "09:00")
    assert cl.display_state(it_c, now) == "due"

    sent = cl.process_reminders(now)
    assert sent == 1
    notifs = db.notif_list(staff["id"])
    assert len(notifs) == 1
    assert "nv_b" in notifs[0]["body"]
    assert notifs[0]["item_id"] == it_a["id"]
    assert "/checklist?date=" in notifs[0]["link"]
    saved = db.cl_item_get(it_a["id"])
    assert saved["due_notified_at"]
    assert saved["reminder_count"] == 1
    # Chạy lại cùng mốc giờ: không gửi thêm
    assert cl.process_reminders(now) == 0
    assert len(db.notif_list(staff["id"])) == 1


# --- 5. quá hạn nhắc lại đúng chu kỳ, ngoài giờ thì dời ----------------------


def test_repeat_reminders_within_and_outside_work_hours(client):
    db, cl, staff = _owner_and_staff(client, "nv_c")
    tpl = db.cl_template_list()[0]  # 08:30
    db.cl_template_update(tpl["id"], {"assignee_id": staff["id"]})
    cl.generate_for_date(MON)
    assert cl.process_reminders(_vn(9, 0)) == 1  # lần đầu: đến hạn
    # +31 phút, vẫn trong giờ làm việc (08:00-17:30, T2): nhắc lần 2
    assert cl.process_reminders(_vn(9, 31)) == 1
    item = db.cl_item_list(MON, assignee_id=staff["id"])[0]
    assert item["reminder_count"] == 2
    # 23:00 ngoài giờ làm việc: không nhắc dù đã quá chu kỳ
    assert cl.process_reminders(_vn(23, 0)) == 0
    # Sáng hôm sau 08:05 (T3, trong giờ làm việc): nhắc tiếp
    assert cl.process_reminders(_vn(8, 5, day=TUE)) == 1
    assert len(db.notif_list(staff["id"])) == 3


# --- 6. complete / cancel dừng nhắc -----------------------------------------


def test_complete_or_cancel_stops_reminders(client):
    db, cl, staff = _owner_and_staff(client, "nv_d")
    tpls = db.cl_template_list()[:2]
    for t in tpls:
        db.cl_template_update(t["id"], {"assignee_id": staff["id"]})
    cl.generate_for_date(MON)
    assert cl.process_reminders(_vn(9, 0)) == 2
    items = db.cl_item_list(MON, assignee_id=staff["id"])
    db.cl_item_update(items[0]["id"], {"status": "done", "completed_by": "nv_d"})
    db.cl_item_update(items[1]["id"], {"status": "cancelled"})
    assert cl.process_reminders(_vn(9, 31)) == 0
    assert cl.process_reminders(_vn(23, 0)) == 0
    assert len(db.notif_list(staff["id"])) == 2


# --- 7. thông báo riêng tư theo user ----------------------------------------


def test_notifications_privacy(client):
    db, cl, staff_a = _owner_and_staff(client, "nv_e")
    login(client, "chushop", "matkhau123")
    code = create_staff(client, "nv_f", perms=("sidebar_checklist", "sidebar_notifications"))
    logout(client)
    activate(client, "nv_f", code)
    staff_b = db.get_user_by_username("nv_f")
    logout(client)
    tpl = db.cl_template_list()[0]
    db.cl_template_update(tpl["id"], {"assignee_id": staff_a["id"]})
    cl.generate_for_date(MON)
    cl.process_reminders(_vn(9, 0))
    notifs_a = db.notif_list(staff_a["id"])
    assert len(notifs_a) == 1

    login(client, "nv_f", "matkhau123")
    r = client.get("/api/notifications")
    assert r.status_code == 200
    assert all(n["id"] != notifs_a[0]["id"] for n in r.json()["notifications"])
    # B đọc thông báo của A -> 403
    assert client.post(f"/api/notifications/{notifs_a[0]['id']}/read").status_code == 403
    logout(client)

    login(client, "nv_e", "matkhau123")
    assert client.post(f"/api/notifications/{notifs_a[0]['id']}/read").status_code == 200
    assert db.notif_unread_count(staff_a["id"]) == 0
    assert db.notif_unread_count(staff_b["id"]) == 0


# --- 8. khởi động lại (init_db lại) không mất/không trùng ---------------------


def test_restart_keeps_state(client):
    db, cl, staff = _owner_and_staff(client, "nv_g")
    tpl = db.cl_template_list()[0]
    db.cl_template_update(tpl["id"], {"assignee_id": staff["id"]})
    cl.generate_for_date(MON)
    cl.process_reminders(_vn(9, 0))
    item_before = db.cl_item_list(MON, assignee_id=staff["id"])[0]

    # Mô phỏng khởi động lại server: init_db chạy lại
    db.init_db()

    assert db.cl_item_count(MON) == 20
    assert len(db.cl_template_list()) == 20
    item_after = db.cl_item_list(MON, assignee_id=staff["id"])[0]
    assert item_after["due_notified_at"] == item_before["due_notified_at"]
    assert item_after["reminder_count"] == 1
    assert db.cl_item_count(MON) == 20  # seed không nhân đôi
    # Chạy nhắc lại cùng mốc giờ: không trùng
    assert cl.process_reminders(_vn(9, 0)) == 0


# --- 9. không truy cập chéo trái quyền ---------------------------------------


def test_cross_user_forbidden(client):
    db, cl, staff_a = _owner_and_staff(client, "nv_h")
    login(client, "chushop", "matkhau123")
    code = create_staff(client, "nv_i", perms=("sidebar_checklist",))
    logout(client)
    activate(client, "nv_i", code)
    logout(client)

    # Mẫu riêng gán cho A
    login(client, "chushop", "matkhau123")
    r = client.post(
        "/api/checklist/templates",
        json={
            "group_name": "Riêng",
            "title": "VIỆC-RIÊNG-CỦA-A-XYZ",
            "due_time": "09:00",
            "sort": 9999,
            "assignee_id": staff_a["id"],
        },
    )
    assert r.status_code == 201
    cl.generate_for_date(MON)
    logout(client)

    login(client, "nv_i", "matkhau123")
    item_a = next(i for i in db.cl_item_list(MON) if i["title"] == "VIỆC-RIÊNG-CỦA-A-XYZ")
    # B hoàn thành việc của A -> 403
    assert client.post(f"/api/checklist/items/{item_a['id']}/complete", json={}).status_code == 403
    # Trang checklist của B không chứa việc của A
    page = client.get("/checklist")
    assert page.status_code == 200
    assert "VIỆC-RIÊNG-CỦA-A-XYZ" not in page.text
    # B không vào board/admin được
    assert client.get("/checklist/board").status_code == 403
    assert client.get("/checklist/admin").status_code == 403
    assert client.post("/api/checklist/generate", json={}).status_code == 403


# --- leader / admin: board + quản lý mẫu/shop/cài đặt -------------------------


def test_leader_board_and_admin_crud(client):
    db, cl, _ = _owner_and_staff(
        client, "leader1", staff_perms=("can_checklist_leader", "sidebar_checklist")
    )
    # Owner gán mẫu cho nhân sự rồi tạo việc
    login(client, "chushop", "matkhau123")
    code = create_staff(client, "nv_j", perms=("sidebar_checklist",))
    activate(client, "nv_j", code)
    staff_j = db.get_user_by_username("nv_j")
    tpl = db.cl_template_list()[0]
    db.cl_template_update(tpl["id"], {"assignee_id": staff_j["id"]})
    cl.generate_for_date(MON)
    item = db.cl_item_list(MON, assignee_id=staff_j["id"])[0]
    db.cl_item_update(item["id"], {"status": "done", "completed_by": "nv_j"})
    logout(client)

    login(client, "leader1", "matkhau123")
    stats = cl.board_stats(MON)
    assert stats["total"] == 20
    assert stats["done"] == 1
    assert stats["unfinished"] == 19
    assert client.get("/checklist/board").status_code == 200
    # Leader xem việc chưa xong của nhân sự qua filter
    page = client.get(f"/checklist?date={MON}&assignee={staff_j['id']}")
    assert page.status_code == 200
    assert client.get("/checklist/admin").status_code == 403  # leader không phải admin

    # Owner (admin) quản lý mẫu/shop/cài đặt
    logout(client)
    login(client, "chushop", "matkhau123")
    r = client.post("/api/checklist/shops", json={"name": "Shop Test"})
    assert r.status_code == 201
    shop_id = r.json()["id"]
    r = client.post(
        "/api/checklist/templates",
        json={
            "group_name": "T",
            "title": "Mẫu mới",
            "due_time": "08:00",
            "sort": 5,
            "shop_id": shop_id,
        },
    )
    assert r.status_code == 201
    tid = r.json()["id"]
    # Xóa shop đang được mẫu tham chiếu -> chặn 409
    assert client.delete(f"/api/checklist/shops/{shop_id}").status_code == 409
    # Đổi giờ hạn sai định dạng -> 422
    assert client.put(f"/api/checklist/templates/{tid}", json={"due_time": "9h"}).status_code == 422
    assert (
        client.put(f"/api/checklist/templates/{tid}", json={"due_time": "08:15"}).status_code == 200
    )
    # Tắt/bật mẫu
    assert client.post(f"/api/checklist/templates/{tid}/toggle").status_code == 200
    # Cài đặt: sai giờ -> 422; đúng -> 200
    assert client.put("/api/checklist/settings", json={"work_start": "8h"}).status_code == 422
    r = client.put(
        "/api/checklist/settings",
        json={
            "work_start": "08:00",
            "work_end": "17:00",
            "work_days": "1,2,3,4,5",
            "reminder_interval_min": 45,
            "due_soon_min": 15,
        },
    )
    assert r.status_code == 200
    assert r.json()["settings"]["reminder_interval_min"] == "45"


def test_notifications_page_flow(client):
    db, cl, staff = _owner_and_staff(client, "nv_k")
    tpl = db.cl_template_list()[0]
    db.cl_template_update(tpl["id"], {"assignee_id": staff["id"]})
    cl.generate_for_date(MON)
    cl.process_reminders(_vn(9, 0))
    login(client, "nv_k", "matkhau123")
    r = client.get("/thong-bao")
    assert r.status_code == 200
    assert "Việc đến hạn" in r.text
    # Mở trang có safety-net dùng giờ thật nên số thông báo có thể > 1
    # (việc hôm nay đến hạn + nhắc lại). Chỉ kiểm chứng read-all xử lý hết.
    before = db.notif_unread_count(staff["id"])
    assert before >= 1
    r = client.post("/api/notifications/read-all")
    assert r.json()["updated"] == before
    assert db.notif_unread_count(staff["id"]) == 0


# --- hiển thị trạng thái: dấu ✓ xanh / ✕ đỏ trước tiêu đề, không gạch ngang ---


def test_checklist_page_status_marks(client):
    create_owner(client)
    db, cl = _db(), _cl()
    cl.seed_defaults()
    cl.generate_for_date(MON)
    items = db.cl_item_list(MON)
    assert items
    # Owner hoàn thành 1 việc; các việc còn lại của ngày đã qua -> quá hạn.
    r = client.post(
        f"/api/checklist/items/{items[0]['id']}/complete", json={"note": "ok"}
    )
    assert r.status_code == 200
    r = client.get(f"/checklist?date={MON}")
    assert r.status_code == 200
    html = r.text
    # Việc đã xong: ký tự ✓ mang class màu xanh lá + nhãn ĐÃ XONG.
    assert 'cl-mark cl-mark-done' in html and "✓" in html
    assert "ĐÃ XONG" in html
    # Việc quá hạn: ký tự ✕ mang class màu đỏ + nhãn QUÁ HẠN.
    assert 'cl-mark cl-mark-over' in html and "✕" in html
    assert "QUÁ HẠN" in html


def test_checklist_css_marks_and_no_line_through():
    import pathlib
    import re

    css_path = pathlib.Path(__file__).resolve().parent.parent / "static" / "style.css"
    css = css_path.read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    # Không rule cl- nào được gạch ngang chữ nữa.
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if "cl-" in sel:
            assert "line-through" not in body, sel
    # Tiêu đề việc: đậm 700 + đen #111 ở mọi trạng thái.
    title = re.search(r"\.cl-title\s*\{([^}]*)\}", css)
    assert title and "font-weight: 700" in title.group(1)
    assert "color: #111" in title.group(1)
    # Dấu ✓ xanh #15803D, dấu ✕ đỏ #DC2626.
    done = re.search(r"\.cl-mark-done\s*\{([^}]*)\}", css)
    assert done and "#15803D" in done.group(1)
    over = re.search(r"\.cl-mark-over\s*\{([^}]*)\}", css)
    assert over and "#DC2626" in over.group(1)
