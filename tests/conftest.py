"""Setup chung: TestClient với SQLite tạm + SECRET_KEY test, import lại app mỗi test."""

import os
import sys
from urllib.parse import parse_qs, urlparse

import pytest

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)


def make_client(tmp_path, monkeypatch):
    """Biến môi trường phải set TRƯỚC khi import app (config đọc lúc import)."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("SECRET_KEY", "pytest-secret-key-khong-dung-that")
    monkeypatch.setenv("SESSION_DAYS", "30")
    for name in [n for n in sys.modules if n == "app" or n.startswith("app.")]:
        sys.modules.pop(name)
    from app.database import init_db
    from app.main import app
    from fastapi.testclient import TestClient

    init_db()
    return TestClient(app)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    return make_client(tmp_path, monkeypatch)


def product_payload(**overrides):
    base = {
        "name": "Rơ le nhiệt RL-NC-01",
        "sku": "RL-NC-01",
        "category": "Linh kiện",
        "data_source": "manual",
        "selling_price": 165000,
        "cost_price": 35000,
        "packaging_cost": 3000,
        "shipping_seller": 0,
        "platform_fee_rate": 9,
        "payment_fee_rate": 2,
        "ads_rate": 5,
        "affiliate_rate": 10,
        "other_cost": 0,
        "demand_score": 4,
        "competition_score": 3,
        "content_score": 3,
        "supply_score": 4,
        "status": "active",
        "notes": "ghi chú test",
    }
    base.update(overrides)
    return base


def create_owner(client, username="chushop", password="matkhau123"):
    r = client.post(
        "/setup",
        data={
            "username": username,
            "display_name": "Chủ Shop",
            "password": password,
            "password2": password,
        },
    )
    assert r.status_code == 200  # đã follow redirect về /
    return r


def logout(client):
    client.get("/logout")


def create_staff(client, username, perms=("can_view_products", "can_view_uni")):
    """Owner tạo nhân sự; trả về mã kích hoạt (đọc từ redirect)."""
    data = {"username": username, "display_name": username}
    for p in perms:
        data[p] = "on"
    r = client.post("/accounts/create", data=data, follow_redirects=False)
    assert r.status_code == 303
    qs = parse_qs(urlparse(r.headers["location"]).query)
    return qs["new_code"][0]


def activate(client, username, code, password="matkhau123"):
    return client.post(
        "/activate",
        data={"username": username, "code": code, "password": password, "password2": password},
    )


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})
