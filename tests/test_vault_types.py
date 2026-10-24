"""Loại tài khoản tự thêm ở Quản lý tài khoản: loại mới xuất hiện trong ô
'Loại tài khoản' của form tài khoản nội bộ; đổi tên lan sang tài khoản đang
dùng; xóa bị chặn khi còn tài khoản dùng loại đó. Loại có sẵn không xóa
được (không nằm trong bảng tự thêm)."""

from conftest import activate, create_owner, create_staff, logout


def _owner(client):
    create_owner(client)


def test_vault_custom_type_flows_into_kind_dropdown(client):
    _owner(client)
    r = client.get("/accounts?tab=noi-bo")
    assert r.status_code == 200
    assert "Loại tài khoản" in r.text
    # Thêm loại mới
    r = client.post(
        "/accounts/loai-tai-khoan/them", data={"name": "Canva"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = client.get("/accounts?tab=noi-bo")
    assert '<option value="Canva">Canva</option>' in r.text
    # Tạo tài khoản nội bộ dùng loại mới -> lưu đúng loại
    r = client.post(
        "/accounts/vault/create",
        data={"category": "noi_bo", "kind": "Canva", "label": "Canva Pro team"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = client.get("/accounts?tab=noi-bo")
    assert "Canva Pro team" in r.text
    # Đổi tên loại -> tài khoản đang dùng đổi theo
    from app import database as db

    tid = db.vault_type_names_custom()[0]["id"]
    client.post(f"/accounts/loai-tai-khoan/{tid}/doi-ten", data={"name": "Canva Pro"})
    r = client.get("/accounts?tab=noi-bo")
    assert "Canva Pro team" in r.text
    assert '<option value="Canva Pro">Canva Pro</option>' in r.text
    # Xóa loại đang có tài khoản dùng -> bị chặn
    client.post(f"/accounts/loai-tai-khoan/{tid}/xoa")
    r = client.get("/accounts?tab=noi-bo")
    assert '<option value="Canva Pro">Canva Pro</option>' in r.text
    # Xóa tài khoản rồi xóa loại -> được
    item = db.vault_list("noi_bo")[0]
    client.post(f"/accounts/vault/{item['id']}/delete")
    client.post(f"/accounts/loai-tai-khoan/{tid}/xoa")
    r = client.get("/accounts?tab=noi-bo")
    assert '<option value="Canva Pro">Canva Pro</option>' not in r.text


def test_vault_type_manager_requires_edit_permission(client):
    _owner(client)
    code = create_staff(client, "nv_xem_kho", perms=("sidebar_accounts",))
    logout(client)
    activate(client, "nv_xem_kho", code)
    # Chỉ xem kho, không có quyền sửa -> không thêm được loại
    assert client.post(
        "/accounts/loai-tai-khoan/them", data={"name": "X"}
    ).status_code == 403
    r = client.get("/accounts?tab=noi-bo")
    assert "Thêm loại tài khoản" not in r.text
