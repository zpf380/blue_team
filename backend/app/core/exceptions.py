"""统一业务异常与 FastAPI 异常处理器 → 统一响应体 {code,message,data}。"""
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError, IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

# 业务错误码
OK = 0
ERR_VALIDATION = 40001
ERR_UNAUTHORIZED = 40100
ERR_FORBIDDEN = 40301
ERR_FORBIDDEN_PERM = 40302
ERR_NOT_FOUND = 40400
ERR_CONFLICT = 40900
ERR_RATE_LIMIT = 42900
ERR_INTERNAL = 50000


class AppError(Exception):
    """业务异常。"""

    def __init__(self, code: int = ERR_INTERNAL, message: str = "服务器内部错误", data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_req: Request, exc: AppError):
        return JSONResponse(status_code=200 if exc.code == OK else 200, content=ok_response(
            code=exc.code, message=exc.message, data=exc.data))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_req: Request, exc: StarletteHTTPException):
        # 401 -> 统一未认证；403 -> 统一无权限；404/405 -> 资源不存在
        code = ERR_UNAUTHORIZED if exc.status_code == 401 else (
            ERR_FORBIDDEN_PERM if exc.status_code == 403 else (
                ERR_NOT_FOUND if exc.status_code in (404, 405) else ERR_INTERNAL))
        message = str(exc.detail) if exc.status_code not in (401, 403, 404, 405) else (
            "认证失败" if exc.status_code == 401 else (
                "无权访问" if exc.status_code == 403 else "资源不存在"))
        return JSONResponse(status_code=exc.status_code, content=ok_response(code=code, message=message))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_req: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content=ok_response(
            code=ERR_VALIDATION, message="参数校验失败", data=exc.errors()))

    # 兜底：未显式校验/捕获的外键冲突（物理删除被引用行）、字段类型/长度超限 → 不再裸 500
    @app.exception_handler(IntegrityError)
    async def _integrity_error(_req: Request, exc: IntegrityError):
        return JSONResponse(status_code=200, content=ok_response(
            code=ERR_CONFLICT, message="数据存在引用或唯一性冲突，无法完成操作"))

    @app.exception_handler(DataError)
    async def _data_error(_req: Request, exc: DataError):
        return JSONResponse(status_code=200, content=ok_response(
            code=ERR_VALIDATION, message="数据格式或长度不符合要求"))


def ok_response(code: int = OK, message: str = "ok", data: Any = None) -> dict:
    return {"code": code, "message": message, "data": data}
