"""训练课程发布通知：通过全局 WebSocket 推送在线学员端。

独立文件便于 API 端点 monkeypatch（测试不实际连接 WS）。
"""
import datetime as dt

from app.ws.manager import manager


async def push_course_published(course_id: int, name: str, scenario_count: int, published_at: dt.datetime | None = None) -> None:
    """向所有在线的 /ws/notifications 连接推送「新课程已发布」通知。"""
    await manager.send_global({
        "type": "training_course_published",
        "data": {
            "course_id": course_id,
            "name": name,
            "scenario_count": scenario_count,
            "published_at": published_at.isoformat() if published_at else None,
        },
    })
