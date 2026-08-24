"""认证与用户相关 Schema。"""
import datetime as dt
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

# ---------- 认证 ----------
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)
    # 自适应验证码：失败达到阈值后必填
    captcha_id: Optional[str] = None
    captcha_code: Optional[str] = None


class RefreshIn(BaseModel):
    refresh_token: str = Field(default="")


class MfaTokenIn(BaseModel):
    """携带 MFA 两段式登录凭证。"""
    mfa_token: str = Field(min_length=1)


class MfaCodeIn(BaseModel):
    mfa_token: str = Field(min_length=1)
    code: str = Field(min_length=1, max_length=16)


class MfaCodeOnlyIn(BaseModel):
    """已登录用户绑定/解绑 MFA 时提交的验证码。"""
    code: str = Field(min_length=1, max_length=16)


class UserOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    username: str
    email: Optional[str] = None
    phone: Optional[str] = None
    real_name: Optional[str] = None
    employee_no: Optional[str] = None
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    role_id: Optional[int] = None
    role: Optional[str] = None
    role_name: Optional[str] = None
    position: Optional[str] = None
    security_level: int = 1
    status: str = "active"
    created_at: Optional[dt.datetime] = None
    last_login_at: Optional[dt.datetime] = None
    # 角色权限点列表（登录 / /users/me 返回，供前端守卫与按钮级 v-permission 判断）
    permissions: list[str] = []


class LoginResult(BaseModel):
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    user: UserOut
    # MFA 两段式登录：mfa_required=True 时需继续走 /auth/mfa/{setup,confirm,verify}
    mfa_required: bool = False
    mfa_setup: bool = False
    mfa_token: Optional[str] = None


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=6, max_length=128)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    real_name: Optional[str] = None
    employee_no: Optional[str] = None
    department_id: Optional[int] = None
    role_id: Optional[int] = None
    position: Optional[str] = None
    security_level: int = 1
    status: str = "active"


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    real_name: Optional[str] = None
    employee_no: Optional[str] = None
    department_id: Optional[int] = None
    role_id: Optional[int] = None
    position: Optional[str] = None
    security_level: Optional[int] = None
    status: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)


class RoleOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    code: str
    name: str
    description: Optional[str] = None
    data_scope: Optional[str] = "all"


class ChangePasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    parent_id: Optional[int] = None
    manager_id: Optional[int] = None
    description: Optional[str] = None


class DepartmentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    parent_id: Optional[int] = None      # 显式传 null = 移到根
    manager_id: Optional[int] = None
    description: Optional[str] = None


class DepartmentOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    parent_id: Optional[int] = None
    manager_id: Optional[int] = None
    description: Optional[str] = None


class DepartmentTreeNode(DepartmentOut):
    children: list["DepartmentTreeNode"] = []
