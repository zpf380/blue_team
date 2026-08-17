"""密码哈希（bcrypt）与 JWT 签发/校验。"""
import datetime as dt

import bcrypt
import jwt

from app.core.config import settings


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, role_code: str, permissions: list[str]) -> str:
    payload = {
        "sub": str(user_id),
        "role": role_code,
        "permissions": permissions,
        "type": "access",
        "exp": dt.datetime.now(dt.timezone.utc)
        + dt.timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "jti": bcrypt.gensalt().decode()[:16],
        "exp": dt.datetime.now(dt.timezone.utc)
        + dt.timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_mfa_token(user_id: int, minutes: int | None = None) -> str:
    """MFA 两段式登录的短期凭证（type=mfa_pending），用于 setup/verify/confirm 鉴权。"""
    payload = {
        "sub": str(user_id),
        "type": "mfa_pending",
        "exp": dt.datetime.now(dt.timezone.utc)
        + dt.timedelta(minutes=minutes or settings.MFA_PENDING_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
