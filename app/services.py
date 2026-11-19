"""
商業邏輯層（Service Layer）。

網頁路由（app/items）和 API 路由（app/api）都呼叫這裡的函式，
所以「驗證規則」和「庫存計算」只寫一次，兩邊行為一定一致。

對照 C#：相當於 ERP 專案裡的 BLL / Service 類別，
Controller 只負責接參數、回傳結果，不直接寫商業規則。
"""
import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from .errors import BusinessError, NotFoundError, PermissionDenied, ValidationError
from .extensions import db
from .models import Item, StockTransaction, User

# logger 名稱是 "app.services"，會自動沿用 app 的 log 設定與 request_id
logger = logging.getLogger(__name__)

CATEGORIES = ["敷料", "注射耗材", "防護用品", "檢驗耗材", "其他"]
CODE_PATTERN = re.compile(r"^[A-Z0-9-]{3,30}$")


# ---------------------------------------------------------------------------
# 小工具：把表單字串或 JSON 值轉成正確型別
# ---------------------------------------------------------------------------
def _is_blank(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def _to_int(value, field, errors, minimum=0):
    try:
        number = int(value)
    except (TypeError, ValueError):
        errors[field] = "必須是整數"
        return None
    if number < minimum:
        errors[field] = f"不可小於 {minimum}"
        return None
    return number


def _to_decimal(value, field, errors):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        errors[field] = "必須是數字"
        return None
    if number < 0:
        errors[field] = "不可為負數"
        return None
    return number.quantize(Decimal("0.01"))


def _to_date(value, field, errors):
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        errors[field] = "日期格式須為 YYYY-MM-DD"
        return None


# ---------------------------------------------------------------------------
# 驗證
# ---------------------------------------------------------------------------
def clean_item_data(data, partial=False):
    """
    驗證並轉換耗材資料。
    partial=True 代表部分更新（PATCH），沒傳的欄位就不檢查。
    回傳乾淨的 dict；有錯誤就丟 ValidationError（內含每個欄位的錯誤訊息）。

    ※ 新增欄位時，這裡要加一段對應的驗證（見 docs/面試說明.md 第 3 節）
    """
    errors = {}
    cleaned = {}

    def provided(key):
        return key in data and not _is_blank(data.get(key))

    def required(key):
        if not partial and not provided(key):
            errors[key] = "必填"

    # 料號：自動轉大寫，只允許英數與 -
    required("code")
    if provided("code"):
        code = str(data["code"]).strip().upper()
        if CODE_PATTERN.match(code):
            cleaned["code"] = code
        else:
            errors["code"] = "只能是 3~30 碼英數字或 -"

    required("name")
    if provided("name"):
        name = str(data["name"]).strip()
        if len(name) > 100:
            errors["name"] = "最多 100 字"
        else:
            cleaned["name"] = name

    required("category")
    if provided("category"):
        category = str(data["category"]).strip()
        if category in CATEGORIES:
            cleaned["category"] = category
        else:
            errors["category"] = f"必須是：{'、'.join(CATEGORIES)}"

    required("unit")
    if provided("unit"):
        cleaned["unit"] = str(data["unit"]).strip()[:10]

    if provided("safety_stock"):
        value = _to_int(data["safety_stock"], "safety_stock", errors)
        if value is not None:
            cleaned["safety_stock"] = value

    if provided("unit_price"):
        value = _to_decimal(data["unit_price"], "unit_price", errors)
        if value is not None:
            cleaned["unit_price"] = value

    # 效期與儲位可以清空：有傳 key 但值是空的 → 設成 None
    if "expiry_date" in data:
        cleaned["expiry_date"] = (
            None
            if _is_blank(data["expiry_date"])
            else _to_date(data["expiry_date"], "expiry_date", errors)
        )

    if "location" in data:
        cleaned["location"] = (
            None if _is_blank(data["location"]) else str(data["location"]).strip()[:50]
        )

    # 庫存量不允許直接修改，要走入出庫
    if "quantity" in data:
        errors["quantity"] = "庫存量不可直接修改，請使用入庫 / 出庫功能"

    if errors:
        raise ValidationError("資料驗證失敗", details=errors)
    return cleaned


# ---------------------------------------------------------------------------
# 使用者
# ---------------------------------------------------------------------------
def register_user(username, password, display_name=None, role="staff"):
    username = (username or "").strip()
    errors = {}
    if not re.match(r"^[A-Za-z0-9_]{3,50}$", username):
        errors["username"] = "帳號須為 3~50 碼英數字或底線"
    if not password or len(password) < 8:
        errors["password"] = "密碼至少 8 碼"
    if errors:
        raise ValidationError("資料驗證失敗", details=errors)

    if db.session.scalar(select(User).filter_by(username=username)):
        raise BusinessError("此帳號已被註冊", details={"username": "已存在"})

    user = User(username=username, display_name=display_name or username, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    logger.info("新使用者註冊 username=%s role=%s", username, role)
    return user


def authenticate(username, password):
    """帳密正確回傳 User，否則回傳 None（不透露是帳號錯還是密碼錯）"""
    user = db.session.scalar(select(User).filter_by(username=(username or "").strip()))
    if user and user.check_password(password or ""):
        return user
    logger.warning("登入失敗 username=%s", username)
    return None


# ---------------------------------------------------------------------------
# 耗材 CRUD
# ---------------------------------------------------------------------------
def get_item_or_404(item_id):
    item = db.session.get(Item, item_id)
    if item is None:
        raise NotFoundError(f"找不到耗材 id={item_id}")
    return item


def search_items(keyword=None, category=None, low_stock=False):
    """組出查詢語句（還沒執行），讓呼叫端決定要分頁或全部取出"""
    stmt = select(Item)
    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(Item.code.ilike(like), Item.name.ilike(like)))
    if category:
        stmt = stmt.where(Item.category == category)
    if low_stock:
        stmt = stmt.where(Item.quantity <= Item.safety_stock)
    return stmt.order_by(Item.code)


def create_item(data, user):
    cleaned = clean_item_data(data)

    # 期初庫存：建檔時可順便入庫，會自動產生一筆 IN 異動
    initial_qty = 0
    if not _is_blank(data.get("initial_quantity")):
        errors = {}
        initial_qty = _to_int(data["initial_quantity"], "initial_quantity", errors)
        if errors:
            raise ValidationError("資料驗證失敗", details=errors)

    item = Item(**cleaned, quantity=0, created_by_id=user.id)
    db.session.add(item)
    try:
        db.session.flush()  # 先送出 INSERT 取得 item.id，但還沒 commit
    except IntegrityError:
        db.session.rollback()
        raise BusinessError("料號已存在", details={"code": "重複"})

    if initial_qty:
        _apply_stock_change(item, StockTransaction.TYPE_IN, initial_qty, user, note="期初庫存")

    db.session.commit()
    logger.info("新增耗材 id=%s code=%s by=%s", item.id, item.code, user.username)
    return item


def update_item(item, data, partial=True):
    cleaned = clean_item_data(data, partial=partial)
    for field, value in cleaned.items():
        setattr(item, field, value)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise BusinessError("料號已存在", details={"code": "重複"})
    logger.info("修改耗材 id=%s 欄位=%s", item.id, list(cleaned.keys()))
    return item


def delete_item(item, user):
    if not user.is_admin:
        raise PermissionDenied("只有管理員可以刪除耗材")
    logger.info("刪除耗材 id=%s code=%s by=%s", item.id, item.code, user.username)
    db.session.delete(item)
    db.session.commit()


# ---------------------------------------------------------------------------
# 入出庫
# ---------------------------------------------------------------------------
def _apply_stock_change(item, txn_type, qty, user, department=None, note=None):
    """
    真正更新庫存的地方（不 commit，交給呼叫端）。

    出庫用「條件式 UPDATE」：
        UPDATE items SET quantity = quantity - :qty
        WHERE id = :id AND quantity >= :qty
    由資料庫在同一句 SQL 裡檢查並扣除，兩個人同時領料也不會扣成負數。
    """
    if txn_type == StockTransaction.TYPE_IN:
        stmt = (
            update(Item)
            .where(Item.id == item.id)
            .values(quantity=Item.quantity + qty)
        )
    else:
        stmt = (
            update(Item)
            .where(Item.id == item.id, Item.quantity >= qty)
            .values(quantity=Item.quantity - qty)
        )

    result = db.session.execute(stmt)
    if result.rowcount == 0:
        db.session.rollback()
        raise BusinessError(
            f"庫存不足：{item.code} 目前 {item.quantity} {item.unit}，欲出庫 {qty}",
            details={"quantity": "超過現有庫存"},
        )

    db.session.refresh(item)  # 重新讀取最新庫存
    txn = StockTransaction(
        item_id=item.id,
        txn_type=txn_type,
        quantity=qty,
        balance_after=item.quantity,
        department=department,
        note=note,
        user_id=user.id,
    )
    db.session.add(txn)
    return txn


def record_transaction(item, data, user):
    """入庫 / 出庫，data 需要 type、quantity，可選 department、note"""
    errors = {}
    txn_type = str(data.get("type", "")).strip().upper()
    if txn_type not in (StockTransaction.TYPE_IN, StockTransaction.TYPE_OUT):
        errors["type"] = "必須是 IN 或 OUT"
    qty = _to_int(data.get("quantity"), "quantity", errors, minimum=1)
    if errors:
        raise ValidationError("資料驗證失敗", details=errors)

    department = (data.get("department") or "").strip()[:50] or None
    note = (data.get("note") or "").strip()[:200] or None

    txn = _apply_stock_change(item, txn_type, qty, user, department, note)
    db.session.commit()
    logger.info(
        "庫存異動 item=%s type=%s qty=%s balance=%s dept=%s",
        item.code, txn_type, qty, txn.balance_after, department,
    )
    return txn


# ---------------------------------------------------------------------------
# 統計（給儀表板與 /api/v1/stats/summary 用）
# ---------------------------------------------------------------------------
def inventory_summary(expiry_days=30, usage_days=30):
    """
    用 SQL 聚合函式做統計，資料量大時讓資料庫算，不要把全部資料撈回 Python 再算。
    """
    today = date.today()

    # 1. 各分類：品項數、總庫存、庫存金額
    by_category = db.session.execute(
        select(
            Item.category,
            func.count(Item.id),
            func.coalesce(func.sum(Item.quantity), 0),
            func.coalesce(func.sum(Item.quantity * Item.unit_price), 0),
        )
        .group_by(Item.category)
        .order_by(Item.category)
    ).all()

    # 2. 低於安全庫存
    low_stock = db.session.scalars(
        select(Item).where(Item.quantity <= Item.safety_stock).order_by(Item.quantity)
    ).all()

    # 3. 即將到期（含已過期）
    expiring = db.session.scalars(
        select(Item)
        .where(
            Item.expiry_date.is_not(None),
            Item.expiry_date <= today + timedelta(days=expiry_days),
        )
        .order_by(Item.expiry_date)
    ).all()

    # 4. 近 N 天各單位領用量（出庫）排行
    since = datetime.now() - timedelta(days=usage_days)
    usage = db.session.execute(
        select(
            func.coalesce(StockTransaction.department, "未填"),
            func.sum(StockTransaction.quantity),
            func.count(StockTransaction.id),
        )
        .where(
            StockTransaction.txn_type == StockTransaction.TYPE_OUT,
            StockTransaction.created_at >= since,
        )
        .group_by(StockTransaction.department)
        .order_by(func.sum(StockTransaction.quantity).desc())
    ).all()

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "by_category": [
            {
                "category": row[0],
                "item_count": row[1],
                "total_quantity": int(row[2]),
                "stock_value": round(float(row[3]), 2),
            }
            # 依 CATEGORIES 定義的順序排列，「其他」放最後
            for row in sorted(by_category, key=lambda r: CATEGORIES.index(r[0]) if r[0] in CATEGORIES else 99)
        ],
        "low_stock": [i.to_dict() for i in low_stock],
        "expiring_within_days": expiry_days,
        "expiring": [i.to_dict() for i in expiring],
        "usage_days": usage_days,
        "usage_by_department": [
            {"department": row[0], "quantity": int(row[1]), "transactions": row[2]}
            for row in usage
        ],
    }
