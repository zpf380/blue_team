"""角色列表接口：供用户表单下拉选择。"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.exceptions import ok_response
from app.db.session import get_db
from app.models import Role, User
from app.schemas.user import RoleOut

router = APIRouter(prefix="/roles", tags=["角色"])


@router.get("")
async def list_roles(session: AsyncSession = Depends(get_db), _: User = Depends(get_current_user)):
    rows = (await session.execute(select(Role).order_by(Role.id))).scalars().all()
    return ok_response(data=[RoleOut.model_validate(r) for r in rows])
