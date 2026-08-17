"""MFA（TOTP）服务：密钥生成 / otpauth URI / 验证码校验（pyotp）。"""
import pyotp

from app.core.config import settings


def generate_secret() -> str:
    return pyotp.random_base32()


def otpauth_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=settings.MFA_ISSUER)


def verify_code(secret: str, code: str) -> bool:
    """校验 TOTP 验证码；允许前后各 1 步时间窗口（容忍时钟偏差）。"""
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)
    except Exception:
        return False
