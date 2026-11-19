"""
自訂指令（flask <指令>），用來建立管理員與測試資料。

  flask seed           建立 admin / staff 帳號與範例耗材、異動資料
  flask create-admin   互動式建立管理員
"""
import random
from datetime import date, datetime, timedelta

import click
from sqlalchemy import select

from .extensions import db
from .models import Item, StockTransaction, User

SAMPLE_ITEMS = [
    # 料號, 名稱, 分類, 單位, 安全庫存, 單價, 距今幾天到期, 儲位, 期初量
    ("MS-0001", "無菌紗布 4x4", "敷料", "包", 200, 3.5, 400, "A-01-01", 850),
    ("MS-0002", "透氣膠帶 1 吋", "敷料", "捲", 100, 12, 600, "A-01-02", 320),
    ("MS-0003", "人工皮 10x10", "敷料", "片", 50, 85, 20, "A-01-03", 40),
    ("MS-0101", "3cc 空針", "注射耗材", "支", 500, 2.2, 700, "B-02-01", 2400),
    ("MS-0102", "23G 針頭", "注射耗材", "支", 500, 1.1, 15, "B-02-02", 1800),
    ("MS-0103", "靜脈留置針 22G", "注射耗材", "支", 200, 28, 300, "B-02-03", 150),
    ("MS-0201", "外科口罩", "防護用品", "盒", 100, 95, 500, "C-01-01", 380),
    ("MS-0202", "N95 口罩", "防護用品", "盒", 30, 680, 250, "C-01-02", 25),
    ("MS-0203", "檢診手套 M", "防護用品", "盒", 150, 160, 365, "C-01-03", 420),
    ("MS-0301", "真空採血管 紫頭", "檢驗耗材", "支", 300, 4.8, -3, "D-03-01", 600),
    ("MS-0302", "血糖試紙", "檢驗耗材", "盒", 40, 520, 90, "D-03-02", 75),
    ("MS-0901", "酒精棉片", "其他", "盒", 80, 45, 400, "E-01-01", 260),
]

DEPARTMENTS = ["急診", "5A 病房", "7B 病房", "加護病房", "門診", "檢驗科"]


def register_cli(app):
    @app.cli.command("seed")
    @click.option("--reset", is_flag=True, help="先清空所有資料表再建立")
    def seed(reset):
        """建立測試帳號與範例資料"""
        if reset:
            db.drop_all()
        db.create_all()

        if db.session.scalar(select(User).filter_by(username="admin")):
            click.echo("已有資料，略過（要重建請加 --reset）")
            return

        admin = User(username="admin", display_name="系統管理員", role="admin")
        admin.set_password("admin1234")
        staff = User(username="nurse01", display_name="王護理師", role="staff")
        staff.set_password("nurse1234")
        db.session.add_all([admin, staff])
        db.session.flush()

        rng = random.Random(42)  # 固定亂數種子，每次產生的資料都一樣
        now = datetime.now()
        for code, name, cat, unit, safety, price, days, loc, qty in SAMPLE_ITEMS:
            item = Item(
                code=code, name=name, category=cat, unit=unit, safety_stock=safety,
                unit_price=price, expiry_date=date.today() + timedelta(days=days),
                location=loc, quantity=qty, created_by_id=admin.id,
            )
            db.session.add(item)
            db.session.flush()
            # 期初入庫
            db.session.add(StockTransaction(
                item_id=item.id, txn_type="IN", quantity=qty, balance_after=qty,
                note="期初庫存", user_id=admin.id, created_at=now - timedelta(days=30),
            ))
            # 模擬近 30 天的領用紀錄
            # 先產生日期再由舊到新排序，結存才會符合時間順序
            balance = qty
            days_ago = sorted((rng.randint(0, 29) for _ in range(rng.randint(2, 6))), reverse=True)
            for d in days_ago:
                out = rng.randint(1, max(1, qty // 20))
                if out > balance:
                    break
                balance -= out
                db.session.add(StockTransaction(
                    item_id=item.id, txn_type="OUT", quantity=out, balance_after=balance,
                    department=rng.choice(DEPARTMENTS), note="病房請領",
                    user_id=staff.id, created_at=now - timedelta(days=d, hours=rng.randint(0, 8)),
                ))
            item.quantity = balance

        db.session.commit()
        click.echo("完成！帳號 admin / admin1234（管理員）、nurse01 / nurse1234（一般使用者）")

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(username, password):
        """建立管理員帳號"""
        from .services import register_user

        register_user(username, password, role="admin")
        click.echo(f"管理員 {username} 建立完成")
