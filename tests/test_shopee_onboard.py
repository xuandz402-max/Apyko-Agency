"""Module Shopee Onboard: danh mục 43 việc/7 giai đoạn nguyên văn từ file
Excel, các tab tham khảo (Lộ trình, Kế hoạch tuần, Shop công ty & khách,
Đánh giá), tiến độ theo mã việc, validate Hoàn tất/Không áp dụng, nhật ký
đổi trạng thái và phân quyền theo registry sidebar (tự động)."""

# ruff: noqa: RUF001, E501 — các chuỗi nguyên văn từ file user gửi chứa
# dấu gạch ngang dài và vượt độ dài dòng; đó là nội dung, không được sửa.

import json
import os

from conftest import activate, create_owner, create_staff, logout

_CATALOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app",
    "data",
    "shopee_onboard.json",
)


def _db():
    from app import database as db

    return db


def _sp():
    from app import shopee

    return shopee


def _update(**overrides):
    base = {
        "code": "SP-001",
        "status": "Đang làm",
        "assignee": "Bạn A",
        "due": "",
        "evidence": "",
        "note": "",
    }
    base.update(overrides)
    return base


# ------------------------------ danh mục tĩnh ------------------------------


def test_catalog_has_43_tasks_7_phases_sequential_codes():
    sp = _sp()
    catalog = sp.load_catalog()
    assert len(catalog["phases"]) == 7
    assert len(catalog["tasks"]) == 43
    codes = [t["code"] for t in catalog["tasks"]]
    assert codes == [f"SP-{i:03d}" for i in range(1, 44)]
    assert [p["name"] for p in sp.list_phases()] == [
        "1. Nhận shop",
        "2. Setup nền tảng",
        "3. Cơ cấu & tối ưu sản phẩm",
        "4. Seeding & Affiliate",
        "5. Video & Livestream",
        "6. Quảng cáo & chiến dịch",
        "7. Báo cáo & phối hợp",
    ]
    from collections import Counter

    assert dict(Counter(t["phase"] for t in catalog["tasks"])) == {
        "1. Nhận shop": 4,
        "2. Setup nền tảng": 8,
        "3. Cơ cấu & tối ưu sản phẩm": 15,
        "4. Seeding & Affiliate": 2,
        "5. Video & Livestream": 3,
        "6. Quảng cáo & chiến dịch": 4,
        "7. Báo cáo & phối hợp": 7,
    }


# 2 việc mỗi giai đoạn, đối chiếu NGUYÊN VĂN toàn bộ ô (title/goal/guide/
# evidence/frequency/owner_hint/review_note) với file nguồn.
_SPOT = {
    "SP-001": ("Nhận shop – shop mới MKT City",
               "Biết rõ shop đang tiếp nhận và người chịu trách nhiệm.",
               "Ghi tên shop, loại shop (công ty/khách hàng), Team Lead phụ trách, đầu mối khách hàng, ngày bắt đầu và kênh trao đổi.",
               "Phiếu nhận shop và đầu mối được xác nhận.",
               "Ngày đầu nhận shop", "Nhân sự mới + Team Lead",
               "Shop mới phải báo cáo Team Lead phụ trách."),
    "SP-003": ("Xin thông tin từ khách hàng",
               "Thu thập đủ đầu vào để không phải đoán khi setup.",
               "Dùng danh sách yêu cầu: thông tin shop, SKU, giá, tồn, kho, nội dung, ảnh/video, lịch sale, quyền truy cập, báo cáo, mục tiêu và người duyệt; ghi phần thiếu/người cung cấp/hạn.",
               "Danh sách đầu vào có trạng thái nhận/thiếu và ngày cập nhật.",
               "Khi onboard shop khách hàng", "Account/nhân sự vận hành",
               "Nếu thiếu dữ liệu hoặc quyền, báo Team Lead và chờ bổ sung."),
    "SP-005": ("Setup kho hàng",
               "Thiết lập quy trình/đầu mối kho để tồn và xử lý hàng đúng.",
               "Xác định kho, nguồn tồn chính thức, SKU, người cập nhật, cách báo tồn thấp và đầu mối xử lý.",
               "Danh sách kho/đầu mối/nguồn tồn; cách đối chiếu đã thống nhất.",
               "Khi setup shop mới; rà soát khi có thay đổi", "Vận hành + kho",
               "Không tự tạo hoặc sửa tồn nếu chưa được giao quyền."),
    "SP-011": ("Thiết lập xu thưởng",
               "Cài xu thưởng theo chương trình shop đã chọn.",
               "Xác nhận đối tượng, mức áp dụng, thời gian và điều kiện theo kế hoạch; rà cấu hình.",
               "Link/capture và thời gian áp dụng.",
               "Nếu có trong kế hoạch", "Vận hành",
               "Duyệt chi phí/điều kiện trước khi bật."),
    "SP-013": ("Rà cơ cấu sản phẩm",
               "Biết SKU trọng tâm, SKU bổ trợ và sản phẩm cần ưu tiên.",
               "Dựa trên danh mục, dữ liệu bán, tồn, mục tiêu và vai trò sản phẩm; ghi nhận đề xuất thay đổi cơ cấu.",
               "Danh sách SKU nhóm theo ưu tiên và lý do.",
               "Khi onboard; rà soát định kỳ", "Vận hành + ngành hàng",
               "Đề xuất được Team Lead/khách xác nhận trước thay đổi lớn."),
    "SP-027": ("Kiểm tra ảnh bìa và phân loại sản phẩm",
               "Đảm bảo ảnh bìa đúng, phân loại/biến thể chính xác.",
               "Rà SKU, ảnh đại diện, màu/size/biến thể, tên và danh mục; ghi lỗi và yêu cầu sửa.",
               "Danh sách SKU lỗi/đạt; link/capture.",
               "Khi rà soát sản phẩm", "Vận hành + nội dung",
               "Duyệt thay đổi nội dung/thuộc tính nếu cần."),
    "SP-028": ("Seeding sản phẩm nếu có",
               "Tạo nội dung/trải nghiệm thật để hỗ trợ nhận biết sản phẩm.",
               "Xác định SKU, mục tiêu, người tham gia, mẫu thật nếu có, nội dung, lịch và cách đo; theo dõi bài đăng.",
               "Kế hoạch được duyệt, link nội dung, kết quả có nguồn.",
               "Nếu có kế hoạch", "Vận hành + marketing",
               "Không tạo đơn/đánh giá/tương tác giả; xin duyệt chi phí và mẫu."),
    "SP-029": ("Mở Affiliate và setup campaign",
               "Kết nối sản phẩm với hoạt động Affiliate phù hợp.",
               "Chọn sản phẩm/campaign; xác nhận mức hoa hồng 10–12% theo thông tin đã chốt; ghi thời gian và điều kiện.",
               "Cấu hình campaign, sản phẩm, mức hoa hồng và link kiểm tra.",
               "Theo kế hoạch Affiliate", "Vận hành Affiliate",
               "Mức 10–12% đã được anh xác nhận; người có quyền duyệt trước khi bật."),
    "SP-030": ("Đăng video",
               "Đăng video đúng lịch và gắn sản phẩm/link khi cần.",
               "Dùng nội dung đã duyệt; kiểm tra caption, hashtag, link sản phẩm, lịch đăng và hiển thị.",
               "URL video, ngày đăng và kiểm tra link.",
               "Theo lịch nội dung; nếu có nhịp hằng ngày thì theo kế hoạch kênh",
               "Nội dung + vận hành",
               "Duyệt nội dung/claim và quyền sử dụng."),
    "SP-032": ("Livestream",
               "Chuẩn bị buổi livestream theo kế hoạch shop.",
               "Chốt lịch, host, SKU, tồn, ưu đãi, kịch bản, link và đầu mối xử lý; tổng kết sau buổi.",
               "Checklist trước live, link/bản ghi và báo cáo kết quả.",
               "Theo lịch livestream", "Vận hành + nội dung/host",
               "Duyệt kịch bản/ưu đãi/chi phí nếu có."),
    "SP-033": ("Chạy quảng cáo Shopee",
               "Triển khai quảng cáo theo mục tiêu, ngân sách và thời hạn được duyệt.",
               "Xác nhận sản phẩm, mục tiêu, từ khóa, ngân sách, lịch và tiêu chí theo dõi; ghi trạng thái theo nhịp.",
               "Link/capture cài đặt, ngân sách, kết quả và nguồn số liệu.",
               "Theo campaign; theo dõi khi đang chạy", "Vận hành Ads",
               "Ngân sách cần phê duyệt; nhân sự mới không tự tăng ngân sách."),
    "SP-036": ("Trực Spike Day",
               "Đảm bảo shop được theo dõi trong ngày cao điểm.",
               "Chốt lịch trực; kiểm tra hàng, giá, nội dung, ads, ưu đãi và đầu mối sự cố; ghi nhật ký trong ca.",
               "Lịch trực, checklist trước ngày và nhật ký ca.",
               "Mỗi Spike Day", "Vận hành + kho + CS",
               "Team Lead phân ca và đầu mối escalation."),
    "SP-037": ("Lập kế hoạch ngày/campaign",
               "Chuyển mục tiêu thành việc có người, hạn và đầu ra.",
               "Ghi mục tiêu, SKU, hoạt động, thời gian, phụ thuộc, người làm và người duyệt.",
               "Kế hoạch có trạng thái, người duyệt và bước tiếp theo.",
               "Hằng ngày / trước campaign", "Vận hành + Team Lead", ""),
    "SP-043": ("Banner, quà tặng, thông báo tồn, Star Shop, booking, AFF",
               "Điều phối các hạng mục phối hợp có phát sinh trong shop/campaign.",
               "Xác nhận mục nào áp dụng; giao người phụ trách, lịch, thông tin, nội dung và cách kiểm tra kết quả.",
               "Kế hoạch/link, trạng thái, người nhận và kết quả.",
               "Nếu có / theo campaign", "Vận hành + nhóm liên quan",
               "Chương trình/chi phí/ưu đãi cần người có quyền duyệt."),
}


def test_verbatim_spot_checks_two_tasks_per_phase():
    sp = _sp()
    by_code = {t["code"]: t for t in sp.list_tasks()}
    keys = ["title", "goal", "guide", "evidence", "frequency", "owner_hint",
            "review_note"]
    for code, expected in _SPOT.items():
        task = by_code[code]
        assert tuple(task[k] for k in keys) == expected, code


def test_reference_sheets_counts_and_titles():
    sp = _sp()
    catalog = sp.load_catalog()
    rm = catalog["roadmap"]
    assert rm["title"] == "Lộ trình onboard Shopee | 1 tháng thử việc"
    assert rm["duration"] == ""
    assert [w["week"] for w in rm["weeks"]] == ["TUẦN 1", "TUẦN 2", "TUẦN 3", "TUẦN 4"]
    assert [w["title"] for w in rm["weeks"]] == [
        "NHẬN & HIỂU SHOP",
        "SETUP NỀN TẢNG",
        "KÍCH HOẠT BÁN HÀNG",
        "TỐI ƯU & ĐÁNH GIÁ",
    ]
    assert [r["label"] for r in rm["quick_view_rows"]] == [
        "Bạn hiểu", "Bạn thực hành", "Minh chứng",
    ]
    assert rm["quick_view_rows"][0]["week_values"][0] == (
        "Biết mục tiêu, phạm vi, người phụ trách và sản phẩm."
    )
    assert len(catalog["weekly"]["rows"]) == 7
    assert catalog["weekly"]["rows"][0][0] == "Tuần 1 • Ngày 1"
    assert catalog["weekly"]["rows"][-1][0] == "Cuối tháng"
    assert len(catalog["compare"]["rows"]) == 6
    assert catalog["compare"]["rows"][0][0] == "Mục tiêu/phạm vi"
    assert len(catalog["eval"]["competencies"]) == 7
    assert catalog["eval"]["competencies"][0][0] == "Hiểu shop"
    assert catalog["eval"]["open_fields"] == [
        "Phạm vi có thể tự phụ trách:",
        "Phần cần đào tạo thêm:",
        "Kết luận / ngày rà soát:",
    ]
    with open(_CATALOG_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["tasks"][0]["code"] == "SP-001"
    assert raw["roadmap"]["weeks"][0]["title"] == "NHẬN & HIỂU SHOP"


def test_validate_done_requires_evidence_or_note():
    sp = _sp()
    _clean, errors = sp.validate_progress_payload(_update(status="Hoàn tất"))
    assert "evidence" in errors
    clean, errors = sp.validate_progress_payload(
        _update(status="Hoàn tất", evidence="https://example.com/bang-chung")
    )
    assert errors == {}
    assert clean["status"] == "Hoàn tất"
    _clean, errors = sp.validate_progress_payload(
        _update(status="Hoàn tất", note="Đã xác nhận miệng với quản lý")
    )
    assert errors == {}


def test_validate_na_requires_note():
    sp = _sp()
    _clean, errors = sp.validate_progress_payload(_update(status="Không áp dụng"))
    assert "note" in errors
    _clean, errors = sp.validate_progress_payload(
        _update(status="Không áp dụng", note="Shop không chạy mục này")
    )
    assert errors == {}


# ------------------------------ hiển thị trang ------------------------------


def test_page_renders_phases_and_task_titles(client):
    create_owner(client)
    r = client.get("/shopee-onboard")
    assert r.status_code == 200
    for name in ["1. Nhận shop", "2. Setup nền tảng",
                 # Jinja escape & thành &amp; trong HTML
                 "3. Cơ cấu &amp; tối ưu sản phẩm", "7. Báo cáo &amp; phối hợp"]:
        assert name in r.text
    assert "Nhận shop – shop mới MKT City" in r.text
    assert "SP-043" in r.text
    assert "0/43 việc hoàn tất" in r.text
    assert 'href="/shopee-onboard"' in r.text  # mục menu ở sidebar


def test_filter_by_phase(client):
    create_owner(client)
    r = client.get("/shopee-onboard", params={"phase": "2. Setup nền tảng"})
    assert r.status_code == 200
    assert "Setup kho hàng" in r.text
    assert "Nhận shop – shop mới MKT City" not in r.text


def test_filter_by_keyword(client):
    create_owner(client)
    r = client.get("/shopee-onboard", params={"q": "SP-029"})
    assert r.status_code == 200
    assert "Mở Affiliate và setup campaign" in r.text
    assert "Nhận shop – shop mới MKT City" not in r.text


def test_all_reference_tabs_render(client):
    create_owner(client)
    cases = [
        ("lo-trinh", "NHẬN &amp; HIỂU SHOP"),
        ("lo-trinh", "Quy tắc dễ nhớ"),
        ("ke-hoach-tuan", "Tuần 1 • Ngày 1"),
        ("ke-hoach-tuan", "Nhận shop và thông tin shop"),
        ("shop", "Hai nhánh tiếp nhận shop"),
        ("shop", "Shop khách hàng"),
        ("danh-gia", "Hiểu shop"),
        ("danh-gia", "Kết luận thử việc"),
        ("danh-gia", "Phạm vi có thể tự phụ trách:"),
        ("lich-su", "Chưa có thay đổi trạng thái nào."),
    ]
    for tab, marker in cases:
        r = client.get("/shopee-onboard", params={"tab": tab})
        assert r.status_code == 200, tab
        assert marker in r.text, (tab, marker)


# ------------------------------ cập nhật tiến độ ------------------------------


def test_update_done_without_evidence_rejected(client):
    create_owner(client)
    db = _db()
    r = client.post(
        "/shopee-onboard/update",
        data=_update(status="Hoàn tất"),
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "err=" in r.headers["location"]
    assert db.sp_get_progress("SP-001") is None
    assert db.sp_history_list() == []


def test_update_done_with_evidence_saves_and_writes_history(client):
    create_owner(client)
    db = _db()
    r = client.post(
        "/shopee-onboard/update",
        data=_update(
            status="Hoàn tất",
            evidence="https://example.com/phieu-nhan",
            due="2026-11-01",
        ),
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "err=" not in r.headers["location"]
    prog = db.sp_get_progress("SP-001")
    assert prog["status"] == "Hoàn tất"
    assert prog["evidence"] == "https://example.com/phieu-nhan"
    assert prog["due"] == "2026-11-01"
    assert prog["assignee"] == "Bạn A"
    history = db.sp_history_list()
    assert len(history) == 1
    assert history[0]["code"] == "SP-001"
    assert history[0]["old_status"] == "Chưa bắt đầu"
    assert history[0]["new_status"] == "Hoàn tất"

    r = client.get("/shopee-onboard")
    assert "1/43 việc hoàn tất" in r.text
    assert "01/11/2026" in r.text  # hạn hiển thị DD/MM/YYYY

    r = client.get("/shopee-onboard", params={"tab": "lich-su"})
    assert r.status_code == 200
    assert "Hoàn tất" in r.text
    assert "Nhận shop – shop mới MKT City" in r.text


def test_update_same_status_does_not_write_history(client):
    create_owner(client)
    db = _db()
    client.post("/shopee-onboard/update", data=_update(), follow_redirects=False)
    client.post(
        "/shopee-onboard/update", data=_update(assignee="Bạn B"),
        follow_redirects=False,
    )
    # Đổi người phụ trách nhưng giữ trạng thái -> chỉ 1 dòng nhật ký (lần đầu)
    assert len(db.sp_history_list()) == 1
    assert db.sp_get_progress("SP-001")["assignee"] == "Bạn B"


def test_update_na_without_note_rejected(client):
    create_owner(client)
    db = _db()
    r = client.post(
        "/shopee-onboard/update",
        data=_update(status="Không áp dụng"),
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "err=" in r.headers["location"]
    assert db.sp_get_progress("SP-001") is None

    r = client.post(
        "/shopee-onboard/update",
        data=_update(status="Không áp dụng", note="Shop không chạy mục này"),
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert db.sp_get_progress("SP-001")["status"] == "Không áp dụng"
    r = client.get("/shopee-onboard")
    assert "1 việc không áp dụng" in r.text


# ------------------------------ phân quyền ------------------------------


def test_sidebar_registry_position_and_auto_permission(client):
    from app import sidebar as sb

    ids = sb.all_ids()
    # Shopee Onboard nằm ngay sau TikTok Onboard trong registry
    assert ids.index("shopee_onboard") == ids.index("tiktok") + 1
    item = sb.by_id("shopee_onboard")
    assert item["label"] == "Shopee Onboard"
    assert item["route"] == "/shopee-onboard"
    assert item["icon_img"] == "/static/shopee-icon.svg"
    # Checkbox phân quyền tự sinh từ registry entry, không cần cờ tay
    create_owner(client)
    r = client.get("/accounts")
    assert 'name="sidebar_shopee_onboard"' in r.text
    assert "Xem Shopee Onboard" in r.text


def test_view_and_write_permissions(client):
    create_owner(client)
    code_view = create_staff(client, "nv_sp_view", perms=("sidebar_shopee_onboard",))
    code_no_view = create_staff(client, "nv_sp_no_view", perms=())
    # Chỉ xem: xem được trang, POST cập nhật bị 403
    logout(client)
    activate(client, "nv_sp_view", code_view)
    assert client.get("/shopee-onboard").status_code == 200
    r = client.post(
        "/shopee-onboard/update", data=_update(), follow_redirects=False
    )
    assert r.status_code == 403
    # Không quyền xem: GET cũng 403
    logout(client)
    activate(client, "nv_sp_no_view", code_no_view)
    assert client.get("/shopee-onboard").status_code == 403


def test_nav_link_order_after_tiktok_onboard(client):
    create_owner(client)
    r = client.get("/shopee-onboard")
    assert r.status_code == 200
    assert r.text.index('href="/tiktok-onboard"') < r.text.index('href="/shopee-onboard"')
