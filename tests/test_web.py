"""網頁測試：註冊、登入、頁面 CRUD、CSRF"""
from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import Item


def login(client, username="staff", password="staff1234"):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=True)


def test_pages_require_login(client):
    resp = client.get("/items")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_register_then_login(client):
    resp = client.post(
        "/register",
        data={"username": "newuser", "password": "password1", "password_confirm": "password1"},
        follow_redirects=True,
    )
    assert "註冊成功" in resp.get_data(as_text=True)
    assert "歡迎回來" in login(client, "newuser", "password1").get_data(as_text=True)


def test_register_validation(client):
    resp = client.post("/register", data={"username": "ab", "password": "123", "password_confirm": "123"})
    html = resp.get_data(as_text=True)
    assert "帳號須為" in html and "密碼至少 8 碼" in html


def test_login_failure(client):
    assert "帳號或密碼錯誤" in login(client, "staff", "nope").get_data(as_text=True)


def test_open_redirect_blocked(client):
    resp = client.post(
        "/login?next=https://evil.example.com",
        data={"username": "staff", "password": "staff1234"},
    )
    assert "evil" not in resp.headers["Location"]


def test_web_crud_flow(app, client):
    login(client)
    # 新增
    resp = client.post(
        "/items/new",
        data={"code": "MS-0100", "name": "3cc 空針", "category": "注射耗材", "unit": "支",
              "safety_stock": "10", "unit_price": "2.2", "expiry_date": "", "location": "",
              "initial_quantity": "50"},
        follow_redirects=True,
    )
    html = resp.get_data(as_text=True)
    assert "已新增 MS-0100" in html and "期初庫存" in html

    with app.app_context():
        item_id = db.session.scalar(db.select(Item.id).filter_by(code="MS-0100"))

    # 列表、搜尋、儀表板
    assert "3cc 空針" in client.get("/items?q=空針").get_data(as_text=True)
    assert client.get("/").status_code == 200

    # 編輯頁可以打開，且驗證失敗會保留輸入
    assert client.get(f"/items/{item_id}/edit").status_code == 200
    resp = client.post(f"/items/{item_id}/edit", data={"code": "MS-0100", "name": "改名", "category": "錯的", "unit": "支"})
    assert "必須是" in resp.get_data(as_text=True) and 'value="改名"' in resp.get_data(as_text=True)

    # 出庫
    resp = client.post(f"/items/{item_id}/stock", data={"type": "OUT", "quantity": "20", "department": "急診"},
                       follow_redirects=True)
    assert "結存 30" in resp.get_data(as_text=True)

    # 一般使用者刪除 → 被擋
    resp = client.post(f"/items/{item_id}/delete", follow_redirects=True)
    assert "只有管理員" in resp.get_data(as_text=True)


def test_admin_can_delete(app, client):
    login(client, "admin", "admin1234")
    client.post("/items/new", data={"code": "DEL-1", "name": "待刪", "category": "其他", "unit": "個"})
    with app.app_context():
        item_id = db.session.scalar(db.select(Item.id).filter_by(code="DEL-1"))
    resp = client.post(f"/items/{item_id}/delete", follow_redirects=True)
    assert "已刪除 DEL-1" in resp.get_data(as_text=True)


def test_404_page(client):
    login(client)
    assert client.get("/items/9999").status_code == 302  # NotFoundError → 導回並顯示訊息
    assert client.get("/no-such-page").status_code == 404


def test_csrf_blocks_post_without_token():
    class CsrfConfig(TestConfig):
        CSRF_ENABLED = True

    app = create_app(CsrfConfig)
    with app.app_context():
        db.create_all()
        resp = app.test_client().post("/login", data={"username": "a", "password": "b"}, follow_redirects=True)
        assert "表單已過期" in resp.get_data(as_text=True)
        db.drop_all()
