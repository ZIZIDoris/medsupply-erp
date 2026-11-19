"""API 測試：登入、CRUD、入出庫、權限、錯誤格式"""


# ---------- 驗證 ----------
def test_health(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.get_json()["database"] == "sqlite"


def test_login_wrong_password(client):
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401
    body = resp.get_json()
    assert body["error"]["code"] == "unauthorized"
    # 每個錯誤都要帶 request_id，且與回應標頭一致
    assert body["error"]["request_id"] == resp.headers["X-Request-ID"]


def test_requires_token(client):
    assert client.get("/api/v1/items").status_code == 401
    bad = client.get("/api/v1/items", headers={"Authorization": "Bearer abc.def"})
    assert bad.status_code == 401
    assert bad.get_json()["error"]["message"] == "Token 無效"


def test_me(client, staff_headers):
    assert client.get("/api/v1/me", headers=staff_headers).get_json()["username"] == "staff"


# ---------- CRUD ----------
def test_create_item_normalizes_and_records_initial_stock(client, staff_headers, sample_item):
    assert sample_item["code"] == "MS-0001"  # 自動轉大寫
    assert sample_item["quantity"] == 100
    txns = client.get(f"/api/v1/items/{sample_item['id']}/transactions", headers=staff_headers).get_json()
    assert txns["data"][0]["note"] == "期初庫存"


def test_create_item_validation(client, staff_headers):
    resp = client.post(
        "/api/v1/items",
        headers=staff_headers,
        json={"code": "x", "category": "不存在", "unit_price": -1},
    )
    assert resp.status_code == 422
    details = resp.get_json()["error"]["details"]
    assert set(details) >= {"code", "name", "category", "unit", "unit_price"}


def test_duplicate_code(client, staff_headers, sample_item):
    resp = client.post(
        "/api/v1/items",
        headers=staff_headers,
        json={"code": "MS-0001", "name": "重複", "category": "敷料", "unit": "包"},
    )
    assert resp.status_code == 409


def test_list_search_and_pagination(client, staff_headers, sample_item):
    resp = client.get("/api/v1/items?q=紗布&per_page=5", headers=staff_headers).get_json()
    assert resp["meta"]["total"] == 1
    assert client.get("/api/v1/items?q=不存在", headers=staff_headers).get_json()["meta"]["total"] == 0


def test_patch_and_put(client, staff_headers, sample_item):
    url = f"/api/v1/items/{sample_item['id']}"
    resp = client.patch(url, headers=staff_headers, json={"safety_stock": 50, "location": "A-01"})
    assert resp.status_code == 200
    assert resp.get_json()["safety_stock"] == 50

    # PUT 缺必填欄位 → 422
    assert client.put(url, headers=staff_headers, json={"name": "只給名稱"}).status_code == 422


def test_cannot_edit_quantity_directly(client, staff_headers, sample_item):
    resp = client.patch(f"/api/v1/items/{sample_item['id']}", headers=staff_headers, json={"quantity": 999})
    assert resp.status_code == 422
    assert "quantity" in resp.get_json()["error"]["details"]


def test_get_missing_item(client, staff_headers):
    resp = client.get("/api/v1/items/9999", headers=staff_headers)
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "not_found"


def test_delete_requires_admin(client, staff_headers, admin_headers, sample_item):
    url = f"/api/v1/items/{sample_item['id']}"
    assert client.delete(url, headers=staff_headers).status_code == 403
    assert client.delete(url, headers=admin_headers).status_code == 204
    assert client.get(url, headers=admin_headers).status_code == 404


def test_non_json_body(client, staff_headers):
    resp = client.post("/api/v1/items", headers=staff_headers, data="not json")
    assert resp.status_code == 422


# ---------- 入出庫 ----------
def test_stock_in_and_out(client, staff_headers, sample_item):
    url = f"/api/v1/items/{sample_item['id']}/transactions"
    resp = client.post(url, headers=staff_headers, json={"type": "OUT", "quantity": 30, "department": "急診"})
    assert resp.status_code == 201
    assert resp.get_json()["item"]["quantity"] == 70

    resp = client.post(url, headers=staff_headers, json={"type": "in", "quantity": 10})
    assert resp.get_json()["transaction"]["balance_after"] == 80


def test_stock_out_insufficient(client, staff_headers, sample_item):
    url = f"/api/v1/items/{sample_item['id']}/transactions"
    resp = client.post(url, headers=staff_headers, json={"type": "OUT", "quantity": 101})
    assert resp.status_code == 409
    # 失敗時庫存不能被扣
    item = client.get(f"/api/v1/items/{sample_item['id']}", headers=staff_headers).get_json()
    assert item["quantity"] == 100


def test_stock_invalid_quantity(client, staff_headers, sample_item):
    url = f"/api/v1/items/{sample_item['id']}/transactions"
    assert client.post(url, headers=staff_headers, json={"type": "OUT", "quantity": 0}).status_code == 422
    assert client.post(url, headers=staff_headers, json={"type": "XX", "quantity": 1}).status_code == 422


# ---------- 統計 ----------
def test_summary(client, staff_headers, sample_item):
    url = f"/api/v1/items/{sample_item['id']}/transactions"
    client.post(url, headers=staff_headers, json={"type": "OUT", "quantity": 85, "department": "5A 病房"})

    summary = client.get("/api/v1/stats/summary", headers=staff_headers).get_json()
    assert summary["by_category"][0] == {
        "category": "敷料", "item_count": 1, "total_quantity": 15, "stock_value": 52.5,
    }
    assert [i["code"] for i in summary["low_stock"]] == ["MS-0001"]  # 15 <= 20
    assert summary["usage_by_department"][0]["department"] == "5A 病房"


# ---------- 非預期錯誤 ----------
def test_unexpected_error_returns_request_id(app, client, staff_headers, monkeypatch):
    from app import services

    def boom(*args, **kwargs):
        raise RuntimeError("模擬資料庫掛掉")

    monkeypatch.setattr(services, "inventory_summary", boom)
    resp = client.get("/api/v1/stats/summary", headers={**staff_headers, "X-Request-ID": "trace-123"})
    assert resp.status_code == 500
    assert resp.get_json()["error"]["request_id"] == "trace-123"
