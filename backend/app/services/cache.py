"""Redis 缓存封装：验证码 / 限流计数 / 临时状态。

设计：
- 每次操作使用独立短连接（避免跨事件循环复用连接的问题），
  验证码 / 限流均属低频操作，建连开销可忽略。
- Redis 不可达时所有操作静默降级（返回 None/False），
  不影响核心业务（验证码/限流属增强防护，非硬依赖）。
"""
from redis import asyncio as aioredis

from app.core.config import settings


async def _open():
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def redis_get(key: str) -> str | None:
    r = None
    try:
        r = await _open()
        return await r.get(key)
    except Exception:
        return None
    finally:
        if r is not None:
            await r.aclose()


async def redis_set(key: str, value: str, ttl: int) -> bool:
    r = None
    try:
        r = await _open()
        await r.set(key, value, ex=ttl)
        return True
    except Exception:
        return False
    finally:
        if r is not None:
            await r.aclose()


async def redis_del(key: str) -> None:
    r = None
    try:
        r = await _open()
        await r.delete(key)
    except Exception:
        pass
    finally:
        if r is not None:
            await r.aclose()


async def redis_incr(key: str, ttl: int) -> int | None:
    """自增并设置 TTL（首次自增时生效）。返回当前计数值。"""
    r = None
    try:
        r = await _open()
        val = await r.incr(key)
        if val == 1:
            await r.expire(key, ttl)
        return int(val)
    except Exception:
        return None
    finally:
        if r is not None:
            await r.aclose()
