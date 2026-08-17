"""WebSocket 路由：/ws/chat/{channel_id}、/ws/notifications

- 认证：query 参数 ?token=<access_token>
- 权限：需 chat:view（审计员被拦在外）
- 心跳：客户端每 30s 发 {"type":"ping"} → 服务端回 {"type":"pong"}；90s 无心跳自动断开
- 消息：客户端发 {"type":"message", ...MessageCreate} → 持久化 + 广播
- /ws/notifications：需 training:agent:view（学员/分析师可见），服务端主动推送新课程等通知
"""
from fastapi import WebSocket, WebSocketDisconnect

from app.api.v1.channels import _get_channel, create_message
from app.core.dependencies import _has_permission
from app.core.security import decode_token
from app.db.session import AsyncSessionLocal
from app.models import Role, User
from app.schemas.chat import MessageCreate
from app.ws.manager import manager


def _auth_payload(token: str) -> dict | None:
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None
    return payload


def register_websocket(app) -> None:
    @app.websocket("/ws/notifications")
    async def ws_notifications(websocket: WebSocket):
        token = websocket.query_params.get("token", "") or websocket.cookies.get("access_token", "")
        payload = _auth_payload(token)
        if not payload:
            await websocket.close(code=4401)
            return

        async with AsyncSessionLocal() as session:
            user = await session.get(User, int(payload["sub"]))
            if not user or user.status not in ("active", "on_leave"):
                await websocket.close(code=4401)
                return
            user._role = await session.get(Role, user.role_id) if user.role_id else None
            perms = user._role.permissions if user._role else []
            if not _has_permission(perms, "training:agent:view"):
                await websocket.close(code=4403)
                return

            await manager.connect_global(user.id, user.real_name or user.username, websocket)
            try:
                while True:
                    raw = await websocket.receive_json()
                    if raw.get("type") == "ping":
                        manager.touch_global(user.id, websocket)
                        await websocket.send_json({"type": "pong"})
            except WebSocketDisconnect:
                pass
            finally:
                await manager.disconnect_global(user.id, websocket)
    @app.websocket("/ws/chat/{channel_id}")
    async def ws_chat(websocket: WebSocket, channel_id: int):
        # 认证：优先 ?token=（非浏览器客户端），否则同源 WebSocket 握手自动携带的 HttpOnly Cookie
        token = websocket.query_params.get("token", "") or websocket.cookies.get("access_token", "")
        payload = _auth_payload(token)
        if not payload:
            await websocket.close(code=4401)
            return

        async with AsyncSessionLocal() as session:
            user = await session.get(User, int(payload["sub"]))
            if not user or user.status not in ("active", "on_leave"):
                await websocket.close(code=4401)
                return
            user._role = await session.get(Role, user.role_id) if user.role_id else None
            perms = user._role.permissions if user._role else []
            if not _has_permission(perms, "chat:view"):
                await websocket.close(code=4403)
                return

            try:
                channel = await _get_channel(session, channel_id, user)
            except Exception:
                await websocket.close(code=4404)
                return

            name = user.real_name or user.username
            await manager.connect(channel_id, user.id, name, websocket)
            await manager.broadcast(channel_id, {"type": "system", "data": {"text": f"{name} 加入了频道"}})
            try:
                while True:
                    raw = await websocket.receive_json()
                    kind = raw.get("type")
                    if kind == "ping":
                        manager.touch(channel_id, user.id)
                        await websocket.send_json({"type": "pong"})
                    elif kind == "message":
                        try:
                            data = MessageCreate(**raw.get("data", {}))
                        except Exception:
                            continue
                        await create_message(session, user, channel, data)
            except WebSocketDisconnect:
                pass
            finally:
                await manager.disconnect(channel_id, user.id)
                await manager.broadcast(channel_id, {"type": "system", "data": {"text": f"{name} 离开了频道"}})
