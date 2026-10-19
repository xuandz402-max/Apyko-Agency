"""CRUD sản phẩm qua form HTML + validation + CSV."""

from conftest import create_owner, product_payload


def test_create_product_via_form(client):
    create_owner(client)
    r = client.post("/products", data=product_payload(), follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/products")
    r = client.get("/products")
    assert "Rơ le nhiệt RL-NC-01" in r.text
    assert "RL-NC-01" in r.text


def test_create_product_validation_error(client):
    create_owner(client)
    r = client.post("/products", data=product_payload(platform_fee_rate=150))
    assert r.status_code == 422
    assert "0 đến 100" in r.text


def test_create_product_missing_name(client):
    create_owner(client)
    r = client.post("/products", data=product_payload(name=""))
    assert r.status_code == 422
    assert "Tên sản phẩm" in r.text


def test_product_detail_shows_calc(client):
    create_owner(client)
    r = client.post("/api/products", json=product_payload())
    pid = r.json()["product"]["id"]
    r = client.get(f"/products/{pid}")
    assert r.status_code == 200
    # LN = 165000 - 35000 - 3000 - 0 - (9%+2%+5%+10%)*165000 - 0
    #    = 165000 - 38000 - 42900 = 84100
    assert "84,100₫" in r.text
    assert "Cách tính lợi nhuận" in r.text


def test_edit_product(client):
    create_owner(client)
    pid = client.post("/api/products", json=product_payload()).json()["product"]["id"]
    r = client.post(
        f"/products/{pid}/edit", data=product_payload(selling_price=175000), follow_redirects=False
    )
    assert r.status_code == 303
    r = client.get(f"/products/{pid}")
    assert "175,000₫" in r.text


def test_api_crud_json(client):
    create_owner(client)
    created = client.post("/api/products", json=product_payload()).json()
    pid = created["product"]["id"]
    assert created["calc"]["profit"] == 84100
    got = client.get(f"/api/products/{pid}").json()
    assert got["product"]["name"] == "Rơ le nhiệt RL-NC-01"
    updated = client.put(f"/api/products/{pid}", json={"cost_price": 40000}).json()
    assert updated["calc"]["profit"] == 79100
    assert client.get("/api/products/999999").status_code == 404


def test_csv_export_import_roundtrip(client):
    create_owner(client)
    client.post("/api/products", json=product_payload())
    r = client.get("/api/products/export")
    assert r.status_code == 200
    assert "name" in r.text.splitlines()[0]
    # Import lại file vừa export (bỏ BOM đã decode, đổi tên để tránh trùng)
    text = r.text.lstrip("\ufeff").replace("Rơ le nhiệt RL-NC-01", "Rơ le nhiệt COPY", 1)
    r = client.post(
        "/api/products/import",
        files={"file": ("products.csv", text.encode("utf-8-sig"), "text/csv")},
    )
    assert r.json()["imported"] == 1
    assert r.json()["errors"] == []
    r = client.get("/api/products")
    assert r.json()["total"] == 2


def test_csv_import_bad_rows_reported(client):
    create_owner(client)
    csv_text = "name,platform_fee_rate\nHợp lệ,10\nSai phí,150\n"
    r = client.post(
        "/api/products/import",
        files={"file": ("bad.csv", csv_text.encode("utf-8"), "text/csv")},
    )
    body = r.json()
    assert body["imported"] == 1
    assert len(body["errors"]) == 1
    assert body["errors"][0]["row"] == 3


def test_demo_seed_and_clear(client):
    create_owner(client)
    r = client.post("/api/demo/seed")
    assert r.json()["created"] == 3
    r = client.get("/products")
    assert "DEMO" in r.text
    r = client.request("DELETE", "/api/demo")
    assert r.json()["deleted"] == 3
