"""
擴充套件集中在這裡建立，再於 create_app() 裡 init_app()。
這樣做可以避免循環 import（models 要用 db、app 也要用 db）。
"""
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

# ORM：相當於 C# 的 Entity Framework DbContext
db = SQLAlchemy()

# 資料庫版本控管（Alembic）：相當於 EF Core 的 Migrations
migrate = Migrate()

# 網頁登入狀態管理（Session / Cookie）
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "請先登入"
login_manager.login_message_category = "warning"
