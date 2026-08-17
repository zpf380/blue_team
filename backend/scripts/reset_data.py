"""重置演示/测试数据：仅保留 admin 账号与基础配置（角色权限/部门/频道/设备/子网/训练场景/智能体/徽章）。

删除：除 admin 外的所有用户、聊天消息/成员/私聊频道、文件记录、AI 会话、
操作日志（TRUNCATE 绕过防删 RULE）、扫描报告、审计报告、训练进度/会话/积分/徽章记录。
保留：admin（角色 admin，permissions=[ALL]，可创建用户并分配角色）；
预置频道/设备/子网/告警/训练场景等基础配置，仅解除对将被删除用户的引用（如设备 owner_id 置空）。

用法：python -m scripts.reset_data
"""
import asyncio

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models import (
    AIConversation,
    Alert,
    AuditReport,
    Channel,
    ChannelMember,
    Device,
    FileRecord,
    IPAllocation,
    Message,
    OperationLog,
    RefreshToken,
    SandboxSession,
    ScanReport,
    ScoreRecord,
    TrainingProgress,
    User,
    UserBadge,
)


async def _reset(session: AsyncSession) -> None:
    # 1) 聊天运行数据：消息 → 成员 → AI 会话 → 文件 → 私聊频道（预置 public/trainee 频道保留）
    await session.execute(delete(Message))
    await session.execute(delete(ChannelMember))
    await session.execute(delete(AIConversation))
    await session.execute(delete(FileRecord))
    await session.execute(delete(Channel).where(Channel.type == "private"))

    # 2) 其余运行数据
    await session.execute(delete(ScanReport))
    await session.execute(delete(AuditReport))
    await session.execute(delete(TrainingProgress))
    await session.execute(delete(SandboxSession))
    await session.execute(delete(ScoreRecord))
    await session.execute(delete(UserBadge))

    # 3) 操作日志为只追加（RULE 禁止 DELETE/UPDATE），用 TRUNCATE 绕过
    await session.execute(text("TRUNCATE TABLE operation_logs"))

    # 4) 刷新令牌（引用 user），删除用户前清空
    await session.execute(delete(RefreshToken))

    # 5) 保留基础配置对象，仅解除对将被删除用户的引用
    await session.execute(update(Device).values(owner_id=None))
    await session.execute(update(IPAllocation).values(allocated_to=None))
    await session.execute(update(Alert).values(acknowledged_by=None))

    # 6) 删除除 admin 外的所有用户
    result = await session.execute(delete(User).where(User.username != "admin"))
    await session.commit()

    remaining = (await session.execute(select(User))).scalars().all()
    print(f"[reset] 删除用户 {result.rowcount} 个；剩余用户：{[u.username for u in remaining]}")
    for u in remaining:
        if u.role:
            print(f"[reset] {u.username} 角色：{u.role.code}，权限数：{len(u.role.permissions)}")
    channels = (await session.execute(select(Channel))).scalars().all()
    print(f"[reset] 保留频道：{[(c.name, c.type) for c in channels]}")
    print("[reset] 完成")


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await _reset(session)


if __name__ == "__main__":
    asyncio.run(main())
