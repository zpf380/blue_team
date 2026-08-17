"""数据范围过滤器单元测试（构造查询并断言生成的 SQL 条件）。"""
from sqlalchemy import select

from app.models import Role, User
from app.services.data_scope import apply_data_scope


def _user_with(role_code: str, data_scope: str, user_id: int = 1, dept_id: int | None = 10) -> User:
    u = User(id=user_id, department_id=dept_id)
    u._role = Role(code=role_code, data_scope=data_scope)
    return u


def test_admin_sees_all():
    u = _user_with("admin", "all")
    q = apply_data_scope(select(User), u, User)
    sql = str(q)
    assert "WHERE" not in sql


def test_all_scope_no_filter():
    u = _user_with("auditor", "all")
    q = apply_data_scope(select(User), u, User)
    assert "WHERE" not in str(q)


def test_self_scope_filters_own_user():
    u = _user_with("trainee", "self", user_id=7)
    q = apply_data_scope(select(User), u, User)
    sql = str(q)
    assert "users.id" in sql
    assert "= :id_1" in sql


def test_dept_scope_filters_department():
    u = _user_with("analyst", "dept", dept_id=10)
    q = apply_data_scope(select(User), u, User)
    sql = str(q)
    assert "department_id" in sql


def test_self_scope_uses_owner_for_device():
    from app.models import Device

    u = _user_with("trainee", "self", user_id=3)
    q = apply_data_scope(select(Device), u, Device)
    sql = str(q)
    assert "owner_id" in sql
