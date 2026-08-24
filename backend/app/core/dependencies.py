"""FastAPI 依赖：当前用户、权限、角色白名单、审计员写拦截。"""
from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ERR_FORBIDDEN_PERM, ERR_UNAUTHORIZED
from app.core.security import decode_token
from app.db.session import get_db
from app.models import Role, User


def _has_permission(permissions: list[str], required: str) -> bool:
    if not required:
        return True
    if "*" in permissions:
        return True
    for p in permissions:
        if p == required:
            return True
        if p.endswith("*") and required.startswith(p[:-1]):
            return True
    return False


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> User:
    """解析当前用户：优先 Bearer 头（API/测试），否则 HttpOnly Cookie（浏览器）。

    CSRF 防护：通过 Cookie 认证的写操作（POST/PUT/DELETE）必须携带
    X-Requested-With: XMLHttpRequest 头（前端 axios 全局附加）；SameSite=Lax
    已阻止跨站携带 Cookie，此头作双重保险。
    """
    token: str | None = None
    auth_source = "header"
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    else:
        cookie_token = request.cookies.get("access_token")
        if cookie_token:
            token = cookie_token
            auth_source = "cookie"
    if not token:
        raise AppError(code=ERR_UNAUTHORIZED, message="未认证")

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise AppError(code=ERR_UNAUTHORIZED, message="认证失败或令牌已过期")

    if auth_source == "cookie" and request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get("x-requested-with") != "XMLHttpRequest":
            raise AppError(code=ERR_FORBIDDEN_PERM, message="缺少 CSRF 防护头，请刷新页面重试")

    user = await session.get(User, int(payload["sub"]))
    if not user or user.status in ("disabled", "archived"):
        raise AppError(code=ERR_UNAUTHORIZED, message="用户不存在或已禁用")
    user._role = await session.get(Role, user.role_id) if user.role_id else None
    return user


def require_permission(permission: str):
    async def _dep(user: User = Depends(get_current_user)) -> User:
        perms = user._role.permissions if user._role else []
        if not _has_permission(perms, permission):
            raise AppError(code=ERR_FORBIDDEN_PERM, message=f"缺少权限: {permission}")
        return user

    return _dep


def require_role(roles: list[str]):
    async def _dep(user: User = Depends(get_current_user)) -> User:
        role_code = user._role.code if user._role else ""
        if role_code not in roles:
            raise AppError(code=ERR_FORBIDDEN_PERM, message="该操作仅限指定角色")
        return user

    return _dep


async def get_client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


async def get_user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")
