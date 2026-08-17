"""创建/重置管理员账号（幂等）。

用法：ADMIN_PASSWORD=xxx python -m scripts.create_admin
"""
import asyncio
import os

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models import Role, User


async def main() -> None:
    password = os.environ.get("ADMIN_PASSWORD", "admin123")
    async with AsyncSessionLocal() as session:
        admin = (await session.execute(select(User).where(User.username == "admin"))).scalar_one_or_none()
        role = (await session.execute(select(Role).where(Role.code == "admin"))).scalar_one_or_none()
        if not role:
            print("[create_admin] 请先运行 scripts.seed_data 创建角色。")
            return
        if admin:
            admin.password_hash = hash_password(password)
            print(f"[create_admin] 已重置 admin 密码。")
        else:
            session.add(User(username="admin", real_name="系统管理员", password_hash=hash_password(password), role_id=role.id, status="active"))
            print(f"[create_admin] 已创建 admin / {password}")
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
