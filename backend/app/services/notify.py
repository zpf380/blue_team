"""告警外部通知：企业微信 / 钉钉 / 通用 webhook + SMTP 邮件。

设计要点：
- 任一渠道失败一律静默（记日志），绝不影响业务主流程与响应。
- 未配置对应渠道 → no-op（返回 False），部署零配置也可正常运行。
- `notify_alert_task` 为后台任务：发送成功后回写 alerts.notified_at（供前端展示"已通知"）。
"""
import asyncio
import datetime as dt
import logging
import smtplib
import ssl
from email.mime.text import MIMEText

import httpx

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models import Alert

logger = logging.getLogger("app.notify")

_SEVERITY_LABEL = {"critical": "严重", "high": "高", "medium": "中", "low": "低", "info": "提示"}


def _severity_label(severity: str | None) -> str:
    return _SEVERITY_LABEL.get(severity or "", severity or "未知")


async def send_alert_notification(title: str, content: str, severity: str | None = None) -> bool:
    """发送告警通知（webhook + 邮件并行）。返回是否至少一个渠道发送成功。"""
    ok = await asyncio.gather(
        _send_webhook(title, content, severity),
        _send_email(title, content, severity),
        return_exceptions=True,
    )
    fired = False
    for r in ok:
        if r is True:
            fired = True
        elif isinstance(r, BaseException):
            logger.warning("告警通知渠道异常：%s", r)
    return fired


async def notify_alert_task(alert_id: int, title: str, content: str, severity: str | None) -> None:
    """后台任务：发送告警通知，成功后回写 alerts.notified_at。任何失败都不上抛。"""
    try:
        sent = await send_alert_notification(title, content, severity)
        if sent:
            async with AsyncSessionLocal() as session:
                a = await session.get(Alert, alert_id)
                if a:
                    a.notified_at = dt.datetime.now(dt.timezone.utc)
                    await session.commit()
    except Exception:  # noqa: BLE001 —— 通知链路失败不影响主流程
        logger.exception("告警通知/回写失败 alert_id=%s", alert_id)


async def _send_webhook(title: str, content: str, severity: str | None) -> bool:
    url = settings.ALERT_NOTIFY_WEBHOOK_URL
    if not url:
        return False
    wt = settings.ALERT_NOTIFY_WEBHOOK_TYPE
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    text = f"【蓝队告警 · {_severity_label(severity)}】{title}\n{content}\n[{now}]"
    if wt == "feishu":
        payload = {"msg_type": "text", "content": {"text": text}}
    elif wt in ("wecom", "dingtalk"):
        payload = {"msgtype": "text", "text": {"content": text}}
    else:  # generic：通用 JSON 回调
        payload = {"title": title, "content": content, "severity": severity, "time": now}
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
    return True


async def _send_email(title: str, content: str, severity: str | None) -> bool:
    to = settings.ALERT_NOTIFY_EMAIL_TO
    if not to or not settings.SMTP_HOST:
        return False
    body = f"级别：{_severity_label(severity)}\n标题：{title}\n\n{content}"
    await asyncio.to_thread(
        _smtp_send, f"[蓝队告警] {title}", body, [e.strip() for e in to.split(",") if e.strip()]
    )
    return True


def _smtp_send(subject: str, body: str, to_list: list[str]) -> None:
    """同步 SMTP 发送（在线程池中执行）。仅支持 SSL（465）；STARTTLS 环境可自行扩展。"""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USERNAME
    msg["To"] = ", ".join(to_list)
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10, context=ctx) as server:
        if settings.SMTP_USERNAME:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.sendmail(msg["From"], to_list, msg.as_string())
