"""
網頁版會員功能：註冊、登入、登出（使用 Session Cookie）。
API 的登入在 app/api/routes.py，用的是 Bearer Token。
"""
from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..errors import AppError
from ..extensions import db, login_manager
from ..models import User
from .. import services

bp = Blueprint("auth", __name__)


@login_manager.user_loader
def load_user(user_id):
    """每個請求 Flask-Login 會用 Session 裡的 user_id 呼叫這裡取回使用者"""
    return db.session.get(User, int(user_id))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("items.dashboard"))

    if request.method == "POST":
        user = services.authenticate(request.form.get("username"), request.form.get("password"))
        if user:
            login_user(user, remember=bool(request.form.get("remember")))
            flash(f"歡迎回來，{user.display_name}", "success")
            # 只允許站內跳轉，避免 Open Redirect 弱點
            next_url = request.args.get("next")
            if not next_url or urlsplit(next_url).netloc:
                next_url = url_for("items.dashboard")
            return redirect(next_url)
        flash("帳號或密碼錯誤", "danger")

    return render_template("auth/login.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("items.dashboard"))

    errors = {}
    if request.method == "POST":
        if request.form.get("password") != request.form.get("password_confirm"):
            errors["password_confirm"] = "兩次密碼不一致"
        else:
            try:
                services.register_user(
                    request.form.get("username"),
                    request.form.get("password"),
                    request.form.get("display_name"),
                )
                flash("註冊成功，請登入", "success")
                return redirect(url_for("auth.login"))
            except AppError as err:
                errors = err.details or {"_": err.message}

    return render_template("auth/register.html", errors=errors, form=request.form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("已登出", "info")
    return redirect(url_for("auth.login"))
