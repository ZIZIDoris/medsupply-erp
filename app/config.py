"""
設定檔：所有「會因環境不同而改變」的值都放這裡，並且優先讀環境變數。

對照 C#：這裡的角色就像 appsettings.json + IConfiguration。
資料庫連線字串 DATABASE_URL 就相當於 ConnectionStrings:DefaultConnection。
"""
import os
from pathlib import Path

# 專案根目錄（app/ 的上一層）
BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    # Session 與 API Token 簽章用的金鑰，正式環境一定要改成隨機長字串
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    # 資料庫連線字串（SQLAlchemy URL 格式）
    # 預設用 SQLite 檔案；換成 MySQL / PostgreSQL / SQL Server 只要改環境變數，程式碼不用動：
    #   mysql+pymysql://user:pass@localhost:3306/medsupply?charset=utf8mb4
    #   postgresql+psycopg://user:pass@localhost:5432/medsupply
    #   mssql+pyodbc://user:pass@localhost/medsupply?driver=ODBC+Driver+18+for+SQL+Server
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'medsupply.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # SQL_ECHO=1 時會把每一句實際執行的 SQL 印出來，除錯時非常好用
    SQLALCHEMY_ECHO = os.environ.get("SQL_ECHO", "0") == "1"

    # API Token 有效秒數（預設 8 小時，約一個班別）
    API_TOKEN_MAX_AGE = int(os.environ.get("API_TOKEN_MAX_AGE", 8 * 3600))

    # 日誌設定：LOG_DIR 設為空字串就只輸出到終端機
    LOG_DIR = os.environ.get("LOG_DIR", str(BASE_DIR / "logs"))
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    # 表單 CSRF 防護（測試時關閉，方便直接 POST）
    CSRF_ENABLED = True

    # 效期預警天數：幾天內到期就列入警示
    EXPIRY_WARNING_DAYS = int(os.environ.get("EXPIRY_WARNING_DAYS", 30))

    # 列表每頁筆數
    ITEMS_PER_PAGE = 20


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    # 測試用記憶體資料庫，每次測試都是乾淨的
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ECHO = False
    LOG_DIR = ""
    LOG_LEVEL = "WARNING"
    CSRF_ENABLED = False
