"""操作审计写入（who/when/what/where，只追加）。"""
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OperationLog, User


async def record(
    session: AsyncSession,
    user: User,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> OperationLog:
    role_code = user._role.code if getattr(user, "_role", None) else None
    log = OperationLog(
        user_id=user.id,
        username=user.username,
        role_code=role_code,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(log)
    await session.flush()
    return log
