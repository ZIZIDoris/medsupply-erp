"""
API 驗證：登入後發一組有時效、經簽章的 Token。
之後每次呼叫 API 都要帶 Header：  Authorization: Bearer <token>

Token 用 itsdangerous 簽章（與 Flask Session 同一套機制），
內容只有 user id，伺服器用 SECRET_KEY 驗證沒被竄改、也沒過期。
概念上和 JWT 一樣：伺服器不需要另外存 Token。
"""
from functools import wraps

from flask import current_app, g, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..errors import AuthError, PermissionDenied
from ..extensions import db
from ..models import User

TOKEN_SALT = "api-token"


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=TOKEN_SALT)


def generate_token(user):
    return _serializer().dumps({"uid": user.id})


def verify_token(token):
    try:
        data = _serializer().loads(token, max_age=current_app.config["API_TOKEN_MAX_AGE"])
    except SignatureExpired:
        raise AuthError("Token 已過期，請重新登入")
    except BadSignature:
        raise AuthError("Token 無效")
    user = db.session.get(User, data.get("uid"))
    if user is None:
        raise AuthError("使用者不存在")
    return user


def token_required(view):
    """裝飾器：沒帶或帶錯 Token 就回 401"""

    @wraps(view)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise AuthError("缺少 Authorization: Bearer <token>")
        g.api_user = verify_token(header[len("Bearer "):].strip())
        g.api_user_name = g.api_user.username  # 給請求 log 使用
        return view(*args, **kwargs)

    return wrapper


def admin_required(view):
    """裝飾器：必須是管理員（要放在 token_required 下面）"""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not g.api_user.is_admin:
            raise PermissionDenied("需要管理員權限")
        return view(*args, **kwargs)

    return wrapper
