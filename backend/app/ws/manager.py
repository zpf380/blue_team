"""WebSocket 连接管理（单机内存直推；多机可扩展 Redis Pub/Sub）。

连接表：channel_id -> user_id -> ConnectionInfo。
"""
import asyncio
import datetime as dt
import time
from dataclasses import dataclass, field

from fastapi import WebSocket


@dataclass
class ConnectionInfo:
    websocket: WebSocket
    username: str
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


class ConnectionManager:
    def __init__(self) -> None:
        self._channels: dict[int, dict[int, ConnectionInfo]] = {}
        # 全局通知连接（如 /ws/notifications）：user_id -> 该用户所有标签页连接
        self._globals: dict[int, list[ConnectionInfo]] = {}

    async def connect(self, channel_id: int, user_id: int, username: str, ws: WebSocket) -> None:
        await ws.accept()
        self._channels.setdefault(channel_id, {})[user_id] = ConnectionInfo(websocket=ws, username=username)

    async def disconnect(self, channel_id: int, user_id: int) -> None:
        conns = self._channels.get(channel_id)
        if conns:
            conns.pop(user_id, None)
            if not conns:
                self._channels.pop(channel_id, None)

    def touch(self, channel_id: int, user_id: int) -> None:
        conn = self._channels.get(channel_id, {}).get(user_id)
        if conn:
            conn.last_seen = time.time()

    def connected_users(self, channel_id: int) -> list[int]:
        return list(self._channels.get(channel_id, {}).keys())

    async def broadcast(self, channel_id: int, message: dict, exclude_user_id: int | None = None) -> None:
        """向频道内所有在线连接推送消息，逐个容错。"""
        for uid, conn in list(self._channels.get(channel_id, {}).items()):
            if exclude_user_id is not None and uid == exclude_user_id:
                continue
            try:
                await conn.websocket.send_json(message)
            except Exception:
                # 单连接失败不影响其他连接；由心跳清扫统一回收
                continue

    async def send_to_user(self, user_id: int, message: dict) -> None:
        """向该用户所有连接推送（用于 @提及 / 私聊等）。"""
        for conns in self._channels.values():
            conn = conns.get(user_id)
            if not conn:
                continue
            try:
                await conn.websocket.send_json(message)
            except Exception:
                continue

    # ---------- 全局通知连接（/ws/notifications） ----------
    async def connect_global(self, user_id: int, username: str, ws: WebSocket) -> None:
        await ws.accept()
        self._globals.setdefault(user_id, []).append(ConnectionInfo(websocket=ws, username=username))

    async def disconnect_global(self, user_id: int, ws: WebSocket) -> None:
        conns = self._globals.get(user_id)
        if not conns:
            return
        for i, conn in enumerate(conns):
            if conn.websocket is ws:
                conns.pop(i)
                break
        if not conns:
            self._globals.pop(user_id, None)

    def touch_global(self, user_id: int, ws: WebSocket) -> None:
        for conn in self._globals.get(user_id, []):
            if conn.websocket is ws:
                conn.last_seen = time.time()
                break

    async def send_global(self, message: dict) -> None:
        """向所有在线全局通知连接广播（逐连接容错，单连接失败不影响其他）。"""
        for uid, conns in list(self._globals.items()):
            for conn in conns:
                try:
                    await conn.websocket.send_json(message)
                except Exception:
                    continue

    async def sweep_stale(self, timeout_seconds: float = 90.0) -> None:
        """心跳清扫：长时间未 ping 的连接视为断线。"""
        now = time.time()
        for channel_id, conns in list(self._channels.items()):
            for uid, conn in list(conns.items()):
                if now - conn.last_seen > timeout_seconds:
                    try:
                        await conn.websocket.close()
                    except Exception:
                        pass
                    conns.pop(uid, None)
            if not conns:
                self._channels.pop(channel_id, None)
        for uid, conns in list(self._globals.items()):
            for conn in list(conns):
                if now - conn.last_seen > timeout_seconds:
                    try:
                        await conn.websocket.close()
                    except Exception:
                        pass
                    conns.remove(conn)
            if not conns:
                self._globals.pop(uid, None)


manager = ConnectionManager()


async def heartbeat_loop(interval: float = 30.0, timeout: float = 90.0) -> None:
    """后台心跳清扫任务（app 启动时挂起）。"""
    while True:
        await asyncio.sleep(interval)
        await manager.sweep_stale(timeout)
