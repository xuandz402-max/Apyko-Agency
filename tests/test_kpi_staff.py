"""Sheet Nhân sự ở /kpi: danh sách nhân sự + loại công việc tự thêm/sửa.

Sheet nằm dưới quyền KPI hiện hữu (Leader/Quản trị) — không thêm cờ sidebar
mới cho 1 tab. Nhân sự ở đây là danh bạ riêng, KHÔNG nối vào tài khoản
đăng nhập (bảng KPI xếp hạng vẫn tính theo tài khoản đăng nhập được giao
việc checklist); báo cáo nêu rõ điểm này."""

from conftest import activate, create_owner, create_staff, logout


def _leader(client):
    """Owner cũng là Leader (owner bypass mọi cổng leader)."""
    create_owner(client)


def test_kpi_staff_sheet_crud_and_job_type_manager(client):
    _leader(client)
    r = client.get("/kpi?sheet=nhan-su")
    assert r.status_code == 200
    # Loại có sẵn
    for t in ("Shopee", "TikTok", "Vận hành", "Kế toán"):
        assert f'<option value="{t}">{t}</option>' in r.text
    # Thêm nhân sự
    r = client.post(
        "/kpi/nhan-su/them",
        data={"name": "Nguyễn Văn A", "job_type": "Shopee"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = client.get("/kpi?sheet=nhan-su")
    assert "Nguyễn Văn A" in r.text and "Shopee" in r.text
    # Thêm loại công việc mới -> xuất hiện trong dropdown
    client.post("/kpi/loai-cong-viec/them", data={"name": "Livestream"})
    r = client.get("/kpi?sheet=nhan-su")
    assert '<option value="Livestream">Livestream</option>' in r.text
    # Đổi tên loại -> nhân sự dùng loại đó đổi theo
    client.post("/kpi/nhan-su/them", data={"name": "Trần Thị B", "job_type": "Livestream"})
    from app import database as db

    tid = db.kpi_job_types_custom()[0]["id"]
    client.post(f"/kpi/loai-cong-viec/{tid}/doi-ten", data={"name": "Live bán hàng"})
    r = client.get("/kpi?sheet=nhan-su")
    assert "Live bán hàng" in r.text
    assert "Trần Thị B" in r.text
    # Xóa loại đang có nhân sự dùng -> bị chặn, loại còn đó
    r = client.post(f"/kpi/loai-cong-viec/{tid}/xoa", follow_redirects=False)
    assert r.status_code == 303
    assert "Live bán hàng" in client.get("/kpi?sheet=nhan-su").text
    # Xóa nhân sự rồi xóa loại -> được
    staff = db.kpi_staff_list()
    for s in staff:
        client.post(f"/kpi/nhan-su/{s['id']}/xoa")
    client.post(f"/kpi/loai-cong-viec/{tid}/xoa")
    assert "Live bán hàng" not in client.get("/kpi?sheet=nhan-su").text


def test_kpi_staff_sheet_requires_leader(client):
    create_owner(client)
    code = create_staff(client, "nv_thuong", perms=("sidebar_products",))
    logout(client)
    activate(client, "nv_thuong", code)
    assert client.get("/kpi?sheet=nhan-su").status_code == 403
    assert client.post(
        "/kpi/nhan-su/them", data={"name": "X", "job_type": "Shopee"}
    ).status_code == 403


def test_kpi_ranking_tab_unaffected(client):
    _leader(client)
    r = client.get("/kpi")
    assert r.status_code == 200
    assert "Bảng xếp hạng" in r.text
    assert "Nhân sự" in r.text
