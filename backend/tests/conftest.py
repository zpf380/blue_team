"""pytest 配置。

- 单元测试不依赖数据库。
- 集成测试（client fixture）使用独立 NullPool 引擎，避免连接跨事件循环复用；
  需要 PostgreSQL 可用，否则自动跳过。
"""
import asyncio
import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.services.scanner as scanner_mod
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models import User
from app.services import notify as notify_mod

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", settings.DATABASE_URL)

# 测试环境关闭「管理员强制 MFA」：否则所有用 admin 登录的存量测试都要走 TOTP 流程。
# MFA 功能本身由 test_auth_api.py 专项测试覆盖（用普通账号手动启用）。
settings.MFA_FORCE_ROLES = []


async def _db_available(url: str) -> bool:
    try:
        engine = create_async_engine(url)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def db_available() -> bool:
    return asyncio.run(_db_available(TEST_DB_URL))


@pytest.fixture(scope="session", autouse=True)
def purge_test_subnet_residue(db_available):
    """每次测试会话开始时，物理清理历史残留的测试子网/分配（10.2xx / 172.16 前缀，均为测试网段）。

    单段随机网段的子网测试（10.201-10.205.x 等）创建后不删子网，跨 pytest 运行累积残留，
    随机网段会撞「该网段已登记」→ flaky。本清理只针对测试网段，seed（10.0.x）不受影响。
    """
    if not db_available:
        return
    from sqlalchemy import text
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)

    async def _purge():
        async with engine.begin() as conn:
            # 先删引用残留子网的发现/巡检记录（subnet_id 外键），再删分配与子网
            await conn.execute(text(
                "DELETE FROM network_discoveries WHERE network::text LIKE '10.2%' OR network::text LIKE '172.16%'"
            ))
            await conn.execute(text(
                "DELETE FROM device_patrols WHERE network::text LIKE '10.2%' OR network::text LIKE '172.16%'"
            ))
            await conn.execute(text(
                "DELETE FROM ip_allocations WHERE ip_address::text LIKE '10.2%' OR ip_address::text LIKE '172.16%'"
            ))
            # 测试自身未清理的残留分配（数据范围测试在 seed 办公网 10.0.0.x 上逐次新建、不删）：
            # 随机 IP 撞旧残留 → 409 → flaky。按目的标签兜底清理（seed 静态分配不含此标签，不受影响）
            await conn.execute(text("DELETE FROM ip_allocations WHERE purpose = '数据范围测试'"))
            # 扫描自动告警残留（target 为随机测试网段，未清理则随机 target 撞旧告警 → dedup 短路 → flaky）。
            # 只清「扫描发现高风险」这一扫描自动生成的告警，人工/手动告警不受影响
            await conn.execute(text("DELETE FROM alerts WHERE title LIKE '扫描发现高风险：%'"))
            # 测试网段设备（网络发现/巡检测试创建）同样清掉，防跨运行累积（名称/状态断言撞车）；
            # 10.7% 为 devices_import_csv 的导入测试网段（测试自清理 + 此处兜底）；
            # 10.0.99% 为 _uniq_ip() 设备测试专用网段（测试正常自清理，此处兜底被中断的运行残留）
            # 先删 10.0.99% 设备被引用记录（归档删除保护测试可能残留 scan_report 引用），再删设备
            await conn.execute(text(
                "DELETE FROM scan_reports WHERE device_id IN (SELECT id FROM devices WHERE ip_address::text LIKE '10.0.99.%')"
            ))
            await conn.execute(text(
                "DELETE FROM alerts WHERE device_id IN (SELECT id FROM devices WHERE ip_address::text LIKE '10.0.99.%')"
            ))
            await conn.execute(text(
                "DELETE FROM ip_allocations WHERE device_id IN (SELECT id FROM devices WHERE ip_address::text LIKE '10.0.99.%')"
            ))
            await conn.execute(text(
                "DELETE FROM devices WHERE ip_address::text LIKE '10.2%' OR ip_address::text LIKE '172.16%' OR ip_address::text LIKE '10.7.%' OR ip_address::text LIKE '10.0.99.%'"
            ))
            await conn.execute(text(
                "DELETE FROM ip_subnets WHERE network::text LIKE '10.2%' OR network::text LIKE '172.16%'"
            ))

    asyncio.run(_purge())
    engine.dispose()


@pytest.fixture
async def client(db_available):
    """集成测试客户端：独立 NullPool 引擎 + get_db 依赖覆盖。"""
    if not db_available:
        pytest.skip("PostgreSQL 未就绪，跳过集成测试")

    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    TestSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 重置账号锁定 / MFA 状态，避免跨多次运行累积失败次数与绑定残留
    async with TestSession() as s:
        await s.execute(
            update(User).values(
                failed_attempts=0, locked_until=None,
                totp_enabled=False, totp_secret=None, totp_confirmed_at=None,
            )
        )
        await s.commit()

    async def _override_db():
        async with TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    # scanner / notify / patrol 后台任务也使用 NullPool 引擎的会话，避免连接跨事件循环复用崩溃
    scanner_mod.AsyncSessionLocal = TestSession
    notify_mod.AsyncSessionLocal = TestSession
    import app.services.patrol as patrol_mod
    patrol_mod.AsyncSessionLocal = TestSession
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
async def test_session(client):
    """与集成测试同一连接池的会话（用于直接查询 DB 验证落库/审计）。"""
    from app.services.scanner import AsyncSessionLocal as ScannerSession

    async with ScannerSession() as s:
        yield s
