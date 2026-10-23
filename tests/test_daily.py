"""Báo cáo ngày: công thức, validate, upsert, phân quyền."""

from datetime import date, timedelta

from app.daily import calc_daily, validate_daily_report
from conftest import activate, create_owner, create_staff, login, logout


def _today():
    return date.today().isoformat()


def _future(days):
    return (date.today() + timedelta(days=days)).isoformat()


def test_calc_total_rev_and_roas():
    c = calc_daily(
        {
            "rev_product": 1000000,
            "rev_live": 500000,
            "rev_video": 250000,
            "rev_aff_link": 100000,
            "rev_affiliate": 150000,
            "ad_gmv": 800000,
            "ad_cost": 200000,
        }
    )
    assert c["total_rev"] == 2000000
    assert c["roas"] == 4.0


def test_calc_roas_zero_cost_is_none():
    c = calc_daily({"rev_product": 100, "ad_gmv": 500, "ad_cost": 0})
    assert c["total_rev"] == 100
    assert c["roas"] is None


def test_calc_ignores_missing_fields():
    c = calc_daily({})
    assert c["total_rev"] == 0
    assert c["roas"] is None


def test_validate_ok():
    clean, errors = validate_daily_report(
        {
            "date": _today(),
            "rev_product": "1250000",
            "rev_live": 300000,
            "rev_video": 0,
            "rev_aff_link": "",
            "rev_affiliate": None,
            "ad_gmv": 800000,
            "ad_cost": 200000,
            "aov": 150000,
            "conv_rate": "2.5",
            "note": "  ngày tốt  ",
        }
    )
    assert errors == {}, errors
    assert clean["date"] == _today()
    assert clean["rev_product"] == 1250000
    assert clean["rev_live"] == 300000
    assert clean["rev_aff_link"] == 0
    assert clean["conv_rate"] == 2.5
    assert clean["note"] == "ngày tốt"


def test_validate_negative_rejected():
    _, errors = validate_daily_report({"date": _today(), "rev_product": -1})
    assert "rev_product" in errors
    _, errors = validate_daily_report({"date": _today(), "ad_cost": "-5"})
    assert "ad_cost" in errors


def test_validate_conv_rate_range():
    _, errors = validate_daily_report({"date": _today(), "conv_rate": 100.5})
    assert "conv_rate" in errors
    _, errors = validate_daily_report({"date": _today(), "conv_rate": -1})
    assert "conv_rate" in errors
    clean, errors = validate_daily_report({"date": _today(), "conv_rate": 100})
    assert errors == {}
    assert clean["conv_rate"] == 100


def test_validate_bad_date():
    _, errors = validate_daily_report({"date": "19/10/2026"})
    assert "date" in errors
    _, errors = validate_daily_report({"date": "2026-02-30"})
    assert "date" in errors
    _, errors = validate_daily_report({})
    assert "date" in errors


def test_validate_future_date_blocked():
    _, errors = validate_daily_report({"date": _future(2)})
    assert "date" in errors
    clean, errors = validate_daily_report({"date": _future(1)})
    assert errors == {}, errors
    assert clean["date"] == _future(1)


def _report(day_offset=0, **kw):
    d = {
        "date": _future(day_offset) if day_offset else _today(),
        "rev_product": 1000000,
        "rev_live": 500000,
        "rev_video": 250000,
        "rev_aff_link": 100000,
        "rev_affiliate": 150000,
        "ad_gmv": 800000,
        "ad_cost": 200000,
        "aov": 150000,
        "conv_rate": 2.5,
        "note": "ghi chú",
    }
    d.update(kw)
    return d


def test_upsert_creates_then_updates(client):
    create_owner(client)
    r = client.post("/api/daily", json=_report())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["calc"]["total_rev"] == 2000000
    assert body["calc"]["roas"] == 4.0
    assert body["updated_by"] == "Chủ Shop"

    r = client.post("/api/daily", json=_report(rev_live=900000))
    assert r.status_code == 200  # trùng ngày → cập nhật
    body = r.json()
    assert body["calc"]["total_rev"] == 2400000
    assert body["rev_live"] == 900000

    data = client.get("/api/daily").json()
    assert len(data["reports"]) == 1
    assert data["reports"][0]["date"] == _today()


def test_list_newest_first(client):
    create_owner(client)
    client.post("/api/daily", json=_report())
    client.post("/api/daily", json=_report(day_offset=-2))
    client.post("/api/daily", json=_report(day_offset=-1))
    dates = [r["date"] for r in client.get("/api/daily").json()["reports"]]
    assert dates == sorted(dates, reverse=True)
    assert dates[0] == _today()


def test_get_single_and_404(client):
    create_owner(client)
    client.post("/api/daily", json=_report())
    r = client.get(f"/api/daily/{_today()}")
    assert r.status_code == 200
    assert r.json()["calc"]["total_rev"] == 2000000
    assert client.get("/api/daily/2000-01-01").status_code == 404


def test_put_update_and_date_mismatch(client):
    create_owner(client)
    client.post("/api/daily", json=_report())
    payload = _report(ad_cost=400000)
    r = client.put(f"/api/daily/{_today()}", json=payload)
    assert r.status_code == 200
    assert r.json()["calc"]["roas"] == 2.0
    # body date khác path date → 422
    payload["date"] = _future(-1)
    r = client.put(f"/api/daily/{_today()}", json=payload)
    assert r.status_code == 422
    assert client.put("/api/daily/2000-01-01", json=_report()).status_code == 404


def test_delete(client):
    create_owner(client)
    client.post("/api/daily", json=_report())
    r = client.delete(f"/api/daily/{_today()}")
    assert r.status_code == 204
    assert client.get("/api/daily").json()["reports"] == []
    assert client.delete(f"/api/daily/{_today()}").status_code == 404


def test_validation_errors_api(client):
    create_owner(client)
    r = client.post("/api/daily", json=_report(rev_product=-5))
    assert r.status_code == 422
    r = client.post("/api/daily", json=_report(conv_rate=150))
    assert r.status_code == 422
    r = client.post("/api/daily", json=_report(date="not-a-date"))
    assert r.status_code == 422
    r = client.post("/api/daily", json=_report(date=_future(5)))
    assert r.status_code == 422


def test_server_recomputes_ignores_client_values(client):
    create_owner(client)
    payload = _report()
    payload.update({"total_rev": 99999999, "roas": 123.45, "calc": {"total_rev": 1}})
    r = client.post("/api/daily", json=payload)
    assert r.status_code == 201
    calc = r.json()["calc"]
    assert calc["total_rev"] == 2000000
    assert calc["roas"] == 4.0


def test_fail_closed_no_login(client):
    create_owner(client)
    logout(client)
    r = client.get("/bao-cao", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/login" in r.headers["location"]
    assert client.get("/api/daily").status_code == 401
    assert client.post("/api/daily", json=_report()).status_code == 401
    assert client.delete(f"/api/daily/{_today()}").status_code == 401


def test_view_only_cannot_write(client):
    create_owner(client)
    client.post("/api/daily", json=_report())
    code = create_staff(client, "nv_daily", perms=("can_view_daily",))
    logout(client)
    activate(client, "nv_daily", code)

    assert client.get("/bao-cao").status_code == 200
    assert client.get("/api/daily").status_code == 200
    assert client.get(f"/api/daily/{_today()}").status_code == 200
    assert client.post("/api/daily", json=_report()).status_code == 403
    assert client.put(f"/api/daily/{_today()}", json=_report()).status_code == 403
    assert client.delete(f"/api/daily/{_today()}").status_code == 403


def test_delete_needs_delete_perm(client):
    create_owner(client)
    code = create_staff(client, "nv_sua2", perms=("can_view_daily", "can_add_edit_products"))
    logout(client)
    activate(client, "nv_sua2", code)

    # được thêm/sửa nhưng không được xóa
    assert client.post("/api/daily", json=_report()).status_code == 201
    assert client.delete(f"/api/daily/{_today()}").status_code == 403
    logout(client)
    login(client, "chushop", "matkhau123")
    assert client.delete(f"/api/daily/{_today()}").status_code == 204
