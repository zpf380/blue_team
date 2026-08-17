"""演示数据：为各子系统填充真实感内容（幂等，可重复执行）。

覆盖：聊天消息 / AI 会话 / 训练进度+积分+徽章 / 漏洞扫描报告 /
历史操作日志（供审计统计图表） / 合规审计报告快照。

用法：python -m scripts.demo_data
"""
import asyncio
import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models import (
    AIConversation,
    AuditReport,
    Channel,
    Device,
    Message,
    OperationLog,
    ScanReport,
    ScoreRecord,
    TrainingProgress,
    TrainingScenario,
    User,
    UserBadge,
)
from app.services.audit_report import generate_report
from app.services.badge_service import check_and_award

TZ = dt.timezone.utc


def _ago(**kw) -> dt.datetime:
    return dt.datetime.now(TZ) - dt.timedelta(**kw)


async def _ensure(session: AsyncSession) -> None:
    users = {u.username: u for u in (await session.execute(select(User))).scalars()}
    channels = {c.name: c for c in (await session.execute(select(Channel))).scalars()}
    devices = {d.name: d for d in (await session.execute(select(Device))).scalars()}
    scenarios = {s.code: s for s in (await session.execute(select(TrainingScenario))).scalars()}
    if not {"manager01", "analyst01", "trainee01", "auditor01"} <= set(users):
        raise RuntimeError("请先运行 python -m scripts.seed_data 预置账号")

    manager, analyst, trainee, auditor = (
        users["manager01"], users["analyst01"], users["trainee01"], users["auditor01"],
    )
    incident, community = channels.get("应急响应组"), channels.get("学员社区")
    web01, db01 = devices.get("web-01"), devices.get("db-01")

    # ---------- 1. 聊天消息（应急响应组） ----------
    incident_msgs = [
        ("manager01", "t1", _ago(hours=26), "@分析师李 昨天的横向移动告警处置得怎么样了？", [analyst.id]),
        ("analyst01", "t2", _ago(hours=25, minutes=40), "正在排查。edr-01 检测到 10.0.10.5 在向多台服务器发起 SMB 扫描，我已经先把该主机从业务网隔离了。", None),
        ("analyst01", "t3", _ago(hours=25, minutes=12), "已定位攻击链：/var/log/auth.log 显示 203.0.113.5 连续暴力破解，已用 iptables 封禁并加固了弱口令账户。", None),
        ("manager01", "t4", _ago(hours=24), "处置干净，我稍后对 web-01 跑一遍扫描复核，出报告给你确认。", None),
        ("analyst01", "t5", _ago(hours=23, minutes=20), "收到。扫描结果出来了：开放端口 5 个、漏洞 3 项，风险评分 62，报告已提交待审核。", None),
        ("manager01", "t6", _ago(hours=22, minutes=5), "已审核通过。今天值班要关注 443 端口的证书是否临期，我建个提醒。", None),
    ]
    cnt = 0
    for uname, key, ts, content, mentions in incident_msgs:
        exists = (await session.execute(
            select(Message).where(Message.content == content, Message.sender_id == users[uname].id)
        )).scalar_one_or_none()
        if not exists:
            session.add(Message(
                channel_id=incident.id, sender_id=users[uname].id, sender_type="user",
                message_type="text", content=content, mentions=mentions, created_at=ts,
            ))
            cnt += 1
    # 学员社区：训练交流（跨角色群聊——分析师以导师身份参与）
    community_msgs = [
        ("trainee01", _ago(hours=20), "刚在「日志分析入门」里跑通了 iptables 封禁，攻击源 IP 一次性定位，还挺有成就感的。"),
        ("trainee01", _ago(hours=18, minutes=30), "分享个技巧：先用 grep 'Failed password' 定位爆破，再 grep IP 二次确认，最后封禁，这样不容易误伤。"),
        ("analyst01", _ago(hours=17, minutes=20), "不错。封禁后记得再复查一遍 outbound 连接，防止攻击者留了反向隧道；有疑问随时来社区交流。"),
        ("trainee01", _ago(hours=16, minutes=10), "谢谢老师！那我在沙箱里再练一遍应急响应全流程，遇到卡点再来请教。"),
    ]
    for uname, ts, content in community_msgs:
        exists = (await session.execute(
            select(Message).where(Message.content == content, Message.sender_id == users[uname].id)
        )).scalar_one_or_none()
        if not exists:
            session.add(Message(
                channel_id=community.id, sender_id=users[uname].id, sender_type="user",
                message_type="text", content=content, created_at=ts,
            ))
            cnt += 1
    print(f"[demo] 聊天消息：新增 {cnt} 条（应急响应组 + 学员社区）")

    # ---------- 2. AI 会话（分析师） ----------
    first_q = "给一份处置「10.0.10.5 横向移动」的标准化清单"
    exists_ai = (await session.execute(
        select(AIConversation).where(
            AIConversation.user_id == analyst.id,
            AIConversation.context_messages.contains([{"role": "user", "content": first_q}]),
        )
    )).scalar_one_or_none()
    if not exists_ai:
        session.add(AIConversation(
            channel_id=incident.id, user_id=analyst.id, agent_name="DeepSeek",
            context_messages=[
                {"role": "user", "content": first_q},
                {"role": "assistant", "content": "横向移动处置建议：1) 立即隔离来源主机（断网/下线）；2) 排查 SMB/3389 相关登录日志；3) 封禁攻击源出口 IP；4) 全量主机检查持久化项；5) 恢复后复盘加固。", },
                {"role": "user", "content": "隔离之后怎么验证是否还有残留连接？"},
                {"role": "assistant", "content": "可在核心交换机镜像流量观察 3 分钟，用 ss -antp 与 edr 全量比对连接，确认无外部回连后恢复入网。", },
            ],
            created_at=_ago(hours=23), updated_at=_ago(hours=22),
        ))
        print("[demo] AI 会话：新增 1 条（分析师 · DeepSeek）")
    else:
        print("[demo] AI 会话：已存在（跳过）")

    # ---------- 3. 训练进度 + 积分 + 徽章（学员） ----------
    progress_specs = [
        ("log-analysis", "completed", 60, 1, _ago(days=3, hours=2), _ago(days=3)),
        ("net-suspect", "completed", 45, 2, _ago(days=2, hours=1), _ago(days=2)),
        ("web-injection", "in_progress", None, 1, _ago(days=1), None),
    ]
    for code, status, score, attempts, started, completed in progress_specs:
        sc = scenarios[code]
        p = (await session.execute(
            select(TrainingProgress).where(
                TrainingProgress.user_id == trainee.id, TrainingProgress.scenario_id == sc.id)
        )).scalar_one_or_none()
        if not p:
            p = TrainingProgress(user_id=trainee.id, scenario_id=sc.id)
            session.add(p)
        p.status, p.score, p.attempts, p.started_at, p.completed_at = (
            status, score, attempts, started, completed)
    # 积分（按场景，幂等）
    score_specs = [
        ("scenario_complete", scenarios["log-analysis"].id, 60, "完成「日志分析入门」"),
        ("scenario_complete", scenarios["net-suspect"].id, 45, "完成「异常连接排查」"),
    ]
    new_scores = 0
    for src, sid, pts, desc in score_specs:
        s = (await session.execute(
            select(ScoreRecord).where(
                ScoreRecord.user_id == trainee.id, ScoreRecord.source_type == src,
                ScoreRecord.source_id == sid)
        )).scalar_one_or_none()
        if not s:
            session.add(ScoreRecord(
                user_id=trainee.id, source_type=src, source_id=sid,
                points=pts, description=desc, created_at=_ago(days=3),
            ))
            new_scores += 1
    await session.flush()
    awarded = await check_and_award(session, trainee)
    badge_names = [b["name"] for b in awarded]
    print(f"[demo] 训练进度：学员王 2 完成 + 1 进行中；新增积分记录 {new_scores} 条；新徽章 {badge_names or '无（已授予）'}")

    # ---------- 4. 漏洞扫描报告 ----------
    scan_specs = [
        {
            "device": web01, "status": "approved", "risk": 62, "generated_by": analyst, "approved_by": manager,
            "target_ip": "10.0.10.11", "ts": _ago(days=1),
            "scan_data": {
                "target_ip": "10.0.10.11",
                "open_ports": [22, 80, 443, 3306, 8080],
                "vulnerabilities": [
                    {"name": "SSH 弱口令风险", "severity": "high", "cve": "CVE-2019-0001"},
                    {"name": "OpenSSL 版本过旧", "severity": "medium", "cve": "CVE-2023-2650"},
                    {"name": "Tomcat AJP 端口暴露", "severity": "high", "cve": "CVE-2020-1938"},
                ],
                "risk_score": 62,
            },
            "summary": "目标 10.0.10.11：发现开放端口 5 个、漏洞 3 项，风险评分 62。",
        },
        {
            "device": db01, "status": "pending_review", "risk": 41, "generated_by": analyst, "approved_by": None,
            "target_ip": "10.0.10.12", "ts": _ago(hours=5),
            "scan_data": {
                "target_ip": "10.0.10.12",
                "open_ports": [22, 3306],
                "vulnerabilities": [
                    {"name": "Redis 未授权访问", "severity": "critical", "cve": "CVE-2022-0543"},
                ],
                "risk_score": 41,
            },
            "summary": "目标 10.0.10.12：发现开放端口 2 个、漏洞 1 项，风险评分 41。",
        },
    ]
    added = 0
    for sp in scan_specs:
        exists = (await session.execute(
            select(ScanReport).where(
                ScanReport.device_id == sp["device"].id, ScanReport.summary == sp["summary"])
        )).scalar_one_or_none()
        if exists:
            continue
        session.add(ScanReport(
            report_type="on_demand", device_id=sp["device"].id, target_ip=sp["target_ip"],
            scan_data=sp["scan_data"], summary=sp["summary"], risk_score=sp["risk"],
            status=sp["status"], approved_by=sp["approved_by"].id if sp["approved_by"] else None,
            generated_by=sp["generated_by"].id, generated_at=sp["ts"],
        ))
        added += 1
    print(f"[demo] 扫描报告：新增 {added} 条（web-01 已审核 / db-01 待审核）")

    # ---------- 5. 历史操作日志（一次性，供审计统计图表） ----------
    marker = (await session.execute(
        select(func.count()).select_from(OperationLog).where(OperationLog.action == "demo:seed")
    )).scalar_one()
    if marker == 0:
        log_specs = [
            # (days_ago, hours, username, action, target_type, target_id, sensitive)
            (13, 3, "admin", "user:create", "user", "u6"),
            (13, 2, "manager01", "auth:login", None, None),
            (12, 9, "analyst01", "auth:login", None, None),
            (12, 5, "analyst01", "monitor:device:probe", "device", "1"),
            (12, 1, "manager01", "ipam:alloc:create", "ip_allocation", "4"),
            (11, 8, "trainee01", "training:scenario:start", "scenario", "1"),
            (11, 4, "analyst01", "chat:message:send", "message", "100"),
            (11, 2, "auditor01", "auth:login", None, None),
            (10, 10, "analyst01", "monitor:scan:create", "scan_report", "1"),
            (10, 6, "manager01", "monitor:scan:review", "scan_report", "1"),
            (10, 1, "manager01", "auth:change_password", "user", "2"),
            (9, 7, "trainee01", "training:submit", "scenario", "1"),
            (9, 3, "trainee01", "training:submit", "scenario", "2"),
            (8, 8, "analyst01", "chat:message:send", "message", "101"),
            (8, 4, "admin", "user:update", "user", "3"),
            (7, 9, "manager01", "auth:login", None, None),
            (7, 5, "analyst01", "monitor:alert:acknowledge", "alert", "3"),
            (6, 6, "analyst01", "monitor:scan:create", "scan_report", "2"),
            (6, 2, "manager01", "monitor:scan:review", "scan_report", "2"),
            (5, 8, "trainee01", "training:scenario:start", "scenario", "3"),
            (5, 4, "trainee01", "training:submit", "scenario", "3"),
            (4, 7, "admin", "auth:login", None, None),
            (4, 1, "manager01", "ipam:alloc:release", "ip_allocation", "3"),
            (3, 9, "analyst01", "chat:message:send", "message", "102"),
            (3, 5, "analyst01", "monitor:device:probe", "device", "2"),
            (2, 6, "trainee01", "training:submit", "scenario", "2"),
            (2, 3, "auditor01", "auth:login", None, None),
            (1, 8, "analyst01", "monitor:scan:create", "scan_report", "3"),
            (1, 4, "manager01", "monitor:scan:review", "scan_report", "3"),
            (0, 2, "analyst01", "auth:login", None, None),
        ]
        for days, hrs, uname, action, tt, tid in log_specs:
            u = users[uname]
            session.add(OperationLog(
                user_id=u.id, username=u.username, role_code=u.role.code if u.role else None,
                action=action, target_type=tt, target_id=tid,
                detail={}, ip_address="10.0.0.10", user_agent="demo-seed",
                created_at=_ago(days=days, hours=hrs),
            ))
        session.add(OperationLog(
            username="demo_seed", role_code=None, action="demo:seed",
            detail={"batch": "demo_data_v1"}, created_at=_ago(hours=0),
        ))
        print(f"[demo] 历史操作日志：写入 {len(log_specs)} 条（一次性）")
    else:
        print("[demo] 历史操作日志：已存在（跳过）")

    # ---------- 6. 合规审计报告快照 ----------
    today = dt.date.today()
    exists_report = (await session.execute(
        select(AuditReport).where(AuditReport.title.like("%演示%合规审计报告%"))
    )).scalar_one_or_none()
    if not exists_report:
        report = await generate_report(
            session, auditor, "on_demand",
            date_from=today - dt.timedelta(days=13), date_to=today,
        )
        report.title = f"演示按需合规审计报告（{today - dt.timedelta(days=13)} ~ {today}）"
        print("[demo] 合规审计报告：生成 1 份（按需）")
    else:
        print("[demo] 合规审计报告：已存在（跳过）")

    await session.commit()
    print("[demo] 演示数据完成")


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await _ensure(session)


if __name__ == "__main__":
    asyncio.run(main())
