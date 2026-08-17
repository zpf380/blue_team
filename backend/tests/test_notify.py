"""告警外部通知单元测试：webhook（企业微信/钉钉/通用）+ 邮件渠道与配置开关。

纯单测，不依赖数据库/网络：httpx 与 SMTP 全部 mock。
"""
import pytest


class _FakeResp:
    def raise_for_status(self):
        return None


class _FakeClient:
    """记录调用并返回固定响应的 httpx.AsyncClient 替身。"""

    def __init__(self, *a, **k):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        self.calls.append((url, json))
        return _FakeResp()


async def test_no_channel_configured_returns_false(monkeypatch):
    """全渠道未配置 → no-op，返回 False（部署零配置也可运行）。"""
    from app.services import notify

    monkeypatch.setattr(notify.settings, "ALERT_NOTIFY_WEBHOOK_URL", "")
    monkeypatch.setattr(notify.settings, "ALERT_NOTIFY_EMAIL_TO", "")
    assert await notify.send_alert_notification("标题", "内容", "high") is False


async def test_wecom_webhook_payload(monkeypatch):
    from app.services import notify

    fake = _FakeClient()
    monkeypatch.setattr(notify.httpx, "AsyncClient", lambda *a, **k: fake)
    monkeypatch.setattr(notify.settings, "ALERT_NOTIFY_WEBHOOK_URL", "https://qyapi.example/hook")
    monkeypatch.setattr(notify.settings, "ALERT_NOTIFY_WEBHOOK_TYPE", "wecom")
    monkeypatch.setattr(notify.settings, "ALERT_NOTIFY_EMAIL_TO", "")

    assert await notify.send_alert_notification("Redis 未授权访问", "端口 6379 暴露", "critical") is True
    url, payload = fake.calls[0]
    assert url == "https://qyapi.example/hook"
    assert payload["msgtype"] == "text"
    assert "Redis 未授权访问" in payload["text"]["content"]
    assert "严重" in payload["text"]["content"]  # 级别中文映射


async def test_dingtalk_webhook_same_shape(monkeypatch):
    from app.services import notify

    fake = _FakeClient()
    monkeypatch.setattr(notify.httpx, "AsyncClient", lambda *a, **k: fake)
    monkeypatch.setattr(notify.settings, "ALERT_NOTIFY_WEBHOOK_URL", "https://oapi.dingtalk.example/robot/send")
    monkeypatch.setattr(notify.settings, "ALERT_NOTIFY_WEBHOOK_TYPE", "dingtalk")
    monkeypatch.setattr(notify.settings, "ALERT_NOTIFY_EMAIL_TO", "")

    assert await notify.send_alert_notification("入侵检测", "异常登录", "critical") is True
    assert fake.calls[0][1]["msgtype"] == "text"


async def test_feishu_webhook_payload(monkeypatch):
    """飞书机器人：msg_type=text + content.text 结构。"""
    from app.services import notify

    fake = _FakeClient()
    monkeypatch.setattr(notify.httpx, "AsyncClient", lambda *a, **k: fake)
    monkeypatch.setattr(
        notify.settings, "ALERT_NOTIFY_WEBHOOK_URL", "https://open.feishu.cn/open-apis/bot/v2/hook/test"
    )
    monkeypatch.setattr(notify.settings, "ALERT_NOTIFY_WEBHOOK_TYPE", "feishu")
    monkeypatch.setattr(notify.settings, "ALERT_NOTIFY_EMAIL_TO", "")

    assert await notify.send_alert_notification("端口扫描告警", "扫描发现高危端口", "high") is True
    url, payload = fake.calls[0]
    assert url == "https://open.feishu.cn/open-apis/bot/v2/hook/test"
    assert payload["msg_type"] == "text"
    assert "端口扫描告警" in payload["content"]["text"]
    assert "高" in payload["content"]["text"]  # 级别中文映射


async def test_generic_webhook_payload(monkeypatch):
    from app.services import notify

    fake = _FakeClient()
    monkeypatch.setattr(notify.httpx, "AsyncClient", lambda *a, **k: fake)
    monkeypatch.setattr(notify.settings, "ALERT_NOTIFY_WEBHOOK_URL", "https://ops.example/alert")
    monkeypatch.setattr(notify.settings, "ALERT_NOTIFY_WEBHOOK_TYPE", "generic")
    monkeypatch.setattr(notify.settings, "ALERT_NOTIFY_EMAIL_TO", "")

    assert await notify.send_alert_notification("合规告警", "未达标", "medium") is True
    url, payload = fake.calls[0]
    assert payload["title"] == "合规告警" and payload["severity"] == "medium"
    assert "content" in payload and "time" in payload


async def test_email_channel_calls_smtp(monkeypatch):
    from app.services import notify

    sent = []

    def fake_smtp(subject, body, to_list):  # to_thread 要求同步函数
        sent.append((subject, body, to_list))

    monkeypatch.setattr(notify, "_smtp_send", fake_smtp)
    monkeypatch.setattr(notify.settings, "ALERT_NOTIFY_WEBHOOK_URL", "")
    monkeypatch.setattr(notify.settings, "ALERT_NOTIFY_EMAIL_TO", "a@x.com, b@x.com")
    monkeypatch.setattr(notify.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(notify.settings, "SMTP_PORT", 465)
    monkeypatch.setattr(notify.settings, "SMTP_USERNAME", "u")
    monkeypatch.setattr(notify.settings, "SMTP_PASSWORD", "p")
    monkeypatch.setattr(notify.settings, "SMTP_FROM", "bt@x.com")

    assert await notify.send_alert_notification("邮件告警", "正文", "high") is True
    assert sent[0][0].startswith("[蓝队告警]")
    assert sent[0][2] == ["a@x.com", "b@x.com"]


async def test_webhook_failure_swallowed(monkeypatch):
    """webhook 抛异常 → 不向外抛，返回 False（告警主流程不受影响）。"""
    from app.services import notify

    class _BoomClient(_FakeClient):
        async def post(self, url, json=None):
            raise RuntimeError("网络不通")

    monkeypatch.setattr(notify.httpx, "AsyncClient", lambda *a, **k: _BoomClient())
    monkeypatch.setattr(notify.settings, "ALERT_NOTIFY_WEBHOOK_URL", "https://x/hook")
    monkeypatch.setattr(notify.settings, "ALERT_NOTIFY_EMAIL_TO", "")

    assert await notify.send_alert_notification("t", "c", "high") is False
