"""结构化日志：JSON 单行输出（stdout → Docker logs / journald），含 HTTP 访问日志中间件。

定位线上问题的关键：日志必须是可 grep 的结构化行，而非花哨的彩色多行。
每行一条 JSON：{ts, level, logger, msg, ...业务字段}；访问日志额外带
method/path/status/duration_ms/ip；>=500 或未捕获异常记 ERROR 并带 exc。
"""
import json
import logging
import sys
import time

from fastapi import Request

# 访问日志额外字段（通过 extra 注入）
_EXTRA_FIELDS = ("method", "path", "status", "duration_ms", "ip", "user_id", "event", "request_id")

request_logger = logging.getLogger("app.request")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for k in _EXTRA_FIELDS:
            v = getattr(record, k, None)
            if v is not None:
                payload[k] = v
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging() -> None:
    """幂等初始化：JSON handler 挂到 root，关 uvicorn 默认访问日志（用自建中间件替代）。"""
    root = logging.getLogger()
    if any(getattr(h, "_json_handler", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._json_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").disabled = True  # 统一访问日志格式
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("aiormq").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    return xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")


async def access_log_middleware(request: Request, call_next):
    """记录每个 HTTP 请求：方法/路径/状态/耗时/IP。>=500 或异常记 ERROR。"""
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    except Exception:
        request_logger.exception(
            "request failed", extra={"method": request.method, "path": request.url.path, "ip": _client_ip(request)}
        )
        raise
    finally:
        duration = round((time.perf_counter() - start) * 1000, 1)
        request_logger.log(
            logging.ERROR if status >= 500 else logging.INFO,
            "request",
            extra={
                "method": request.method, "path": request.url.path, "status": status,
                "duration_ms": duration, "ip": _client_ip(request),
            },
        )
