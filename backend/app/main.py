"""FastAPI 应用入口。"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from app.api.v1.monitor import _recycle_expired_leases
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import ok_response, register_exception_handlers
from app.core.logging import access_log_middleware, setup_logging
from app.db.session import AsyncSessionLocal
from app.models import NetworkDiscovery, ScanReport
from app.services.leave_status import _switch_due_leave_statuses
from app.services.patrol import patrol_all_subnets
from app.ws.manager import heartbeat_loop
from app.ws.routes import register_websocket

logger = logging.getLogger("app.scheduler")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 服务重启兜底：把遗留的 pending/running 扫描与发现标记为 failed（进程内任务随 worker 消失）
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(ScanReport)
            .where(ScanReport.scan_status.in_(["pending", "running"]))
            .values(scan_status="failed", error="服务重启导致扫描中断")
        )
        await session.execute(
            update(NetworkDiscovery)
            .where(NetworkDiscovery.scan_status.in_(["pending", "running"]))
            .values(scan_status="failed", error="服务重启导致发现中断")
        )
        await session.commit()

    async def _lease_recycle_loop() -> None:
        """定时回收过期 DHCP 租约（惰性回收之外的后台兜底，静默失败）。"""
        while True:
            try:
                async with AsyncSessionLocal() as session:
                    n = await _recycle_expired_leases(session)
                if n:
                    logger.info("定时回收过期租约 %d 条", n)
            except Exception:  # noqa: BLE001 —— 后台任务任何异常都不能拖垮进程
                logger.exception("定时租约回收失败")
            await asyncio.sleep(settings.LEASE_RECYCLE_INTERVAL_MINUTES * 60)

    async def _leave_status_loop() -> None:
        """定时按休假/外勤申请的 start_at/end_at 自动切换用户状态（静默失败）。"""
        while True:
            try:
                async with AsyncSessionLocal() as session:
                    started, ended = await _switch_due_leave_statuses(session)
                if started or ended:
                    logger.info("自动切换休假/外勤状态：生效 %d 条，恢复 %d 条", started, ended)
            except Exception:  # noqa: BLE001 —— 后台任务任何异常都不能拖垮进程
                logger.exception("定时切换休假/外勤状态失败")
            await asyncio.sleep(settings.LEAVE_AUTO_SWITCH_INTERVAL_MINUTES * 60)

    async def _patrol_loop() -> None:
        """定时对 active 子网做设备在线巡检，刷新设备状态（静默失败）。"""
        while True:
            try:
                stats = await patrol_all_subnets()
                if not stats.get("skipped") and stats.get("subnets"):
                    logger.info(
                        "设备巡检完成：%d 个子网，在线 %d / 幽灵 %d / 离线 %d",
                        stats["subnets"], stats["online"], stats["ghost"], stats["offline"],
                    )
            except Exception:  # noqa: BLE001 —— 后台任务任何异常都不能拖垮进程
                logger.exception("定时设备巡检失败")
            await asyncio.sleep(settings.DEVICE_PATROL_INTERVAL_MINUTES * 60)

    task = asyncio.create_task(heartbeat_loop())
    recycle_task = asyncio.create_task(_lease_recycle_loop())
    leave_task = asyncio.create_task(_leave_status_loop())
    patrol_task = asyncio.create_task(_patrol_loop())
    yield
    task.cancel()
    recycle_task.cancel()
    leave_task.cancel()
    patrol_task.cancel()


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(
        title=settings.PROJECT_NAME, docs_url="/docs", openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(access_log_middleware)
    register_exception_handlers(app)
    register_websocket(app)

    @app.get("/health", tags=["系统"])
    async def health():
        return ok_response(data={"status": "up"})

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    return app


app = create_app()
