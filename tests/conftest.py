"""
pytest 共用設定：每個測試都拿到一個全新的 app + 記憶體資料庫。
"""
import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import User


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        admin = User(username="admin", display_name="管理員", role="admin")
        admin.set_password("admin1234")
        staff = User(username="staff", display_name="一般人員", role="staff")
        staff.set_password("staff1234")
        db.session.add_all([admin, staff])
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _token(client, username, password):
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["token"]


@pytest.fixture
def admin_headers(client):
    return {"Authorization": f"Bearer {_token(client, 'admin', 'admin1234')}"}


@pytest.fixture
def staff_headers(client):
    return {"Authorization": f"Bearer {_token(client, 'staff', 'staff1234')}"}


@pytest.fixture
def sample_item(client, staff_headers):
    """先建立一筆期初 100 的耗材"""
    resp = client.post(
        "/api/v1/items",
        headers=staff_headers,
        json={
            "code": "ms-0001",
            "name": "無菌紗布",
            "category": "敷料",
            "unit": "包",
            "safety_stock": 20,
            "unit_price": 3.5,
            "expiry_date": "2030-12-31",
            "initial_quantity": 100,
        },
    )
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()
