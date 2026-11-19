"""
網頁版耗材管理：儀表板、列表 / 搜尋、新增、編輯、刪除、入出庫。
商業規則都在 services.py，這裡只處理「表單進來、頁面出去」。
"""
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import services
from ..errors import ValidationError
from ..extensions import db

bp = Blueprint("items", __name__)


@bp.route("/")
@login_required
def dashboard():
    summary = services.inventory_summary(current_app.config["EXPIRY_WARNING_DAYS"])
    return render_template("dashboard.html", summary=summary)


@bp.route("/items")
@login_required
def list_items():
    keyword = request.args.get("q", "").strip()
    category = request.args.get("category", "")
    low_stock = request.args.get("low_stock") == "1"
    page = request.args.get("page", 1, type=int)

    stmt = services.search_items(keyword, category, low_stock)
    pagination = db.paginate(
        stmt, page=page, per_page=current_app.config["ITEMS_PER_PAGE"], error_out=False
    )
    return render_template(
        "items/list.html",
        pagination=pagination,
        q=keyword,
        category=category,
        low_stock=low_stock,
    )


@bp.route("/items/new", methods=["GET", "POST"])
@login_required
def create_item():
    errors = {}
    if request.method == "POST":
        try:
            item = services.create_item(request.form, current_user)
            flash(f"已新增 {item.code} {item.name}", "success")
            return redirect(url_for("items.item_detail", item_id=item.id))
        except ValidationError as err:
            # 驗證失敗：留在原頁，保留使用者輸入的值並顯示各欄位錯誤
            errors = err.details
    return render_template("items/form.html", item=None, form=request.form, errors=errors)


@bp.route("/items/<int:item_id>")
@login_required
def item_detail(item_id):
    item = services.get_item_or_404(item_id)
    transactions = item.transactions.limit(50).all()
    return render_template("items/detail.html", item=item, transactions=transactions)


@bp.route("/items/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit_item(item_id):
    item = services.get_item_or_404(item_id)
    errors = {}
    if request.method == "POST":
        try:
            # 表單會送出所有欄位，所以用完整驗證（partial=False）
            services.update_item(item, request.form, partial=False)
            flash("已儲存", "success")
            return redirect(url_for("items.item_detail", item_id=item.id))
        except ValidationError as err:
            errors = err.details
    return render_template("items/form.html", item=item, form=request.form, errors=errors)


@bp.route("/items/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_item(item_id):
    item = services.get_item_or_404(item_id)
    code = item.code
    services.delete_item(item, current_user)  # 非管理員會丟 PermissionDenied
    flash(f"已刪除 {code}", "success")
    return redirect(url_for("items.list_items"))


@bp.route("/items/<int:item_id>/stock", methods=["POST"])
@login_required
def stock_change(item_id):
    item = services.get_item_or_404(item_id)
    txn = services.record_transaction(item, request.form, current_user)
    label = "入庫" if txn.txn_type == "IN" else "出庫"
    flash(f"{label} {txn.quantity} {item.unit}，結存 {txn.balance_after}", "success")
    return redirect(url_for("items.item_detail", item_id=item.id))
