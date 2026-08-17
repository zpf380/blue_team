"""初始化数据库表结构（开发用：Base.metadata.create_all 幂等）。

生产/后续阶段使用 alembic 做增量迁移。
用法：python -m scripts.init_db
"""
import asyncio

from app import models  # noqa: F401  确保全部模型注册
from app.db.base import Base
from app.db.session import engine


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[init_db] 表结构创建完成。")


if __name__ == "__main__":
    asyncio.run(main())
