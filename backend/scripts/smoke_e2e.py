"""全栈端到端冒烟测试：覆盖认证/用户/角色/部门/聊天/AI/训练/监控/审计/考勤/文件/统计。

用法（需后端已启动）：
    .venv\\Scripts\\python scripts/smoke_e2e.py
退出码：0=全部通过，1=有失败。
"""
import asyncio
import datetime as dt
import os
import sys
import uuid

import httpx
import pyotp

# 直接以 `python scripts/smoke_e2e.py` 运行时，保证能 import app.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "http://localhost:8000/api/v1"
PASS: list[str] = []
FAIL: list[str] = []


async def api(c: httpx.AsyncClient, method: str, path: str, token: str | None = None,
              timeout: float = 30, **kw) -> tuple[int, dict]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = await c.request(method, path, headers=headers, timeout=timeout, **kw)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:300]}


def is_ok(j: dict) -> bool:
    return j.get("code") == 0


def uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def login(c: httpx.AsyncClient, username: str, password: str) -> str:
    code, j = await api(c, "POST", "/auth/login", json={"username": username, "password": password})
    assert is_ok(j), f"登录失败 {username}: {j}"
    return j["data"]["access_token"]


async def _admin_totp_secret() -> str | None:
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models import User

    async with AsyncSessionLocal() as s:
        return (await s.execute(select(User.totp_secret).where(User.username == "admin"))).scalar_one_or_none()


async def _clear_leave_artifacts(username: str) -> None:
    """清理历史冒烟运行遗留的请假申请（API 不能删除已审批的，直接清库，保证时段不重叠）。"""
    from sqlalchemy import delete, select

    from app.db.session import AsyncSessionLocal
    from app.models import LeaveRequest, User

    async with AsyncSessionLocal() as s:
        uid = (await s.execute(select(User.id).where(User.username == username))).scalar_one_or_none()
        if uid:
            await s.execute(delete(LeaveRequest).where(LeaveRequest.user_id == uid))
            await s.commit()


async def login_admin(c: httpx.AsyncClient) -> str:
    """admin 登录：管理员强制 MFA，需走 TOTP 两段式（首次绑定 setup→confirm，此后 verify）。"""
    code, j = await api(c, "POST", "/auth/login", json={"username": "admin", "password": "admin123"})
    assert is_ok(j) and j["data"].get("mfa_required"), f"admin 登录应进入 MFA: {j}"
    mfa_token = j["data"]["mfa_token"]

    def _totp(secret: str) -> str:
        return pyotp.TOTP(secret).now()

    if j["data"].get("mfa_setup"):
        code, j = await api(c, "POST", "/auth/mfa/setup", json={"mfa_token": mfa_token})
        assert is_ok(j), j
        secret = j["data"]["secret"]
        for _ in range(3):
            code, j = await api(c, "POST", "/auth/mfa/confirm",
                                json={"mfa_token": mfa_token, "code": _totp(secret)})
            if is_ok(j):
                break
            await asyncio.sleep(1)
        assert is_ok(j), j
    else:
        secret = await _admin_totp_secret()
        assert secret, "admin 已启用 MFA 但库中无密钥"
        for _ in range(3):
            code, j = await api(c, "POST", "/auth/mfa/verify",
                                json={"mfa_token": mfa_token, "code": _totp(secret)})
            if is_ok(j):
                break
            await asyncio.sleep(1)
        assert is_ok(j), j
    return j["data"]["access_token"]


def _clip(msg: str, limit: int = 300) -> str:
    return msg if len(msg) <= limit else f"{msg[:limit]} …(截断, 共 {len(msg)} 字符)"


async def check(c: httpx.AsyncClient, name: str, fn):
    try:
        await fn()
        PASS.append(name)
    except AssertionError as e:
        FAIL.append(f"{name} — {_clip(str(e))}")
    except Exception as e:
        FAIL.append(f"{name} — 异常 {type(e).__name__}: {_clip(str(e))}")


async def main():
    async with httpx.AsyncClient(base_url=BASE) as c:
        # ---------- 认证 ----------
        mgr = await login(c, "manager01", "Bt@123456")
        ana = await login(c, "analyst01", "Bt@123456")
        trn = await login(c, "trainee01", "Bt@123456")
        adm = await login_admin(c)
        aud = await login(c, "auditor01", "Bt@123456")
        _, me_ana = await api(c, "GET", "/users/me", token=ana)
        ana_id = me_ana["data"]["id"]
        _, me_mgr = await api(c, "GET", "/users/me", token=mgr)
        mgr_id = me_mgr["data"]["id"]

        async def auth_section():
            code, j = await api(c, "GET", "/auth/captcha")
            assert is_ok(j) and j["data"].get("captcha_id") and j["data"].get("image"), j
            code, j = await api(c, "GET", "/users/me", token=mgr)
            assert is_ok(j) and j["data"]["username"] == "manager01" and j["data"]["role"] == "manager", j
            code, j = await api(c, "GET", "/auth/sessions", token=mgr)
            assert is_ok(j) and isinstance(j["data"].get("items"), list), j
            code, j = await api(c, "POST", "/auth/refresh", token=mgr, json={"refresh_token": ""})
            assert not is_ok(j), "空 refresh_token 应被拒绝"
            code, j = await api(c, "POST", "/auth/change-password", token=mgr,
                                json={"old_password": "wrong", "new_password": "Bt@123456"})
            assert not is_ok(j), "错误旧密码应被拒绝"
        await check(c, "认证: captcha/me/sessions/refresh/改密", auth_section)

        # ---------- 用户 / 角色 / 部门 ----------
        tmp_user_id, tmp_dept_id = None, None
        async def user_section():
            nonlocal tmp_user_id, tmp_dept_id
            # 列表/角色/部门树：manager 可读
            code, j = await api(c, "GET", "/users", token=mgr, params={"size": 10})
            assert is_ok(j) and isinstance(j["data"].get("items"), list), j
            code, j = await api(c, "GET", "/roles", token=mgr)
            assert is_ok(j) and len(j["data"]) >= 5, j
            code, j = await api(c, "GET", "/departments/tree", token=mgr)
            assert is_ok(j), j
            # 新增/改/导出：仅 admin（manager 仅可列表/导出）
            code, j = await api(c, "POST", "/departments", token=adm,
                                json={"name": uniq("e2e-dept"), "parent_id": None})
            assert is_ok(j), j
            tmp_dept_id = j["data"]["id"]
            code, j = await api(c, "POST", "/users", token=adm, json={
                "username": uniq("e2euser"), "password": "Test@123456",
                "real_name": "E2E用户", "department_id": tmp_dept_id, "role_id": 4, "status": "active"})
            assert is_ok(j), j
            tmp_user_id = j["data"]["id"]
            code, j = await api(c, "PUT", f"/users/{tmp_user_id}", token=adm, json={"position": "测试岗"})
            assert is_ok(j), j
            code, j = await api(c, "GET", "/users/export", token=mgr)
            assert code == 200, j
            # 越权：manager 不能建用户
            code, j = await api(c, "POST", "/users", token=mgr, json={
                "username": uniq("noperm"), "password": "Test@123456", "real_name": "越权", "role_id": 4})
            assert not is_ok(j), "manager 建用户应被拒绝"
        await check(c, "用户/角色/部门: 列表+增改+导出+越权", user_section)
        if tmp_user_id:
            await api(c, "DELETE", f"/users/{tmp_user_id}", token=adm, params={"reason": "e2e清理"})
        if tmp_dept_id:
            await api(c, "DELETE", f"/departments/{tmp_dept_id}", token=adm, params={"reason": "e2e清理"})

        async def ensure_contact(me_token: str, me_id: int, other_token: str, other_id: int):
            """幂等建立 me↔other 互为联系人（已建联/有待处理请求则跳过新建）。"""
            code, j = await api(c, "GET", "/chat/contacts", token=me_token)
            assert is_ok(j), j
            if any(cc["id"] == other_id for cc in j["data"]):
                return
            code, j = await api(c, "GET", "/chat/contacts/requests", token=other_token)
            assert is_ok(j), j
            pending = next((r for r in j["data"] if r["requester_id"] == me_id), None)
            if not pending:
                code, j = await api(c, "POST", "/chat/contacts/requests", token=me_token,
                                    json={"target_id": other_id})
                assert is_ok(j), j
                req_id = j["data"]["id"]
            else:
                req_id = pending["id"]
            code, j = await api(c, "POST", f"/chat/contacts/requests/{req_id}/accept", token=other_token)
            assert is_ok(j), j

        # ---------- 聊天 ----------
        ch_id, ch_name, msg_id = None, None, None
        async def chat_section():
            nonlocal ch_id, ch_name, msg_id
            ch_name = uniq("e2e-ch")
            code, j = await api(c, "GET", "/channels", token=mgr)
            assert is_ok(j), j
            code, j = await api(c, "POST", "/channels", token=mgr,
                                json={"name": ch_name, "type": "public", "description": "e2e"})
            assert is_ok(j), j
            ch_id = j["data"]["id"]
            code, j = await api(c, "POST", "/channels/join", token=ana, json={"name": ch_name})
            assert is_ok(j), j
            code, j = await api(c, "POST", f"/channels/{ch_id}/messages", token=ana,
                                json={"content": "e2e hello", "message_type": "text"})
            assert is_ok(j), j
            msg_id = j["data"]["id"]
            code, j = await api(c, "GET", f"/channels/{ch_id}/messages", token=mgr, params={"size": 10})
            assert is_ok(j) and any(m["id"] == msg_id for m in j["data"].get("items", [])), j
            code, j = await api(c, "POST", f"/channels/{ch_id}/read", token=mgr, json={})
            assert is_ok(j), j
            code, j = await api(c, "GET", f"/channels/{ch_id}/members", token=mgr)
            assert is_ok(j), j
            # 私聊需互为联系人：先建立 mgr↔ana
            await ensure_contact(mgr, mgr_id, ana, ana_id)
            code, j = await api(c, "POST", "/channels/dm", token=mgr, json={"user_id": ana_id})
            assert is_ok(j), j
            code, j = await api(c, "GET", "/chat/contacts", token=mgr)
            assert is_ok(j), j
            code, j = await api(c, "GET", "/chat/search", token=mgr, params={"q": "e2e hello"})
            assert is_ok(j), j
        await check(c, "聊天: 频道/消息/已读/成员/私聊/搜索", chat_section)
        if msg_id:
            await api(c, "POST", f"/messages/{msg_id}/recall", token=ana, json={})

        # ---------- AI ----------
        async def ai_section():
            code, j = await api(c, "GET", "/ai/conversations", token=mgr)
            assert is_ok(j), j
            code, j = await api(c, "POST", "/ai/invoke", token=mgr,
                                json={"query": "一句话介绍自己", "model_pref": None}, timeout=60)
            assert is_ok(j) and j["data"].get("reply"), j
            conv_id = j["data"]["conversation_id"]
            code, j = await api(c, "GET", f"/ai/conversations/{conv_id}", token=mgr)
            assert is_ok(j), j
            code, j = await api(c, "DELETE", f"/ai/conversations/{conv_id}", token=mgr)
            assert is_ok(j), j
        await check(c, "AI: 会话列表+调用+详情+删除", ai_section)

        # ---------- 训练 ----------
        course_id = None
        async def training_section():
            nonlocal course_id
            # 学员侧：智能体/榜单/统计/徽章/沙箱（manager 角色无 agent:sandbox 权限，用 analyst）
            for ep in ("/training/agents", "/training/ranking", "/training/stats",
                       "/training/badges", "/training/sandbox/sessions"):
                code, j = await api(c, "GET", ep, token=ana)
                assert is_ok(j), f"{ep}: {j}"
            # 管理侧：课程管理仅 manager/admin
            code, j = await api(c, "GET", "/training/manage/courses", token=mgr)
            assert is_ok(j), j
            code, j = await api(c, "POST", "/training/manage/courses", token=mgr,
                                json={"name": uniq("e2e-course"), "difficulty": 2,
                                      "description": "e2e", "order_index": 0})
            assert is_ok(j), j
            course_id = j["data"]["course_id"]
            code, j = await api(c, "POST", f"/training/manage/courses/{course_id}/scenarios", token=mgr,
                                json={"title": "e2e 场景", "scenario_type": "practice",
                                      "content": {"prompt": "e2e"}, "points": 10})
            assert is_ok(j), j
            code, j = await api(c, "POST", f"/training/manage/courses/{course_id}/publish", token=mgr)
            assert is_ok(j), j
        await check(c, "训练: 榜单/徽章/统计/沙箱/课程建发", training_section)
        if course_id:
            await api(c, "DELETE", f"/training/manage/courses/{course_id}", token=mgr)

        # ---------- 监控 ----------
        dev_id, sub_id, alloc_id, auth_id = None, None, None, None
        async def monitor_section():
            nonlocal dev_id, sub_id, alloc_id, auth_id
            for ep in ("/monitor/devices", "/monitor/subnets", "/monitor/allocations",
                       "/monitor/alerts", "/monitor/scan-auth", "/monitor/scans/reports",
                       "/monitor/discover"):
                code, j = await api(c, "GET", ep, token=mgr, params={"size": 10})
                assert is_ok(j), f"{ep}: {j}"
            ip = f"10.233.{int(uuid.uuid4().hex[:4], 16) % 200 + 1}.{int(uuid.uuid4().hex[:5], 16) % 254 + 1}"
            code, j = await api(c, "POST", "/monitor/devices", token=mgr, json={
                "name": uniq("e2e-dev"), "ip_address": ip,
                "device_type": "server", "status": "active"})
            assert is_ok(j), j
            dev_id = j["data"]["id"]
            code, j = await api(c, "PUT", f"/monitor/devices/{dev_id}", token=mgr, json={"location": "e2e"})
            assert is_ok(j), j
            code, j = await api(c, "POST", f"/monitor/devices/{dev_id}/ping", token=mgr)
            assert code in (200, 400), j  # 无 ping/nmap 工具时优雅报错即可
            code, j = await api(c, "GET", "/monitor/devices/export", token=mgr)
            assert code == 200, j
            net = f"10.234.{int(uuid.uuid4().hex[:4], 16) % 200 + 1}.0/24"
            code, j = await api(c, "POST", "/monitor/subnets", token=mgr,
                                json={"name": uniq("e2e-net"), "network": net})
            assert is_ok(j), j
            sub_id = j["data"]["id"]
            code, j = await api(c, "GET", f"/monitor/subnets/{sub_id}/usage", token=mgr)
            assert is_ok(j), j
            code, j = await api(c, "POST", "/monitor/allocations", token=mgr,
                                json={"subnet_id": sub_id, "ip": net.rsplit(".", 1)[0] + ".10",
                                      "allocated_to": ana_id, "purpose": "e2e"})
            assert is_ok(j), j
            alloc_id = j["data"]["id"]
            auth_net = f"10.235.{int(uuid.uuid4().hex[:4], 16) % 200 + 1}.0/24"
            code, j = await api(c, "POST", "/monitor/scan-auth", token=mgr,
                                json={"network": auth_net, "name": uniq("e2e-auth"), "note": "e2e"})
            assert is_ok(j), j
            auth_id = j["data"]["id"]
            # 扫描（本机无 nmap → 预期优雅失败；scan_options 落库 + error_code 分类）
            code, j = await api(c, "POST", "/monitor/scans", token=mgr,
                                json={"target_ip": net.rsplit(".", 1)[0] + ".11",
                                      "scan_type": "sT", "port_range": "22,80", "nse": True})
            assert is_ok(j), j
            rid = j["data"]["report_id"]
            st = "pending"
            for _ in range(30):
                code, j = await api(c, "GET", f"/monitor/scans/reports/{rid}", token=mgr)
                st = j["data"]["scan_status"]
                if st in ("completed", "failed"):
                    break
                await asyncio.sleep(1)
            assert st in ("completed", "failed"), j
            assert j["data"].get("scan_options", {}).get("port_range") == "22,80", j
            assert j["data"].get("error_code") is not None, "本机无 nmap 应有错误分类"
        await check(c, "监控: 设备/子网/IPAM/扫描授权/扫描", monitor_section)
        if dev_id:
            await api(c, "DELETE", f"/monitor/devices/{dev_id}", token=mgr, params={"reason": "e2e清理"})
        if alloc_id:
            await api(c, "DELETE", f"/monitor/allocations/{alloc_id}", token=mgr)
        if sub_id:
            await api(c, "DELETE", f"/monitor/subnets/{sub_id}", token=mgr, params={"reason": "e2e清理"})
        if auth_id:
            await api(c, "POST", f"/monitor/scan-auth/{auth_id}/revoke", token=mgr)

        # ---------- 审计（仅 admin/auditor 角色可访问，manager 无权限） ----------
        async def audit_section():
            for ep in ("/audit/logs", "/audit/reports/stats", "/audit/reports"):
                code, j = await api(c, "GET", ep, token=aud, params={"size": 10})
                assert is_ok(j), f"{ep}: {j}"
            code, j = await api(c, "GET", "/audit/logs/export", token=aud)
            assert code == 200, j
            code, j = await api(c, "POST", "/audit/reports", token=aud,
                                json={"report_type": "on_demand",
                                      "date_from": "2026-08-01", "date_to": "2026-08-24"})
            assert is_ok(j), j
            report_id = j["data"]["id"]
            code, j = await api(c, "GET", f"/audit/reports/{report_id}", token=aud)
            assert is_ok(j), j
            code, j = await api(c, "GET", f"/audit/reports/{report_id}/export", token=aud)
            assert code == 200, j
        await check(c, "审计: 日志/统计/报告生成/导出", audit_section)

        # ---------- 考勤 ----------
        leave_id = None
        async def leave_section():
            nonlocal leave_id
            now = dt.datetime.now(dt.timezone.utc)  # 后端按 UTC 处理，须传带时区的 ISO
            await _clear_leave_artifacts("analyst01")  # 清掉历史运行的测试请假，避免时段重叠
            code, j = await api(c, "GET", "/leaves", token=mgr, params={"size": 10})
            assert is_ok(j), j
            code, j = await api(c, "GET", "/leaves/mine", token=ana)
            assert is_ok(j), j
            code, j = await api(c, "POST", "/leaves", token=ana, json={
                "leave_type": "on_leave",
                "start_at": (now + dt.timedelta(days=1)).isoformat(),
                "end_at": (now + dt.timedelta(days=2)).isoformat(),
                "reason": "e2e 请假"})
            assert is_ok(j), j
            leave_id = j["data"]["id"]
            code, j = await api(c, "POST", f"/leaves/{leave_id}/approve", token=mgr,
                                json={"note": "e2e 同意"})
            assert is_ok(j), j
        await check(c, "考勤: 申请→审批", leave_section)

        # ---------- 文件 / 统计 ----------
        async def misc_section():
            code, j = await api(c, "POST", "/files", token=mgr,
                                files={"file": ("smoke.txt", b"e2e file content", "text/plain")})
            assert is_ok(j), j
            for ep in ("/stats/overview", "/stats/workspace"):
                code, j = await api(c, "GET", ep, token=mgr)
                assert is_ok(j), f"{ep}: {j}"
            code, j = await api(c, "GET", "/stats/workspace", token=trn)
            assert is_ok(j), j
            code, j = await api(c, "GET", "/users", token=trn)
            assert not is_ok(j), "trainee 访问用户管理应被拒绝"
        await check(c, "文件上传+统计工作台+越权拦截", misc_section)

    print("\n========== 全栈 E2E 结果 ==========")
    for p in PASS:
        print(f"  ✅ {p}")
    for f in FAIL:
        print(f"  ❌ {f}")
    print(f"\n通过 {len(PASS)} 项 | 失败 {len(FAIL)} 项")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
