# AGENTS.md — 給 AI 開發助手的專案規則

## 專案
Flask 醫療耗材庫存管理系統（ERP 庫存模組）。網頁 + REST API 共用同一套商業邏輯。

## 分層規則（一定要遵守）
- `app/models.py`：只放資料表定義與 `to_dict()`，不放商業規則。
- `app/services.py`：所有驗證、CRUD、庫存計算、統計都寫在這裡。網頁與 API 都呼叫這裡。
- `app/items/routes.py`、`app/api/routes.py`：只負責取參數、呼叫 service、回傳頁面或 JSON。
- 錯誤一律 `raise` `app/errors.py` 裡的例外（ValidationError / BusinessError / NotFoundError …），不要在 route 裡自己組錯誤 JSON。
- 庫存量 `Item.quantity` 只能透過 `services._apply_stock_change()` 修改，不可直接 setattr。

## 修改資料表欄位時
1. 改 `app/models.py`（含 `to_dict()`）
2. 改 `services.clean_item_data()` 驗證
3. 改 `app/templates/items/form.html`（必要時 list / detail）
4. 執行 `flask db migrate -m "說明"`，檢查 `migrations/versions/` 產生的檔案後再 `flask db upgrade`
5. 補測試

## 風格
- 程式碼註解、錯誤訊息、UI 文字使用繁體中文。
- 新增功能必須附 pytest 測試；完成後執行 `pytest -q` 必須全部通過。
- 使用 SQLAlchemy 2.0 寫法（`select()`、`db.session.scalar()`），不要用舊的 `Model.query`。
