# MedSupply｜醫療耗材庫存管理系統

以 ERP「庫存管理模組」為原型，改用 **Python Flask** 重新實作，套用在醫院耗材管理情境。

| 功能 | 內容 |
|---|---|
| 會員 | 註冊、登入、登出、角色權限（admin / staff）、密碼雜湊、CSRF 防護 |
| CRUD | 耗材主檔新增 / 查詢（搜尋、分類、分頁）/ 修改 / 刪除 |
| 庫存 | 入庫、出庫、異動紀錄、庫存不足檢查（條件式 UPDATE 防止扣成負數） |
| 儀表板 | 分類庫存金額、低於安全庫存、效期預警、各單位領用量排行 |
| REST API | Bearer Token 驗證、統一 JSON 錯誤格式、統計 API |
| 維運 | 資料庫 Migration、請求日誌、request_id 錯誤追蹤、pytest 27 個測試 |

技術：Flask 3、Flask-SQLAlchemy（ORM）、Flask-Login、Flask-Migrate（Alembic）、SQLite（可換 MySQL / SQL Server / PostgreSQL）、pytest

---

## 快速開始

```bash
# 1. 建立虛擬環境並安裝套件
python -m venv .venv
source .venv/bin/activate          # Windows：.venv\Scripts\activate
pip install -r requirements.txt

# 2. 建立資料表（依 migrations/ 內的版本）
flask db upgrade

# 3. 建立測試帳號與範例資料
flask seed

# 4. 啟動
flask run
```

打開 http://127.0.0.1:5000 ，用 `admin / admin1234`（管理員）或 `nurse01 / nurse1234`（一般使用者）登入。

執行測試：

```bash
pytest -v
```

---

## 專案結構

```
medsupply-erp/
├── run.py                 # 進入點：app = create_app()
├── app/
│   ├── __init__.py        # create_app()：組裝設定、DB、日誌、Blueprint、錯誤處理
│   ├── config.py          # 設定（連線字串、密鑰、日誌…）
│   ├── extensions.py      # db / migrate / login_manager 實體
│   ├── models.py          # 資料表：User、Item、StockTransaction
│   ├── services.py        # 商業邏輯：驗證、CRUD、入出庫、統計（網頁與 API 共用）
│   ├── errors.py          # 自訂例外 → 統一轉成 HTTP 狀態碼
│   ├── cli.py             # flask seed / flask create-admin
│   ├── auth/routes.py     # 網頁登入註冊（Session）
│   ├── items/routes.py    # 網頁 CRUD
│   ├── api/auth.py        # API Token 簽發與驗證
│   ├── api/routes.py      # REST API
│   ├── templates/         # Jinja2 頁面
│   └── static/style.css
├── migrations/            # 資料庫版本（Alembic）
├── tests/                 # pytest
├── docs/
│   │   
│   └── api.http           # 可直接在 VS Code REST Client 執行的 API 範例
└── AGENTS.md              # 給 Codex CLI 讀的專案規則
```

---

## API 速覽

所有路徑前綴 `/api/v1`，除了 `/health` 與 `/auth/login` 之外都要帶 `Authorization: Bearer <token>`。

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/health` | 健康檢查（會實際對資料庫下 `SELECT 1`） |
| POST | `/auth/login` | 帳密換 Token |
| GET | `/me` | 目前使用者 |
| GET | `/items?q=&category=&low_stock=1&page=&per_page=` | 列表 |
| POST | `/items` | 新增（可帶 `initial_quantity` 期初庫存） |
| GET | `/items/{id}` | 單筆 |
| PUT / PATCH | `/items/{id}` | 完整 / 部分更新 |
| DELETE | `/items/{id}` | 刪除（管理員） |
| GET / POST | `/items/{id}/transactions` | 異動紀錄 / 入出庫 |
| GET | `/stats/summary?expiry_days=30&usage_days=30` | 庫存統計 |

```bash
TOKEN=$(curl -s -X POST localhost:5000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"nurse01","password":"nurse1234"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl -s localhost:5000/api/v1/items?low_stock=1 -H "Authorization: Bearer $TOKEN"

curl -s -X POST localhost:5000/api/v1/items/1/transactions \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"type":"OUT","quantity":10,"department":"急診"}'
```

錯誤回應格式固定：

```json
{"error": {"code": "business_rule", "message": "庫存不足：…", "details": {"quantity": "超過現有庫存"}, "request_id": "b154df02d945"}}
```

| 狀態碼 | 意義 |
|---|---|
| 200 / 201 / 204 | 成功 / 已建立 / 已刪除 |
| 401 | 沒帶 Token、Token 錯誤或過期、帳密錯誤 |
| 403 | 權限不足（例如 staff 刪除） |
| 404 | 資料不存在 |
| 409 | 違反商業規則（料號重複、庫存不足） |
| 422 | 輸入格式錯誤（`details` 會列出每個欄位） |
| 500 | 未預期錯誤，用 `request_id` 查 `logs/app.log` |

---

## 換成其他資料庫

複製 `.env.example` 為 `.env`，設定 `DATABASE_URL`，安裝對應驅動後執行 `flask db upgrade`：

```bash
# SQL Server
pip install pyodbc
DATABASE_URL=mssql+pyodbc://user:pass@localhost/medsupply?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes

# MySQL
pip install PyMySQL
DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/medsupply?charset=utf8mb4
```

程式碼完全不用改
---

## 用 Codex CLI 繼續擴充

專案根目錄的 `AGENTS.md` 寫好了架構規則，Codex CLI 啟動時會自動讀取。可以拿這些題目練習（建議先自己想要改哪些檔案，再讓 Codex 做，最後對照差異）：

1. 「在 Item 新增 `manufacturer`（廠商，選填，最多 100 字）欄位，網頁表單、API、驗證、測試都要更新，並產生 migration」
2. 「新增 `GET /api/v1/items/export.csv`，匯出目前搜尋條件下的耗材清單」
3. 「新增稽核紀錄表 audit_logs，記錄誰在什麼時間修改了哪個欄位、舊值與新值」
4. 「把刪除改成軟刪除（is_active 欄位），列表預設不顯示停用品項」
5. 「新增 `GET /api/v1/stats/daily-usage?days=90`，回傳每日出庫量時間序列」

每做完一題都執行 `pytest`，確認沒有破壞既有功能。
