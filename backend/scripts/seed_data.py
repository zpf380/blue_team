"""预置数据：5 角色 + 权限、默认部门、管理员与各角色演示账号（幂等）。

用法：python -m scripts.seed_data
"""
import asyncio
import datetime as dt
import getpass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import (
    ALL,
    AUDIT_LOG,
    AUDIT_REPORT,
    CHAT_AI,
    CHAT_CHANNEL,
    CHAT_DM,
    CHAT_VIEW,
    DASHBOARD_ADMIN,
    DASHBOARD_AUDIT,
    DASHBOARD_CHAT,
    DASHBOARD_SECURITY,
    DASHBOARD_TRAINING,
    DEPARTMENT_MANAGE,
    IPAM_MANAGE,
    LEAVE_APPROVE,
    LEAVE_APPLY,
    MONITOR_ALERT_MANAGE,
    MONITOR_ALERT_VIEW,
    MONITOR_DEVICE_MANAGE,
    MONITOR_DEVICE_VIEW,
    MONITOR_SCAN,
    MONITOR_VIEW,
    TRAINING_AGENT_VIEW,
    TRAINING_COURSE_MANAGE,
    TRAINING_RANKING,
    TRAINING_SANDBOX,
    TRAINING_STATS,
    TRAINING_VIEW,
    USER_MANAGE,
)
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models import Department, Role, User

ROLES = [
    {
        "code": "admin",
        "name": "系统管理员",
        "description": "系统配置、用户管理、权限分配",
        "permissions": [ALL],
        "data_scope": "all",
    },
    {
        "code": "manager",
        "name": "安全主管",
        "description": "审批报告、查看统计、团队管理",
        "permissions": [
            DASHBOARD_SECURITY,
            CHAT_VIEW, CHAT_CHANNEL, CHAT_DM, CHAT_AI,
            MONITOR_VIEW, MONITOR_DEVICE_VIEW, MONITOR_DEVICE_MANAGE, MONITOR_ALERT_VIEW, MONITOR_ALERT_MANAGE, MONITOR_SCAN, IPAM_MANAGE,
            TRAINING_VIEW, TRAINING_STATS, TRAINING_RANKING, TRAINING_COURSE_MANAGE,
            AUDIT_REPORT,
            DEPARTMENT_MANAGE,  # 部门管理：新增/编辑/删除（admin 靠 * 通配，manager 显式授权）
            LEAVE_APPLY, LEAVE_APPROVE,  # 考勤：本人申请 + 主管审批
        ],
        "data_scope": "all",
    },
    {
        "code": "analyst",
        "name": "安全分析师",
        "description": "事件响应、设备监控、技能训练",
        "permissions": [
            DASHBOARD_CHAT,
            CHAT_VIEW, CHAT_CHANNEL, CHAT_DM, CHAT_AI,
            MONITOR_VIEW, MONITOR_DEVICE_VIEW, MONITOR_DEVICE_MANAGE, MONITOR_ALERT_VIEW, MONITOR_ALERT_MANAGE, MONITOR_SCAN,
            TRAINING_VIEW, TRAINING_AGENT_VIEW, TRAINING_SANDBOX, TRAINING_STATS, TRAINING_RANKING,
            LEAVE_APPLY,
        ],
        "data_scope": "dept",
    },
    {
        "code": "trainee",
        "name": "训练学员",
        "description": "参与课程、沙箱实训、能力认证",
        "permissions": [
            DASHBOARD_TRAINING,
            TRAINING_VIEW, TRAINING_AGENT_VIEW, TRAINING_SANDBOX, TRAINING_STATS, TRAINING_RANKING,
            CHAT_VIEW, CHAT_CHANNEL, CHAT_DM,  # 可私聊（服务端已限制学员仅能私聊学员）
            LEAVE_APPLY,
        ],
        "data_scope": "self",
    },
    {
        "code": "auditor",
        "name": "审计员",
        "description": "合规检查、操作追溯、只读审计",
        "permissions": [
            DASHBOARD_AUDIT,
            AUDIT_LOG, AUDIT_REPORT,
            MONITOR_VIEW, MONITOR_DEVICE_VIEW, MONITOR_ALERT_VIEW,
            LEAVE_APPLY,  # 审计员同为员工，个人考勤与审计只读职责不冲突
        ],
        "data_scope": "all",
    },
]

DEPARTMENTS = [
    {"name": "安全运营部", "parent": None},
    {"name": "攻防实验室", "parent": "安全运营部"},
    {"name": "应急响应组", "parent": "安全运营部"},
]

DEMO_USERS = [
    {"username": "manager01", "real_name": "主管张", "role": "manager", "department": "安全运营部"},
    {"username": "analyst01", "real_name": "分析师李", "role": "analyst", "department": "攻防实验室"},
    {"username": "trainee01", "real_name": "学员王", "role": "trainee", "department": "攻防实验室"},
    {"username": "trainee02", "real_name": "学员陈", "role": "trainee", "department": "攻防实验室"},
    {"username": "auditor01", "real_name": "审计员赵", "role": "auditor", "department": "安全运营部"},
]

DEFAULT_PASSWORD = "Bt@123456"


async def _ensure(session: AsyncSession) -> None:
    # 角色
    role_map = {}
    for r in ROLES:
        existing = (await session.execute(select(Role).where(Role.code == r["code"]))).scalar_one_or_none()
        if existing:
            existing.permissions = r["permissions"]
            existing.data_scope = r["data_scope"]
            existing.name = r["name"]
            role_map[r["code"]] = existing
        else:
            role = Role(**r)
            session.add(role)
            role_map[r["code"]] = role
    await session.flush()

    # 部门
    dept_map = {}
    for d in DEPARTMENTS:
        existing = (await session.execute(select(Department).where(Department.name == d["name"]))).scalar_one_or_none()
        if existing:
            dept_map[d["name"]] = existing
        else:
            dept = Department(name=d["name"])
            session.add(dept)
            dept_map[d["name"]] = dept
    await session.flush()
    for d in DEPARTMENTS:
        if d["parent"] and d["name"] in dept_map:
            dept_map[d["name"]].parent_id = dept_map[d["parent"]].id

    # 管理员（默认密码 admin123，与文档一致；可用 create_admin.py 重置）
    admin = (await session.execute(select(User).where(User.username == "admin"))).scalar_one_or_none()
    admin_password = "admin123"
    if not admin:
        admin = User(
            username="admin",
            real_name="系统管理员",
            password_hash=hash_password(admin_password),
            role_id=role_map["admin"].id,
            department_id=dept_map["安全运营部"].id,
            position="系统管理员",
            status="active",
        )
        session.add(admin)
        print(f"[seed] 创建管理员 admin / {admin_password}")
    else:
        admin.role_id = role_map["admin"].id
        print("[seed] 管理员已存在，已更新角色。")

    # 演示账号
    for d in DEMO_USERS:
        existing = (await session.execute(select(User).where(User.username == d["username"]))).scalar_one_or_none()
        if existing:
            continue
        session.add(
            User(
                username=d["username"],
                real_name=d["real_name"],
                password_hash=hash_password(DEFAULT_PASSWORD),
                role_id=role_map[d["role"]].id,
                department_id=dept_map[d["department"]].id,
                position=d["real_name"],
                status="active",
            )
        )
        print(f"[seed] 创建演示账号 {d['username']} / {DEFAULT_PASSWORD}")

    # ---------- 聊天频道（幂等，仅建频道不加成员） ----------
    # 规则：群组列表初始为空，用户须「输入群组名称加入」后才可见/通信；管理员监控视图豁免
    from app.models import Channel

    CHANNELS = [
        {"name": "应急响应组", "type": "public", "description": "事件响应协作与告警推送"},
        {"name": "安全公告", "type": "public", "description": "安全通告与运营信息"},
        {"name": "学员社区", "type": "trainee", "description": "学员训练交流社区（跨角色群聊）"},
    ]
    for spec in CHANNELS:
        ch = (await session.execute(select(Channel).where(Channel.name == spec["name"]))).scalar_one_or_none()
        if not ch:
            session.add(Channel(name=spec["name"], type=spec["type"], description=spec["description"]))
    print("[seed] 聊天频道：应急响应组 / 安全公告 / 学员社区（不加成员，需输入名称加入）")

    # ---------- 训练智能体 / 场景 / 徽章（幂等） ----------
    from app.models import Badge, TrainingAgent, TrainingScenario

    AGENTS = [
        {"code": "foundation", "name": "蓝队基础", "difficulty": 1, "description": "从日志分析开始，掌握蓝队基本功：看日志、找异常、封攻击源。", "prerequisites": [], "order_index": 1},
        {"code": "incident", "name": "应急响应实战", "difficulty": 2, "description": "模拟服务器被入侵的完整处置流程：排查进程、连接、取证与封禁。", "prerequisites": ["foundation"], "order_index": 2},
        {"code": "hardening", "name": "安全加固", "difficulty": 3, "description": "面向主机与服务的加固演练：弱口令治理、防火墙规则、端口收敛。", "prerequisites": ["incident"], "order_index": 3},
    ]
    agent_map = {}
    for a in AGENTS:
        agent = (await session.execute(select(TrainingAgent).where(TrainingAgent.code == a["code"]))).scalar_one_or_none()
        if not agent:
            agent = TrainingAgent(code=a["code"], name=a["name"], difficulty=a["difficulty"], description=a["description"], prerequisites=a["prerequisites"], order_index=a["order_index"])
            session.add(agent)
            await session.flush()
        else:
            agent.name, agent.difficulty, agent.description, agent.prerequisites, agent.order_index = (
                a["name"], a["difficulty"], a["description"], a["prerequisites"], a["order_index"])
        agent.status = "published"
        if not agent.published_at:
            agent.published_at = dt.datetime.now(dt.timezone.utc)
        agent_map[a["code"]] = agent
    await session.flush()

    AUTH_LOG = """Aug 13 02:11:07 login sshd[1042]: Failed password for root from 203.0.113.5 port 51243 ssh2
Aug 13 02:11:11 login sshd[1043]: Failed password for root from 203.0.113.5 port 51247 ssh2
Aug 13 02:11:19 login sshd[1044]: Failed password for admin from 203.0.113.5 port 51251 ssh2
Aug 13 02:11:26 login sshd[1045]: Failed password for root from 203.0.113.5 port 51255 ssh2
Aug 13 02:12:01 login sshd[1046]: Failed password for root from 203.0.113.5 port 51259 ssh2
Aug 13 02:12:09 login sshd[1047]: Failed password for root from 203.0.113.5 port 51263 ssh2
Aug 13 02:12:14 login sshd[1048]: Accepted password for analyst01 from 10.0.0.5 port 53221 ssh2
Aug 13 09:12:30 login sshd[1210]: Accepted password for root from 10.0.0.2 port 44421 ssh2"""

    NGINX_LOG = """192.168.1.21 - - [13/Aug/2026:01:03:44 +0800] "GET /product.php?id=1 HTTP/1.1" 200 512
192.168.1.21 - - [13/Aug/2026:01:03:52 +0800] "GET /product.php?id=1' UNION SELECT username,password FROM users-- HTTP/1.1" 200 4096
192.168.1.21 - - [13/Aug/2026:01:04:01 +0800] "GET /product.php?id=1' OR 1=1-- HTTP/1.1" 200 4096
192.168.1.21 - - [13/Aug/2026:01:04:15 +0800] "POST /login.php HTTP/1.1" 302 0
10.0.0.30 - - [13/Aug/2026:02:31:02 +0800] "GET /index.html HTTP/1.1" 200 1024
10.0.0.30 - - [13/Aug/2026:02:31:09 +0800] "GET /css/app.css HTTP/1.1" 200 2048"""

    SCENARIOS = [
        {
            "agent": "foundation", "code": "log-analysis", "title": "日志分析入门：发现暴力破解",
            "description": "通过认证日志定位暴力破解攻击源并封禁。",
            "points": 60, "penalty_points": 5, "order_index": 1,
            "content": {
                "intro": "应急值班室接到告警：服务器 /var/log/auth.log 出现大量认证失败。\n\n你的任务：1) 查看认证日志；2) 找到失败登录记录；3) 定位攻击源 IP；4) 用 iptables 封禁该 IP。\n\n提示：先试试 ls、cat，再看看日志里有什么。",
                "files": {
                    "/etc/passwd": "root:x:0:0:root:/root:/bin/bash\ndaemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\nwww:x:1001:1001:www-data:/var/www:/usr/sbin/nologin",
                    "/var/log/auth.log": AUTH_LOG,
                },
                "tasks": [
                    {"id": "t1", "title": "查看认证日志", "points": 10, "hint": "cat /var/log/auth.log", "check": {"cmd": "cat", "args": "/var/log/auth.log"}},
                    {"id": "t2", "title": "定位失败登录记录", "points": 15, "hint": "grep 'Failed password' /var/log/auth.log", "check": {"cmd": "grep", "pattern": "Failed password"}},
                    {"id": "t3", "title": "确认攻击源 IP", "points": 15, "hint": "grep '203.0.113.5' /var/log/auth.log", "check": {"cmd": "grep", "pattern": "203.0.113.5"}},
                    {"id": "t4", "title": "封禁攻击源 IP", "points": 20, "hint": "iptables -A INPUT -s 203.0.113.5 -j DROP", "check": {"cmd": "iptables", "pattern": "203.0.113.5"}},
                ],
            },
        },
        {
            "agent": "foundation", "code": "net-suspect", "title": "异常连接排查",
            "description": "通过进程与网络连接识别可疑会话。",
            "points": 50, "penalty_points": 5, "order_index": 2,
            "content": {
                "intro": "同事反馈服务器负载异常，怀疑被植入后门。\n\n请排查：1) 查看运行中的进程；2) 查看网络连接；3) 确认异常连接来源。\n\n提示：进程里有可疑程序，连接里有不明来源。",
                "files": {
                    "/var/log/auth.log": AUTH_LOG,
                    "/tmp/.x": "#!/bin/sh\n# suspicious persistence\nnohup /tmp/.x &",
                },
                "tasks": [
                    {"id": "t1", "title": "查看进程列表", "points": 10, "hint": "ps", "check": {"cmd": "ps"}},
                    {"id": "t2", "title": "查看可疑进程文件", "points": 15, "hint": "cat /tmp/.x", "check": {"cmd": "cat", "args": "/tmp/.x"}},
                    {"id": "t3", "title": "查看网络连接", "points": 10, "hint": "ss -antp", "check": {"cmd": "ss"}},
                    {"id": "t4", "title": "确认异常连接来源", "points": 15, "hint": "在 ss 输出中确认 203.0.113.5", "check": {"cmd": "ss", "output_contains": "203.0.113.5"}},
                ],
            },
        },
        {
            "agent": "incident", "code": "web-injection", "title": "应急响应：Web 注入攻击处置",
            "description": "分析访问日志定位 SQL 注入攻击并封禁来源。",
            "points": 70, "penalty_points": 10, "order_index": 1,
            "content": {
                "intro": "WAF 报警：网站疑似遭到 SQL 注入攻击。请分析访问日志、定位注入尝试并封禁攻击源。\n\n步骤提示：tail 日志 → 查找注入关键字 → 确认攻击 IP → 封禁。",
                "files": {
                    "/var/log/nginx/access.log": NGINX_LOG,
                    "/var/log/auth.log": AUTH_LOG,
                },
                "tasks": [
                    {"id": "t1", "title": "查看访问日志", "points": 10, "hint": "tail /var/log/nginx/access.log", "check": {"cmd": "tail", "args": "/var/log/nginx/access.log"}},
                    {"id": "t2", "title": "定位 SQL 注入请求", "points": 20, "hint": "grep 'UNION SELECT' /var/log/nginx/access.log", "check": {"cmd": "grep", "pattern": "UNION"}},
                    {"id": "t3", "title": "确认攻击源 IP", "points": 15, "hint": "grep '192.168.1.21' /var/log/nginx/access.log", "check": {"cmd": "grep", "pattern": "192.168.1.21"}},
                    {"id": "t4", "title": "封禁注入攻击源", "points": 25, "hint": "iptables -A INPUT -s 192.168.1.21 -j DROP", "check": {"cmd": "iptables", "pattern": "192.168.1.21"}},
                ],
            },
        },
        {
            "agent": "incident", "code": "root-login", "title": "应急响应：root 异地登录",
            "description": "识别非法 root 登录行为并实施处置。",
            "points": 55, "penalty_points": 5, "order_index": 2,
            "content": {
                "intro": "夜间审计发现 root 账号在非办公时段成功登录，疑似凭证泄露。\n\n请排查认证日志、确认登录来源并封禁。",
                "files": {
                    "/var/log/auth.log": AUTH_LOG,
                    "/etc/passwd": "root:x:0:0:root:/root:/bin/bash\nwww:x:1001:1001:www-data:/var/www:/usr/sbin/nologin",
                },
                "tasks": [
                    {"id": "t1", "title": "查看认证日志", "points": 10, "hint": "cat /var/log/auth.log", "check": {"cmd": "cat", "args": "/var/log/auth.log"}},
                    {"id": "t2", "title": "定位 root 登录记录", "points": 15, "hint": "grep 'Accepted password' /var/log/auth.log", "check": {"cmd": "grep", "pattern": "Accepted"}},
                    {"id": "t3", "title": "识别可疑登录 IP", "points": 15, "hint": "grep '203.0.113.5' /var/log/auth.log", "check": {"cmd": "grep", "pattern": "203.0.113.5"}},
                    {"id": "t4", "title": "封禁可疑来源", "points": 15, "hint": "iptables -A INPUT -s 203.0.113.5 -j DROP", "check": {"cmd": "iptables", "pattern": "203.0.113.5"}},
                ],
            },
        },
        {
            "agent": "hardening", "code": "fw-hardening", "title": "安全加固：防火墙策略核查",
            "description": "检查防火墙规则，补充缺失的防护策略。",
            "points": 45, "penalty_points": 10, "order_index": 1,
            "content": {
                "intro": "安全合规检查要求主机防火墙具备防暴力破解策略。\n\n请：1) 查看现有 iptables 规则；2) 为攻击源 203.0.113.5 添加 DROP 规则。",
                "files": {
                    "/var/log/auth.log": AUTH_LOG,
                },
                "tasks": [
                    {"id": "t1", "title": "查看防火墙规则", "points": 15, "hint": "iptables -L", "check": {"cmd": "iptables", "args": "-L"}},
                    {"id": "t2", "title": "封禁暴力破解来源", "points": 30, "hint": "iptables -A INPUT -s 203.0.113.5 -j DROP", "check": {"cmd": "iptables", "pattern": "203.0.113.5"}},
                ],
            },
        },
    ]
    # 自愈历史重复：早期版本按 code 匹配（code 曾被漏写为 NULL），导致每次 seed 重复插入场景。
    # 按 title 分组保留最小 id，重指进度/会话/积分引用后删除其余重复行。
    from sqlalchemy import update as sa_update
    from app.models import SandboxSession, ScoreRecord, TrainingProgress
    _rn = func.row_number().over(partition_by=TrainingScenario.title, order_by=TrainingScenario.id).label("rn")
    _sub = select(TrainingScenario.id, _rn).subquery()
    removed = 0
    for dup_id in (await session.execute(select(_sub.c.id).where(_sub.c.rn > 1))).scalars():
        dup = await session.get(TrainingScenario, dup_id)
        keep_id = (await session.execute(
            select(func.min(TrainingScenario.id)).where(TrainingScenario.title == dup.title)
        )).scalar_one()
        await session.execute(sa_update(TrainingProgress).where(TrainingProgress.scenario_id == dup_id).values(scenario_id=keep_id))
        await session.execute(sa_update(SandboxSession).where(SandboxSession.scenario_id == dup_id).values(scenario_id=keep_id))
        await session.execute(sa_update(ScoreRecord).where(
            ScoreRecord.source_type == "scenario_complete", ScoreRecord.source_id == dup_id).values(source_id=keep_id))
        await session.delete(dup)
        removed += 1
    if removed:
        await session.flush()
        print(f"[seed] 清理重复训练场景 {removed} 条（自愈）")

    for spec in SCENARIOS:
        # 历史 bug：code 列曾被漏写（全为 NULL），导致按 code 匹配恒失败、每次 seed 重复插入。
        # 现在同时按 code 或 title 匹配并补写 code，保证幂等。
        sc = (
            await session.execute(
                select(TrainingScenario).where(
                    (TrainingScenario.code == spec["code"]) | (TrainingScenario.title == spec["title"])
                )
            )
        ).scalar_one_or_none()
        agent = agent_map[spec["agent"]]
        if not sc:
            sc = TrainingScenario(
                agent_id=agent.id, code=spec["code"], title=spec["title"], description=spec["description"],
                scenario_type="simulation", content=spec["content"], sandbox_config={"shell": "linux-sim"},
                points=spec["points"], penalty_points=spec["penalty_points"], order_index=spec["order_index"],
            )
            session.add(sc)
        else:
            sc.agent_id, sc.code, sc.title, sc.description, sc.content, sc.points, sc.penalty_points, sc.order_index = (
                agent.id, spec["code"], spec["title"], spec["description"], spec["content"], spec["points"], spec["penalty_points"], spec["order_index"])
    await session.flush()
    print(f"[seed] 训练智能体：{len(AGENTS)} 个；场景：{len(SCENARIOS)} 个")

    BADGES = [
        {"name": "初次告捷", "description": "完成第一个训练场景", "condition_type": "first_completion", "condition_value": {}},
        {"name": "蓝队新秀", "description": "完成「蓝队基础」全部场景", "condition_type": "complete_agent", "condition_value": {"agent_id": agent_map["foundation"].id}},
        {"name": "应急先锋", "description": "完成「应急响应实战」全部场景", "condition_type": "complete_agent", "condition_value": {"agent_id": agent_map["incident"].id}},
        {"name": "加固专家", "description": "完成「安全加固」全部场景", "condition_type": "complete_agent", "condition_value": {"agent_id": agent_map["hardening"].id}},
        {"name": "满分专家", "description": "任一场景零扣分满分完成", "condition_type": "perfect_score", "condition_value": {}},
        {"name": "积分达人", "description": "累计训练积分达到 100 分", "condition_type": "total_points", "condition_value": {"points": 100}},
        {"name": "金牌选手", "description": "累计训练积分达到 300 分", "condition_type": "total_points", "condition_value": {"points": 300}},
    ]
    for b in BADGES:
        existing = (await session.execute(select(Badge).where(Badge.name == b["name"]))).scalar_one_or_none()
        if existing:
            existing.description, existing.condition_type, existing.condition_value = b["description"], b["condition_type"], b["condition_value"]
        else:
            session.add(Badge(**b))
    print("[seed] 训练徽章：初次告捷 / 蓝队新秀 / 应急先锋 / 加固专家 / 满分专家 / 积分达人 / 金牌选手")

    # ---------- 监控：设备 / 子网 / 分配 / 告警（幂等） ----------
    from app.models import Alert, Device, IPAllocation, IPSubnet

    dept_by_name = {d.name: d for d in (await session.execute(select(Department))).scalars()}
    users_by_uname = {u.username: u for u in (await session.execute(select(User))).scalars()}

    DEVICES = [
        {"name": "web-01", "ip": "10.0.10.11", "mac": "02:42:ac:11:00:11", "type": "web_server", "manufacturer": "Dell", "model": "R640", "location": "机房A-01", "dept": "安全运营部", "owner": "manager01"},
        {"name": "db-01", "ip": "10.0.10.12", "mac": "02:42:ac:11:00:12", "type": "database", "manufacturer": "Dell", "model": "R640", "location": "机房A-01", "dept": "攻防实验室", "owner": "analyst01"},
        {"name": "edr-01", "ip": "10.0.10.21", "mac": "02:42:ac:11:00:21", "type": "security_appliance", "manufacturer": "Huawei", "model": "USG6300", "location": "机房B-02", "dept": "应急响应组", "owner": "analyst01"},
        {"name": "fw-core", "ip": "10.0.0.1", "mac": "02:42:ac:10:00:01", "type": "firewall", "manufacturer": "Huawei", "model": "USG6600", "location": "核心机房", "dept": "安全运营部", "owner": "manager01"},
    ]
    for spec in DEVICES:
        d = (await session.execute(select(Device).where(Device.ip_address == spec["ip"]))).scalar_one_or_none()
        dept = dept_by_name.get(spec["dept"])
        owner = users_by_uname.get(spec["owner"])
        if not d:
            session.add(Device(
                name=spec["name"], ip_address=spec["ip"], mac_address=spec["mac"], device_type=spec["type"],
                manufacturer=spec["manufacturer"], model=spec["model"], location=spec["location"],
                department_id=dept.id if dept else None, owner_id=owner.id if owner else None,
                status="active",
            ))
        else:
            d.department_id = dept.id if dept else None
            d.owner_id = owner.id if owner else None
            d.status = "active"
    await session.flush()
    print("[seed] 监控设备：web-01 / db-01 / edr-01 / fw-core")

    SUBNETS = [
        {"name": "办公网", "network": "10.0.0.0/24", "gateway": "10.0.0.1", "vlan_id": 10, "dept": "安全运营部"},
        {"name": "业务网", "network": "10.0.10.0/24", "gateway": "10.0.10.1", "vlan_id": 20, "dept": "攻防实验室"},
        {"name": "服务器网", "network": "10.0.20.0/24", "gateway": "10.0.20.1", "vlan_id": 30, "dept": "应急响应组"},
    ]
    subnet_by_name = {}
    for spec in SUBNETS:
        s = (await session.execute(select(IPSubnet).where(IPSubnet.network == spec["network"]))).scalar_one_or_none()
        dept = dept_by_name.get(spec["dept"])
        if not s:
            s = IPSubnet(name=spec["name"], network=spec["network"], gateway=spec["gateway"], vlan_id=spec["vlan_id"], department_id=dept.id if dept else None)
            session.add(s)
        else:
            s.department_id = dept.id if dept else None
        subnet_by_name[spec["name"]] = s
    await session.flush()

    ALLOCATIONS = [
        {"subnet": "业务网", "ip": "10.0.10.11", "device": "web-01", "purpose": "Web 业务"},
        {"subnet": "业务网", "ip": "10.0.10.12", "device": "db-01", "purpose": "数据库"},
        {"subnet": "业务网", "ip": "10.0.10.21", "device": "edr-01", "purpose": "EDR 探针"},
    ]
    for spec in ALLOCATIONS:
        a = (await session.execute(select(IPAllocation).where(IPAllocation.ip_address == spec["ip"]))).scalar_one_or_none()
        device = (await session.execute(select(Device).where(Device.name == spec["device"]))).scalar_one_or_none()
        if not a:
            session.add(IPAllocation(
                subnet_id=subnet_by_name[spec["subnet"]].id, ip_address=spec["ip"],
                device_id=device.id if device else None, allocation_type="static", purpose=spec["purpose"],
            ))
    await session.flush()

    ALERTS = [
        {"device": "web-01", "type": "response_time", "severity": "high", "title": "Web 服务响应时间超阈值", "description": "连续 5 分钟响应时间超过 3s，疑似负载异常。", "status": "open"},
        {"device": "db-01", "type": "db_slow_query", "severity": "medium", "title": "数据库慢查询告警", "description": "检测到慢查询：SELECT * FROM orders WHERE status=1；耗时 4.2s。", "status": "open"},
        {"device": "edr-01", "type": "lateral_movement", "severity": "critical", "title": "疑似横向移动行为", "description": "内部主机 10.0.10.5 向多台服务器发起 SMB 连接，疑似横向扩散。", "status": "open"},
    ]
    for spec in ALERTS:
        device = (await session.execute(select(Device).where(Device.name == spec["device"]))).scalar_one_or_none()
        exists = (await session.execute(select(Alert).where(Alert.title == spec["title"]))).scalar_one_or_none()
        if not exists:
            session.add(Alert(
                device_id=device.id if device else None, alert_type=spec["type"], severity=spec["severity"],
                title=spec["title"], description=spec["description"], status=spec["status"],
            ))
    print("[seed] 监控子网 3 个 + 静态分配 3 条 + 告警 3 条")

    await session.commit()


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await _ensure(session)
    print("[seed] 预置数据完成。账号：admin / manager01 / analyst01 / trainee01 / trainee02 / auditor01")


if __name__ == "__main__":
    asyncio.run(main())
