"""
REST API（前綴 /api/v1）

  方法    路徑                              說明
  GET     /health                           健康檢查（含資料庫連線測試）
  POST    /auth/login                       登入取得 Token
  GET     /me                               目前登入者
  GET     /items                            列表（?q=&category=&low_stock=1&page=&per_page=）
  POST    /items                            新增
  GET     /items/<id>                       單筆
  PUT     /items/<id>                       完整更新
  PATCH   /items/<id>                       部分更新
  DELETE  /items/<id>                       刪除（管理員）
  GET     /items/<id>/transactions          異動紀錄
  POST    /items/<id>/transactions          入庫 / 出庫
  GET     /stats/summary                    庫存統計（分類、低庫存、效期、領用排行）

成功：回傳資料本身（或 {"data": ..., "meta": ...}）
失敗：{"error": {"code", "message", "details", "request_id"}}
"""
import logging

from flask import Blueprint, current_app, g, jsonify, request, url_for
from sqlalchemy import text

from .. import services
from ..errors import AuthError, ValidationError
from ..extensions import db
from .auth import admin_required, generate_token, token_required

bp = Blueprint("api", __name__)
logger = logging.getLogger(__name__)


def _json_body():
    """取得 JSON 內容；不是 JSON 就回 422，避免後面出現看不懂的 AttributeError"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("請求內容必須是 JSON 物件，並設定 Content-Type: application/json")
    return data


@bp.get("/health")
def health():
    # 實際對資料庫下一句 SELECT 1，確認連線正常
    db.session.execute(text("SELECT 1"))
    return {"status": "ok", "database": db.engine.dialect.name}


@bp.post("/auth/login")
def login():
    data = _json_body()
    user = services.authenticate(data.get("username"), data.get("password"))
    if user is None:
        raise AuthError("帳號或密碼錯誤")
    return {
        "token": generate_token(user),
        "token_type": "Bearer",
        "expires_in": current_app.config["API_TOKEN_MAX_AGE"],
        "user": user.to_dict(),
    }


@bp.get("/me")
@token_required
def me():
    return g.api_user.to_dict()


@bp.get("/items")
@token_required
def list_items():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)  # 上限 100 筆
    stmt = services.search_items(
        request.args.get("q"),
        request.args.get("category"),
        request.args.get("low_stock") == "1",
    )
    pagination = db.paginate(stmt, page=page, per_page=per_page, error_out=False)
    return {
        "data": [item.to_dict() for item in pagination.items],
        "meta": {
            "page": pagination.page,
            "per_page": pagination.per_page,
            "total": pagination.total,
            "pages": pagination.pages,
        },
    }


@bp.post("/items")
@token_required
def create_item():
    item = services.create_item(_json_body(), g.api_user)
    response = jsonify(item.to_dict())
    response.status_code = 201
    response.headers["Location"] = url_for("api.get_item", item_id=item.id)
    return response


@bp.get("/items/<int:item_id>")
@token_required
def get_item(item_id):
    return services.get_item_or_404(item_id).to_dict()


@bp.route("/items/<int:item_id>", methods=["PUT", "PATCH"])
@token_required
def update_item(item_id):
    item = services.get_item_or_404(item_id)
    # PUT 要求必填欄位都要給；PATCH 只更新有傳的欄位
    services.update_item(item, _json_body(), partial=(request.method == "PATCH"))
    return item.to_dict()


@bp.delete("/items/<int:item_id>")
@token_required
@admin_required
def delete_item(item_id):
    services.delete_item(services.get_item_or_404(item_id), g.api_user)
    return "", 204


@bp.get("/items/<int:item_id>/transactions")
@token_required
def list_transactions(item_id):
    item = services.get_item_or_404(item_id)
    limit = min(request.args.get("limit", 50, type=int), 500)
    return {"data": [t.to_dict() for t in item.transactions.limit(limit)]}


@bp.post("/items/<int:item_id>/transactions")
@token_required
def create_transaction(item_id):
    item = services.get_item_or_404(item_id)
    txn = services.record_transaction(item, _json_body(), g.api_user)
    return {"transaction": txn.to_dict(), "item": item.to_dict()}, 201


@bp.get("/stats/summary")
@token_required
def stats_summary():
    expiry_days = request.args.get("expiry_days", current_app.config["EXPIRY_WARNING_DAYS"], type=int)
    usage_days = request.args.get("usage_days", 30, type=int)
    return services.inventory_summary(expiry_days, usage_days)
