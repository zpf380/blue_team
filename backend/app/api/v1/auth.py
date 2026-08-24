"""认证接口：登录（图形验证码 + MFA 两段式）/ 刷新 / 登出 / 会话管理。

安全设计：
- 验证码：用户名或来源 IP 连续失败达到 CAPTCHA_THRESHOLD 后强制图形验证码，
  防暴力破解与用户名枚举；一次性使用 + Redis 存储。
- MFA：角色命中 MFA_FORCE_ROLES（默认 admin）未绑定 TOTP 时强制绑定后才能登录；
  已绑定用户登录后必须通过 6 位 TOTP 二次验证。
- 会话：access/refresh 令牌同时写入 HttpOnly Cookie（SameSite=Lax + Secure），
  前端 JS 无法读取；cookie 认证的写操作需 X-Requested-With 头（CSRF 双重防护）。
- 会话管理：GET /auth/sessions 列出登录会话，可单点吊销。
"""
import base64
import datetime as dt
import hashlib
import random

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_client_ip, get_current_user, get_user_agent
from app.core.exceptions import AppError, ERR_CONFLICT, ERR_FORBIDDEN, ERR_UNAUTHORIZED, ERR_VALIDATION, ok_response
from app.core.security import (
    create_access_token,
    create_mfa_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models import RefreshToken, Role, User
from app.schemas.user import (
    ChangePasswordIn,
    LoginIn,
    LoginResult,
    MfaCodeIn,
    MfaCodeOnlyIn,
    MfaTokenIn,
    RefreshIn,
    UserOut,
)
from app.services import mfa as mfa_service
from app.services.audit_log import record
from app.services.cache import redis_del, redis_get, redis_incr, redis_set

router = APIRouter(prefix="/auth", tags=["认证"])

# 图形验证码字符集（去除 0/O/1/I/l 等易混淆字符）
_CAPTCHA_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _is_secure(request: Request) -> bool:
    """是否 HTTPS：跟随反向代理的 X-Forwarded-Proto。"""
    return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"


def _gen_captcha_svg(code: str) -> str:
    """生成带干扰线的 SVG 验证码（纯 Python，无 PIL 依赖）。"""
    width, height = 130, 42
    bits: list[str] = []
    for _ in range(3):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        bits.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="rgba({random.randint(90, 200)},{random.randint(90, 200)},{random.randint(90, 200)},.45)" '
            f'stroke-width="1"/>'
        )
    text_x = 12
    for ch in code:
        bits.append(
            f'<text x="{text_x}" y="{random.randint(27, 34)}" font-size="{random.randint(20, 26)}" '
            f'fill="rgb({random.randint(20, 140)},{random.randint(20, 140)},{random.randint(20, 140)})" '
            f'font-family="Arial,monospace" font-weight="bold" '
            f'transform="rotate({random.randint(-18, 18)} {text_x} 30)">{ch}</text>'
        )
        text_x += 28
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="100%" height="100%" fill="rgb(244,246,248)"/>'
        + "".join(bits)
        + "</svg>"
    )
    return svg


@router.get("/captcha")
async def captcha():
    code = "".join(random.choices(_CAPTCHA_CHARS, k=4))
    captcha_id = hashlib.sha256(
        f"{dt.datetime.now(dt.timezone.utc).timestamp()}:{random.random()}".encode()
    ).hexdigest()[:24]
    await redis_set(f"captcha:{captcha_id}", code, settings.CAPTCHA_TTL_SECONDS)
    b64 = base64.b64encode(_gen_captcha_svg(code).encode("utf-8")).decode("ascii")
    return ok_response(data={"captcha_id": captcha_id, "image": f"data:image/svg+xml;base64,{b64}"})


async def _verify_captcha(data: LoginIn, user: User | None, ip: str | None) -> None:
    """用户名或 IP 失败次数达阈值时必须通过图形验证码（一次性）。"""
    ip_fails = int(await redis_get(f"login_fail:{ip}") or 0)
    user_fails = user.failed_attempts if user else 0
    if user_fails < settings.CAPTCHA_THRESHOLD and ip_fails < settings.CAPTCHA_THRESHOLD:
        return
    if not data.captcha_id or not data.captcha_code:
        raise AppError(code=ERR_VALIDATION, message="请填写图形验证码")
    expect = await redis_get(f"captcha:{data.captcha_id}")
    if expect is None:
        raise AppError(code=ERR_VALIDATION, message="验证码已过期，请刷新")
    await redis_del(f"captcha:{data.captcha_id}")  # 一次性使用，防重放
    if expect.upper() != data.captcha_code.strip().upper():
        raise AppError(code=ERR_VALIDATION, message="验证码错误")


def build_user_out(user: User, role: Role | None) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        phone=user.phone,
        real_name=user.real_name,
        employee_no=user.employee_no,
        department_id=user.department_id,
        department_name=user.department.name if user.department else None,
        role_id=user.role_id,
        role=role.code if role else None,
        role_name=role.name if role else None,
        position=user.position,
        security_level=user.security_level,
        status=user.status,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        permissions=role.permissions if role else [],
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _set_auth_cookies(response: Response, access: str, refresh: str, secure: bool) -> None:
    response.set_cookie(
        "access_token", access,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True, samesite="lax", secure=secure, path="/",
    )
    response.set_cookie(
        "refresh_token", refresh,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        httponly=True, samesite="lax", secure=secure, path="/",
    )


def _clear_auth_cookies(response: Response, secure: bool) -> None:
    response.delete_cookie("access_token", path="/", httponly=True, samesite="lax", secure=secure)
    response.delete_cookie("refresh_token", path="/", httponly=True, samesite="lax", secure=secure)


async def _issue_tokens(
    session: AsyncSession, user: User, role: Role | None, response: Response, request: Request
) -> tuple[str, str]:
    """签发 access/refresh 令牌：写入 HttpOnly Cookie + 记录 refresh 会话。"""
    role_code = role.code if role else ""
    perms = role.permissions if role else []
    access = create_access_token(user.id, role_code, perms)
    refresh = create_refresh_token(user.id)
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_token_hash(refresh),
            expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            ip_address=await get_client_ip(request),
            user_agent=await get_user_agent(request),
        )
    )
    _set_auth_cookies(response, access, refresh, _is_secure(request))
    return access, refresh


async def _resolve_mfa_user(data: MfaTokenIn, session: AsyncSession) -> User:
    payload = decode_token(data.mfa_token)
    if not payload or payload.get("type") != "mfa_pending":
        raise AppError(code=ERR_UNAUTHORIZED, message="MFA 凭证无效或已过期，请重新登录")
    user = await session.get(User, int(payload["sub"]))
    if not user or user.status in ("disabled", "archived"):
        raise AppError(code=ERR_UNAUTHORIZED, message="用户不可用")
    return user


@router.post("/login")
async def login(data: LoginIn, request: Request, response: Response, session: AsyncSession = Depends(get_db)):
    user = (await session.execute(select(User).where(User.username == data.username))).scalar_one_or_none()
    now = dt.datetime.now(dt.timezone.utc)
    ip = await get_client_ip(request)

    # 统一提示，防用户名枚举；不存在/禁用账号同样计入来源 IP 失败（撞验证码墙）
    if not user or user.status in ("disabled", "archived"):
        await redis_incr(f"login_fail:{ip}", settings.LOGIN_LOCK_MINUTES * 60)
        raise AppError(code=ERR_UNAUTHORIZED, message="用户名或密码错误")
    if user.locked_until and user.locked_until > now:
        raise AppError(code=ERR_UNAUTHORIZED, message="账号已锁定，请稍后再试")

    await _verify_captcha(data, user, ip)

    if not verify_password(data.password, user.password_hash):
        user.failed_attempts += 1
        await redis_incr(f"login_fail:{ip}", settings.LOGIN_LOCK_MINUTES * 60)
        if user.failed_attempts >= settings.LOGIN_MAX_FAILURES:
            user.locked_until = now + dt.timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
            user.failed_attempts = 0
            # 锁定事件审计：暴力破解可追溯（由本次 commit 一并落库）
            user._role = await session.get(Role, user.role_id) if user.role_id else None
            await record(
                session, user, "auth:lock",
                detail={"failed_attempts": settings.LOGIN_MAX_FAILURES, "lock_minutes": settings.LOGIN_LOCK_MINUTES},
                ip_address=ip, user_agent=await get_user_agent(request),
            )
        await session.commit()
        raise AppError(code=ERR_UNAUTHORIZED, message="用户名或密码错误")

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    await redis_del(f"login_fail:{ip}")

    role = await session.get(Role, user.role_id) if user.role_id else None
    user._role = role  # 供审计记录写入角色
    await record(session, user, "auth:login", detail={"method": "password"}, ip_address=ip, user_agent=await get_user_agent(request))

    role_code = role.code if role else ""
    needs_mfa = user.totp_enabled or role_code in settings.MFA_FORCE_ROLES
    if needs_mfa:
        await session.commit()
        # 两段式登录：先给短期 mfa 凭证，不签发会话令牌
        return ok_response(
            data=LoginResult(
                user=build_user_out(user, role),
                mfa_required=True,
                mfa_setup=not user.totp_enabled,
                mfa_token=create_mfa_token(user.id),
            )
        )

    access, refresh = await _issue_tokens(session, user, role, response, request)
    await session.commit()
    return ok_response(
        data=LoginResult(access_token=access, refresh_token=refresh, user=build_user_out(user, role))
    )


@router.post("/mfa/setup")
async def mfa_setup(data: MfaTokenIn, request: Request, session: AsyncSession = Depends(get_db)):
    """生成并绑定 TOTP 密钥（返回 otpauth URI 供二维码展示），绑定前可重复调用。"""
    user = await _resolve_mfa_user(data, session)
    if user.totp_enabled:
        raise AppError(code=ERR_CONFLICT, message="已启用 MFA，无需重复绑定")
    secret = user.totp_secret or mfa_service.generate_secret()
    user.totp_secret = secret
    user._role = await session.get(Role, user.role_id) if user.role_id else None
    await record(session, user, "auth:mfa_setup", ip_address=await get_client_ip(request), user_agent=await get_user_agent(request))
    await session.commit()
    return ok_response(data={"secret": secret, "otpauth_url": mfa_service.otpauth_uri(secret, user.username)})


@router.post("/mfa/confirm")
async def mfa_confirm(data: MfaCodeIn, request: Request, response: Response, session: AsyncSession = Depends(get_db)):
    """绑定确认：验证码正确后启用 MFA 并签发会话。"""
    user = await _resolve_mfa_user(data, session)
    if user.totp_enabled:
        raise AppError(code=ERR_CONFLICT, message="已启用 MFA，无需重复绑定")
    if not user.totp_secret or not mfa_service.verify_code(user.totp_secret, data.code):
        raise AppError(code=ERR_UNAUTHORIZED, message="验证码不正确")
    user.totp_enabled = True
    user.totp_confirmed_at = dt.datetime.now(dt.timezone.utc)
    role = await session.get(Role, user.role_id) if user.role_id else None
    user._role = role
    await record(session, user, "auth:mfa_confirm", ip_address=await get_client_ip(request), user_agent=await get_user_agent(request))
    access, refresh = await _issue_tokens(session, user, role, response, request)
    await session.commit()
    return ok_response(
        data=LoginResult(access_token=access, refresh_token=refresh, user=build_user_out(user, role))
    )


@router.post("/mfa/verify")
async def mfa_verify(data: MfaCodeIn, request: Request, response: Response, session: AsyncSession = Depends(get_db)):
    """已启用 MFA 用户的二次验证，成功后签发会话。"""
    user = await _resolve_mfa_user(data, session)
    if not user.totp_enabled:
        raise AppError(code=ERR_CONFLICT, message="该账号未启用 MFA")
    if not mfa_service.verify_code(user.totp_secret or "", data.code):
        raise AppError(code=ERR_UNAUTHORIZED, message="验证码不正确")
    role = await session.get(Role, user.role_id) if user.role_id else None
    user._role = role
    await record(session, user, "auth:mfa_verify", ip_address=await get_client_ip(request), user_agent=await get_user_agent(request))
    access, refresh = await _issue_tokens(session, user, role, response, request)
    await session.commit()
    return ok_response(
        data=LoginResult(access_token=access, refresh_token=refresh, user=build_user_out(user, role))
    )


@router.post("/mfa/bind")
async def mfa_bind(
    request: Request,
    session: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """已登录用户自助绑定 MFA（生成密钥 + otpauth URI，绑定前可重复调用）。"""
    if current.totp_enabled:
        raise AppError(code=ERR_CONFLICT, message="已启用 MFA，无需重复绑定")
    secret = current.totp_secret or mfa_service.generate_secret()
    current.totp_secret = secret
    await record(session, current, "auth:mfa_bind", ip_address=await get_client_ip(request), user_agent=await get_user_agent(request))
    await session.commit()
    return ok_response(data={"secret": secret, "otpauth_url": mfa_service.otpauth_uri(secret, current.username)})


@router.post("/mfa/bind-confirm")
async def mfa_bind_confirm(
    data: MfaCodeOnlyIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if current.totp_enabled:
        raise AppError(code=ERR_CONFLICT, message="已启用 MFA")
    if not current.totp_secret or not mfa_service.verify_code(current.totp_secret, data.code):
        raise AppError(code=ERR_UNAUTHORIZED, message="验证码不正确")
    current.totp_enabled = True
    current.totp_confirmed_at = dt.datetime.now(dt.timezone.utc)
    await record(session, current, "auth:mfa_bind_confirm", ip_address=await get_client_ip(request), user_agent=await get_user_agent(request))
    await session.commit()
    return ok_response(message="MFA 已启用")


@router.post("/mfa/disable")
async def mfa_disable(
    data: MfaCodeOnlyIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """解绑 MFA：强制角色（admin）不可解绑，需提交当前 TOTP 验证码。"""
    if not current.totp_enabled:
        raise AppError(code=ERR_CONFLICT, message="尚未启用 MFA")
    role_code = current._role.code if current._role else ""
    if role_code in settings.MFA_FORCE_ROLES:
        raise AppError(code=ERR_CONFLICT, message="该角色强制启用 MFA，不可解绑")
    if not mfa_service.verify_code(current.totp_secret or "", data.code):
        raise AppError(code=ERR_UNAUTHORIZED, message="验证码不正确")
    current.totp_enabled = False
    current.totp_secret = None
    current.totp_confirmed_at = None
    await record(session, current, "auth:mfa_disable", ip_address=await get_client_ip(request), user_agent=await get_user_agent(request))
    await session.commit()
    return ok_response(message="MFA 已解绑")


def _require_xhr(request: Request) -> None:
    """Cookie 认证的写端点做 CSRF 双重校验：必须携带 X-Requested-With（浏览器跨站表单无法伪造）。"""
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        raise AppError(code=ERR_FORBIDDEN, message="非法请求来源")


@router.post("/refresh")
async def refresh(data: RefreshIn, request: Request, response: Response, session: AsyncSession = Depends(get_db)):
    _require_xhr(request)
    token = data.refresh_token or request.cookies.get("refresh_token", "")
    if not token:
        raise AppError(code=ERR_UNAUTHORIZED, message="刷新令牌缺失")
    payload = decode_token(token)
    if not payload or payload.get("type") != "refresh":
        raise AppError(code=ERR_UNAUTHORIZED, message="刷新令牌无效")

    row = (
        await session.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == _token_hash(token),
                RefreshToken.revoked.is_(False),
            )
        )
    ).scalar_one_or_none()
    now = dt.datetime.now(dt.timezone.utc)
    if not row or row.expires_at < now:
        raise AppError(code=ERR_UNAUTHORIZED, message="刷新令牌已失效")

    user = await session.get(User, int(payload["sub"]))
    if not user or user.status in ("disabled", "archived"):
        raise AppError(code=ERR_UNAUTHORIZED, message="用户不可用")

    # 轮换：旧令牌作废，签发新对
    row.revoked = True
    role = await session.get(Role, user.role_id) if user.role_id else None
    access, refresh = await _issue_tokens(session, user, role, response, request)
    await session.commit()
    return ok_response(data={"access_token": access, "refresh_token": refresh})


@router.post("/logout")
async def logout(data: RefreshIn, request: Request, response: Response, session: AsyncSession = Depends(get_db)):
    _require_xhr(request)
    token = data.refresh_token or request.cookies.get("refresh_token", "")
    if token:
        row = (
            await session.execute(
                select(RefreshToken).where(RefreshToken.token_hash == _token_hash(token))
            )
        ).scalar_one_or_none()
        if row:
            row.revoked = True
            await session.commit()
    _clear_auth_cookies(response, _is_secure(request))
    return ok_response()


@router.post("/change-password")
async def change_password(
    data: ChangePasswordIn,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if not verify_password(data.old_password, current.password_hash):
        raise AppError(code=ERR_UNAUTHORIZED, message="原密码不正确")
    if data.old_password == data.new_password:
        raise AppError(code=ERR_CONFLICT, message="新密码不能与原密码相同")

    current.password_hash = hash_password(data.new_password)
    # 吊销该用户全部刷新令牌，使其他会话失效，需重新登录
    await session.execute(update(RefreshToken).where(RefreshToken.user_id == current.id).values(revoked=True))
    await record(
        session, current, "auth:change_password", target_type="user", target_id=str(current.id),
        ip_address=await get_client_ip(request), user_agent=await get_user_agent(request),
    )
    await session.commit()
    return ok_response(message="密码已修改，请重新登录")


@router.get("/sessions")
async def list_sessions(
    request: Request,
    session: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """列出当前用户的未过期登录会话。"""
    now = dt.datetime.now(dt.timezone.utc)
    rows = (
        await session.execute(
            select(RefreshToken)
            .where(RefreshToken.user_id == current.id, RefreshToken.expires_at > now)
            .order_by(RefreshToken.created_at.desc())
        )
    ).scalars().all()
    current_refresh = request.cookies.get("refresh_token", "")
    current_hash = _token_hash(current_refresh) if current_refresh else None
    return ok_response(data={
        "items": [
            {
                "id": r.id,
                "created_at": r.created_at,
                "expires_at": r.expires_at,
                "ip_address": r.ip_address,
                "user_agent": (r.user_agent or "")[:80],
                "revoked": r.revoked,
                "current": r.token_hash == current_hash,
            }
            for r in rows
        ]
    })


@router.post("/sessions/{session_id}/revoke")
async def revoke_session(
    session_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    row = await session.get(RefreshToken, session_id)
    if not row or row.user_id != current.id:
        raise AppError(code=ERR_CONFLICT, message="会话不存在")
    row.revoked = True
    await record(session, current, "auth:session_revoke", detail={"session_id": session_id},
                 ip_address=await get_client_ip(request), user_agent=await get_user_agent(request))
    await session.commit()
    return ok_response(message="会话已吊销")
