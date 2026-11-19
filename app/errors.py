"""
自訂例外：商業邏輯層只負責「丟出有意義的錯誤」，
要回傳 JSON 還是網頁訊息，交給 app/__init__.py 的錯誤處理器統一決定。

對照 C#：類似自訂 Exception + 全域 Exception Filter / Middleware。
"""


class AppError(Exception):
    """所有可預期錯誤的基底類別"""

    status_code = 400
    code = "bad_request"

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        # details 通常放「哪個欄位錯了」的字典，例如 {"code": "必填"}
        self.details = details or {}


class ValidationError(AppError):
    """輸入資料格式錯誤"""

    status_code = 422
    code = "validation_error"


class AuthError(AppError):
    """未登入或 Token 無效"""

    status_code = 401
    code = "unauthorized"


class PermissionDenied(AppError):
    """已登入但權限不足"""

    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    """資料不存在"""

    status_code = 404
    code = "not_found"


class BusinessError(AppError):
    """違反商業規則，例如庫存不足、料號重複"""

    status_code = 409
    code = "business_rule"
