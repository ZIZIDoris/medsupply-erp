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

技術：Flask 3、Flask-SQLAlchemy（ORM）、Flask-Login、Flask-Migrate（Alembic）、PostgreSQL（psycopg 3；也可用 SQLite / MySQL / SQL Server）、pytest

---

## 快速開始

預設資料庫為 **PostgreSQL**（在 `.env` 設定 `DATABASE_URL`）。沒有設定 `DATABASE_URL` 時，會自動改用 SQLite 檔案 `instance/medsupply.db`，詳見[使用 SQLite](#使用-sqlite不用裝資料庫)。

```bash
# 1. 建立虛擬環境並安裝套件（已包含 PostgreSQL 驅動 psycopg）
python -m venv .venv
source .venv/bin/activate          # Windows：.venv\Scripts\activate
pip install -r requirements.txt

# 2. 設定連線：複製 .env.example 為 .env，修改 DATABASE_URL 的帳號密碼
#    DATABASE_URL=postgresql+psycopg://postgres:<密碼>@localhost:5432/medsupply
#    （.env 已列在 .gitignore，不會被 commit）

# 3. 建立資料表（依 migrations/ 內的版本）
flask db upgrade

# 4. 建立測試帳號與範例資料
flask seed

# 5. 啟動
flask run
```

打開 http://127.0.0.1:5000 ，用 `admin / admin1234`（管理員）或 `nurse01 / nurse1234`（一般使用者）登入。

確認目前連到哪種資料庫：

```bash
curl -s localhost:5000/api/v1/health
# {"status": "ok", "database": "postgresql"}
```

執行測試：

```bash
pytest -v
```

> 測試使用 `TestConfig`，固定連到 SQLite 記憶體資料庫（`sqlite:///:memory:`），每個測試都是全新的資料庫，不會動到 PostgreSQL 裡的資料。

---

## PostgreSQL 免安裝版（Windows zip）

不想執行安裝程式時，可以下載 PostgreSQL 的 Windows zip 版，解壓縮後直接使用。以下假設程式在 `C:\pgsql\bin`、資料放在 `C:\pgdata`（路徑可自行更換）。

**第一次：初始化資料目錄**（只做一次）

```powershell
# -U 超級使用者名稱、-E 編碼、-W 會提示輸入密碼、--auth 要求連線時驗證密碼
C:\pgsql\bin\initdb.exe -D C:\pgdata -U postgres -E UTF8 --locale=C -W --auth=scram-sha-256
```

**啟動 / 停止伺服器**

```powershell
# 啟動（-l 指定日誌檔，啟動失敗時可看這個檔案找原因）
C:\pgsql\bin\pg_ctl.exe -D C:\pgdata -l C:\pgdata\server.log start

# 查看狀態 / 停止
C:\pgsql\bin\pg_ctl.exe -D C:\pgdata status
C:\pgsql\bin\pg_ctl.exe -D C:\pgdata stop

# 確認是否在 5432 port 接受連線
C:\pgsql\bin\pg_isready.exe -h localhost -p 5432
```

**建立資料庫**（只做一次）

```powershell
C:\pgsql\bin\createdb.exe -h localhost -U postgres -E UTF8 medsupply
```

接著回到[快速開始](#快速開始)的步驟 2，設定 `.env` 後執行 `flask db upgrade`、`flask seed`。

> 密碼若含 `@ : / # ? %` 等特殊字元，放進 `DATABASE_URL` 時要做 URL 編碼，例如 `@` 寫成 `%40`、`#` 寫成 `%23`。

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

## 使用 SQLite（不用裝資料庫）

SQLite 內建在 Python 裡，不必另外安裝資料庫伺服器，適合快速試用。只要 `.env` **不設定** `DATABASE_URL`（把那一行刪掉或在前面加 `#` 註解掉），程式就會使用 `instance/medsupply.db`：

```bash
# .env
# DATABASE_URL=postgresql+psycopg://postgres:<密碼>@localhost:5432/medsupply

flask db upgrade
flask seed
flask run
```

此時 `/api/v1/health` 會回傳 `"database": "sqlite"`。

---

## 換成其他資料庫

在 `.env` 設定 `DATABASE_URL`，安裝對應驅動後執行 `flask db upgrade`：

```bash
# PostgreSQL（預設，驅動已在 requirements.txt）
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/medsupply

# SQL Server
pip install pyodbc
DATABASE_URL=mssql+pyodbc://user:pass@localhost/medsupply?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes

# MySQL
pip install PyMySQL
DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/medsupply?charset=utf8mb4
```

程式碼完全不用改：`app/config.py` 從環境變數讀取 `DATABASE_URL`，SQLAlchemy 依網址前綴自動選擇對應的資料庫方言與驅動。

---

## 用 Codex CLI 繼續擴充

專案根目錄的 `AGENTS.md` 寫好了架構規則，Codex CLI 啟動時會自動讀取。可以拿這些題目練習（建議先自己想要改哪些檔案，再讓 Codex 做，最後對照差異）：

1. 「在 Item 新增 `manufacturer`（廠商，選填，最多 100 字）欄位，網頁表單、API、驗證、測試都要更新，並產生 migration」
2. 「新增 `GET /api/v1/items/export.csv`，匯出目前搜尋條件下的耗材清單」
3. 「新增稽核紀錄表 audit_logs，記錄誰在什麼時間修改了哪個欄位、舊值與新值」
4. 「把刪除改成軟刪除（is_active 欄位），列表預設不顯示停用品項」
5. 「新增 `GET /api/v1/stats/daily-usage?days=90`，回傳每日出庫量時間序列」

每做完一題都執行 `pytest`，確認沒有破壞既有功能。
