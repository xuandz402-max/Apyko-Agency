"""Module TikTok Onboard: danh mục 46 việc/5 giai đoạn nguyên văn từ file
Excel, tiến độ theo mã việc, validate Hoàn tất/Không áp dụng theo sheet
thiết kế, nhật ký đổi trạng thái và phân quyền."""

import json
import os

from conftest import activate, create_owner, create_staff, logout

_CATALOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app",
    "data",
    "tiktok_onboard.json",
)


def _db():
    from app import database as db

    return db


def _tt():
    from app import tiktok

    return tiktok


def _update(**overrides):
    base = {
        "code": "TT-001",
        "status": "Đang làm",
        "assignee": "Bạn A",
        "due": "",
        "evidence": "",
        "note": "",
    }
    base.update(overrides)
    return base


# ------------------------------ danh mục tĩnh ------------------------------


def test_catalog_has_46_tasks_5_phases_sequential_codes():
    tt = _tt()
    catalog = tt.load_catalog()
    assert len(catalog["phases"]) == 5
    assert len(catalog["tasks"]) == 46
    codes = [t["code"] for t in catalog["tasks"]]
    assert codes == [f"TT-{i:03d}" for i in range(1, 47)]
    assert [p["name"] for p in tt.list_phases()] == [
        "Chuẩn bị",
        "Cài đặt",
        "Vận hành",
        "Báo cáo",
        "Phối hợp liên nhóm",
    ]
    with open(_CATALOG_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["tasks"][15]["code"] == "TT-016"
    assert raw["tasks"][15]["title"] == (
        "Đạt 50 video mới cho 1 sản phẩm được coi là tối ưu"
    )


def test_validate_done_requires_evidence_or_note():
    tt = _tt()
    _clean, errors = tt.validate_progress_payload(_update(status="Hoàn tất"))
    assert "evidence" in errors
    clean, errors = tt.validate_progress_payload(
        _update(status="Hoàn tất", evidence="https://example.com/bang-chung")
    )
    assert errors == {}
    assert clean["status"] == "Hoàn tất"
    _clean, errors = tt.validate_progress_payload(
        _update(status="Hoàn tất", note="Đã xác nhận miệng với quản lý")
    )
    assert errors == {}


def test_validate_na_requires_note():
    tt = _tt()
    _clean, errors = tt.validate_progress_payload(_update(status="Không áp dụng"))
    assert "note" in errors
    _clean, errors = tt.validate_progress_payload(
        _update(status="Không áp dụng", note="Shop không chạy mục này")
    )
    assert errors == {}


# ------------------------------ hiển thị trang ------------------------------


def test_page_renders_phases_and_task_titles(client):
    create_owner(client)
    r = client.get("/tiktok-onboard")
    assert r.status_code == 200
    for name in ["Chuẩn bị", "Cài đặt", "Vận hành", "Báo cáo", "Phối hợp liên nhóm"]:
        assert name in r.text
    assert "Đạt 50 video mới cho 1 sản phẩm được coi là tối ưu" in r.text
    assert "TT-046" in r.text
    assert "0/46 việc hoàn tất" in r.text
    assert 'href="/tiktok-onboard"' in r.text  # mục menu ở sidebar


def test_filter_by_phase(client):
    create_owner(client)
    r = client.get("/tiktok-onboard", params={"phase": "Vận hành"})
    assert r.status_code == 200
    assert "Đạt 50 video mới cho 1 sản phẩm được coi là tối ưu" in r.text
    assert "Biên bản bàn giao" not in r.text  # việc của giai đoạn Chuẩn bị


def test_filter_by_keyword(client):
    create_owner(client)
    r = client.get("/tiktok-onboard", params={"q": "TT-016"})
    assert r.status_code == 200
    assert "Đạt 50 video mới cho 1 sản phẩm được coi là tối ưu" in r.text
    assert "Biên bản bàn giao" not in r.text


# ------------------------------ cập nhật tiến độ ------------------------------


def test_update_done_without_evidence_rejected(client):
    create_owner(client)
    db = _db()
    r = client.post(
        "/tiktok-onboard/update",
        data=_update(status="Hoàn tất"),
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "err=" in r.headers["location"]
    assert db.tt_get_progress("TT-001") is None
    assert db.tt_history_list() == []


def test_update_done_with_evidence_saves_and_writes_history(client):
    create_owner(client)
    db = _db()
    r = client.post(
        "/tiktok-onboard/update",
        data=_update(
            status="Hoàn tất",
            evidence="https://example.com/bien-ban",
            due="2026-11-01",
        ),
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "err=" not in r.headers["location"]
    prog = db.tt_get_progress("TT-001")
    assert prog["status"] == "Hoàn tất"
    assert prog["evidence"] == "https://example.com/bien-ban"
    assert prog["due"] == "2026-11-01"
    assert prog["assignee"] == "Bạn A"
    history = db.tt_history_list()
    assert len(history) == 1
    assert history[0]["code"] == "TT-001"
    assert history[0]["old_status"] == "Chưa bắt đầu"
    assert history[0]["new_status"] == "Hoàn tất"

    r = client.get("/tiktok-onboard")
    assert "1/46 việc hoàn tất" in r.text
    assert "01/11/2026" in r.text  # hạn hiển thị DD/MM/YYYY

    r = client.get("/tiktok-onboard", params={"tab": "lich-su"})
    assert r.status_code == 200
    assert "Hoàn tất" in r.text
    assert "Biên bản bàn giao" in r.text


def test_update_same_status_does_not_write_history(client):
    create_owner(client)
    db = _db()
    client.post("/tiktok-onboard/update", data=_update(), follow_redirects=False)
    client.post(
        "/tiktok-onboard/update",
        data=_update(assignee="Bạn B"),
        follow_redirects=False,
    )
    # Đổi người phụ trách nhưng giữ trạng thái -> chỉ 1 dòng nhật ký (lần đầu)
    assert len(db.tt_history_list()) == 1
    assert db.tt_get_progress("TT-001")["assignee"] == "Bạn B"


def test_update_na_without_note_rejected(client):
    create_owner(client)
    db = _db()
    r = client.post(
        "/tiktok-onboard/update",
        data=_update(status="Không áp dụng"),
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "err=" in r.headers["location"]
    assert db.tt_get_progress("TT-001") is None

    r = client.post(
        "/tiktok-onboard/update",
        data=_update(status="Không áp dụng", note="Shop không thuộc diện Mall"),
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert db.tt_get_progress("TT-001")["status"] == "Không áp dụng"
    r = client.get("/tiktok-onboard")
    assert "1 việc không áp dụng" in r.text


# ------------------------------ phân quyền ------------------------------


def test_view_and_write_permissions(client):
    create_owner(client)
    code_view = create_staff(client, "nv_tt_view", perms=("can_view_tiktok",))
    code_no_view = create_staff(client, "nv_tt_no_view", perms=())
    # Chỉ xem: xem được trang, POST cập nhật bị 403
    logout(client)
    activate(client, "nv_tt_view", code_view)
    assert client.get("/tiktok-onboard").status_code == 200
    r = client.post(
        "/tiktok-onboard/update", data=_update(), follow_redirects=False
    )
    assert r.status_code == 403
    # Không quyền xem: GET cũng 403
    logout(client)
    activate(client, "nv_tt_no_view", code_no_view)
    assert client.get("/tiktok-onboard").status_code == 403
