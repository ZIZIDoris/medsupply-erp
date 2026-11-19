"""
資料表定義（ORM Model）。
每個 class 對應一張資料表，每個 db.Column 對應一個欄位。

對照 C#：相當於 EF Core 的 Entity 類別。
修改這裡的欄位之後，要跑 `flask db migrate` + `flask db upgrade` 才會真的改到資料庫。
"""
from datetime import date, datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


class User(UserMixin, db.Model):
    """會員 / 使用者"""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    # 密碼只存雜湊值（PBKDF2 / scrypt），絕不存明碼
    password_hash = db.Column(db.String(256), nullable=False)
    display_name = db.Column(db.String(50))
    # 角色：admin 可以刪除資料；staff 只能新增、修改、入出庫
    role = db.Column(db.String(20), nullable=False, default="staff")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_admin(self):
        return self.role == "admin"

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
        }


class Item(db.Model):
    """醫療耗材主檔（對應 ERP 的「料品主檔」）"""

    __tablename__ = "items"

    id = db.Column(db.Integer, primary_key=True)
    # 料號：業務上的唯一鍵，例如 MS-0001
    code = db.Column(db.String(30), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(30), nullable=False, index=True)
    unit = db.Column(db.String(10), nullable=False, default="個")
    # 目前庫存量：只能透過入出庫異動修改，不能直接編輯（保留稽核軌跡）
    quantity = db.Column(db.Integer, nullable=False, default=0)
    # 安全庫存量：低於這個數字要提醒補貨
    safety_stock = db.Column(db.Integer, nullable=False, default=0)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    expiry_date = db.Column(db.Date)
    location = db.Column(db.String(50))  # 儲位，例如 A-01-03
    manufacturer = db.Column(db.String(100))  # 廠商
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    created_by = db.relationship("User")
    # 刪除料品時一併刪除其異動紀錄
    transactions = db.relationship(
        "StockTransaction",
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="[StockTransaction.created_at.desc(), StockTransaction.id.desc()]",
        lazy="dynamic",
    )

    @property
    def is_low_stock(self):
        return self.quantity <= self.safety_stock

    @property
    def days_to_expiry(self):
        if self.expiry_date is None:
            return None
        return (self.expiry_date - date.today()).days

    def to_dict(self):
        """轉成 JSON 可輸出的 dict（API 回傳用）"""
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "category": self.category,
            "unit": self.unit,
            "quantity": self.quantity,
            "safety_stock": self.safety_stock,
            "unit_price": float(self.unit_price or 0),
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "location": self.location,
            "manufacturer": self.manufacturer,
            "is_low_stock": self.is_low_stock,
            "days_to_expiry": self.days_to_expiry,
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "updated_at": self.updated_at.isoformat(timespec="seconds"),
        }

    def __repr__(self):
        return f"<Item {self.code} {self.name} qty={self.quantity}>"


class StockTransaction(db.Model):
    """入出庫異動紀錄（對應 ERP 的「庫存異動單」）"""

    __tablename__ = "stock_transactions"

    TYPE_IN = "IN"
    TYPE_OUT = "OUT"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(
        db.Integer, db.ForeignKey("items.id"), nullable=False, index=True
    )
    txn_type = db.Column(db.String(3), nullable=False)  # IN / OUT
    quantity = db.Column(db.Integer, nullable=False)  # 永遠是正數
    balance_after = db.Column(db.Integer, nullable=False)  # 異動後結存
    department = db.Column(db.String(50))  # 領用 / 進貨單位，例如 急診、5A 病房
    note = db.Column(db.String(200))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=datetime.now, index=True
    )

    item = db.relationship("Item", back_populates="transactions")
    user = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "item_id": self.item_id,
            "type": self.txn_type,
            "quantity": self.quantity,
            "balance_after": self.balance_after,
            "department": self.department,
            "note": self.note,
            "user": self.user.username if self.user else None,
            "created_at": self.created_at.isoformat(timespec="seconds"),
        }
