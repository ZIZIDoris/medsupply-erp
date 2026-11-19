"""
Application Factory：create_app() 負責把所有元件組起來。

啟動流程：
  1. 讀設定（config.py + 環境變數 / .env）
  2. 初始化資料庫、Migrate、登入管理
  3. 設定日誌（每個請求都帶 request_id，方便追查錯誤）
  4. 註冊 Blueprint（網頁登入、耗材 CRUD、API）
  5. 註冊全域錯誤處理器
"""
import logging
import secrets
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user
from werkzeug.exceptions import HTTPException

from .config import Config
from .errors import AppError
from .extensions import db, login_manager, migrate


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    # JSON 直接輸出中文（不轉成 \uXXXX），並保留欄位原本順序
    app.json.ensure_ascii = False
    app.json.sort_keys = False
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    _setup_logging(app)
    _register_request_hooks(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    _register_template_helpers(app)

    from .cli import register_cli

    register_cli(app)

    # flask shell 進去時自動匯入常用物件，方便直接查資料
    @app.shell_context_processor
    def shell_context():
        from .models import Item, StockTransaction, User

        return {"db": db, "Item": Item, "User": User, "StockTransaction": StockTransaction}

    app.logger.info("應用程式啟動，資料庫=%s", _mask_db_url(app.config["SQLALCHEMY_DATABASE_URI"]))
    return app


# ---------------------------------------------------------------------------
# 日誌
# ---------------------------------------------------------------------------
class RequestIdFilter(logging.Filter):
    """把目前請求的 request_id 塞進每一筆 log"""

    def filter(self, record):
        from flask import has_request_context

        record.request_id = g.get("request_id", "-") if has_request_context() else "-"
        return True


def _setup_logging(app):
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"
    )
    handlers = [logging.StreamHandler()]

    # 寫到 logs/app.log，單檔 1MB、保留 5 個備份
    if app.config.get("LOG_DIR"):
        log_dir = Path(app.config["LOG_DIR"])
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_dir / "app.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
            )
        )

    app.logger.handlers.clear()  # 避免重複建立 app 時 log 印兩次
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(RequestIdFilter())
        app.logger.addHandler(handler)
    app.logger.setLevel(app.config.get("LOG_LEVEL", "INFO"))
    app.logger.propagate = False
    # app.services、app.api.routes 等子 logger 會把 log 往上傳給 app.logger


def _mask_db_url(url):
    """log 裡不要印出資料庫密碼"""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        return f"{scheme}://***@{rest.split('@', 1)[1]}"
    return url


# ---------------------------------------------------------------------------
# 請求前後的處理
# ---------------------------------------------------------------------------
def _register_request_hooks(app):
    @app.before_request
    def start_request():
        # 若前端 / 閘道已帶 X-Request-ID 就沿用，否則自己產生
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        g.start_time = time.perf_counter()

    @app.before_request
    def csrf_protect():
        """網頁表單的 CSRF 防護（API 用 Token，不需要）"""
        if not app.config.get("CSRF_ENABLED"):
            return
        if request.method != "POST" or request.path.startswith("/api/"):
            return
        token = session.get("_csrf_token")
        if not token or token != request.form.get("csrf_token"):
            app.logger.warning("CSRF 驗證失敗 path=%s", request.path)
            flash("表單已過期，請重新送出", "danger")
            return redirect(request.referrer or url_for("items.dashboard"))

    @app.after_request
    def log_request(response):
        if request.path.startswith("/static/"):
            return response
        elapsed_ms = (time.perf_counter() - g.get("start_time", time.perf_counter())) * 1000
        user = current_user.username if current_user.is_authenticated else g.get("api_user_name", "-")
        app.logger.info(
            "%s %s -> %s (%.1f ms) user=%s",
            request.method, request.full_path.rstrip("?"), response.status_code, elapsed_ms, user,
        )
        # 回應標頭帶回 request_id，前端或 Postman 看到錯誤時可以拿這串去查 log
        response.headers["X-Request-ID"] = g.get("request_id", "-")
        return response


def _register_blueprints(app):
    from .api.routes import bp as api_bp
    from .auth.routes import bp as auth_bp
    from .items.routes import bp as items_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(items_bp)
    app.register_blueprint(api_bp, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# 全域錯誤處理：API 一律回 JSON，網頁則顯示訊息或錯誤頁
# ---------------------------------------------------------------------------
def _wants_json():
    return request.path.startswith("/api/")


def _error_json(status, code, message, details=None):
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": g.get("request_id", "-"),
        }
    }
    return jsonify(body), status


def _register_error_handlers(app):
    @app.errorhandler(AppError)
    def handle_app_error(err):
        # 可預期的錯誤（驗證失敗、庫存不足……）記 WARNING 即可
        app.logger.warning("%s: %s %s", err.code, err.message, err.details)
        if _wants_json():
            return _error_json(err.status_code, err.code, err.message, err.details)
        msg = err.message
        if err.details:
            msg += "：" + "；".join(f"{k} {v}" for k, v in err.details.items())
        flash(msg, "danger")
        return redirect(request.referrer or url_for("items.dashboard"))

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        if _wants_json():
            return _error_json(err.code, err.name.lower().replace(" ", "_"), err.description)
        if err.code == 404:
            return render_template("errors/404.html"), 404
        return err

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # 非預期錯誤：記下完整 traceback，並把交易 rollback，避免 session 卡住
        db.session.rollback()
        app.logger.exception("未預期錯誤：%s", err)
        if _wants_json():
            return _error_json(500, "internal_error", "伺服器發生錯誤，請提供 request_id 給管理員")
        return render_template("errors/500.html", request_id=g.get("request_id", "-")), 500


# ---------------------------------------------------------------------------
# 樣板輔助
# ---------------------------------------------------------------------------
def _register_template_helpers(app):
    def csrf_token():
        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_hex(16)
        return session["_csrf_token"]

    @app.context_processor
    def inject_helpers():
        from .services import CATEGORIES

        return {"csrf_token": csrf_token, "CATEGORIES": CATEGORIES}
