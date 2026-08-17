"""AI 网关：DeepSeek 主通道 → Ollama 本地降级 → 提示语兜底（NFR-004）。

- 上下文：调用方传入同一会话最近 N 轮 messages，见 ai_conversations.context_messages。
- 安全：system prompt 限定蓝队防御角色；输入/输出由前端做 HTML 转义 + Markdown 白名单渲染。
"""
from typing import Any

import httpx

from app.core.config import settings

SYSTEM_PROMPT = (
    "你是一名网络安全蓝队防御专家，服务于企业安全运营团队。"
    "你的职责：威胁研判、日志分析、应急响应、加固建议、溯源报告。"
    "回答要求：专业、简洁、可执行，用中文；涉及代码时给出可直接使用的命令或代码片段；"
    "只讨论防御与合规场景，拒绝任何攻击破坏性指令。"
)


class AIUnavailableError(Exception):
    """当前通道不可用，交由上层尝试降级或兜底。"""


class AIGateway:
    """封装 DeepSeek / Ollama 的对话代理层。"""

    def __init__(
        self,
        deepseek_api_key: str | None = None,
        ollama_base_url: str | None = None,
        ollama_model: str | None = None,
    ):
        self._deepseek_key = deepseek_api_key if deepseek_api_key is not None else settings.DEEPSEEK_API_KEY
        self._ollama_base = ollama_base_url or settings.OLLAMA_BASE_URL
        self._ollama_model = ollama_model or settings.OLLAMA_MODEL

    def _build_messages(self, context: list[dict] | None, query: str) -> list[dict]:
        """system + 最近 N 轮上下文 + 当前问题。"""
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        if context:
            messages.extend([{"role": m["role"], "content": m["content"]} for m in context if m.get("role") in ("user", "assistant")])
        messages.append({"role": "user", "content": query})
        return messages

    async def chat(self, context: list[dict] | None, query: str, model_pref: str | None = None, timeout: float | None = None) -> tuple[str, str]:
        """逐级降级调用：DeepSeek → Ollama → 兜底提示。永远不抛出（NFR-004）。

        timeout 覆盖默认 AI_TIMEOUT_SECONDS（如 AI 生成长课程）。
        返回 (content, provider)，provider ∈ {deepseek, ollama, fallback}。
        """
        if model_pref and model_pref == "ollama":
            try:
                return await self._call_ollama(context, query, timeout), "ollama"
            except AIUnavailableError:
                pass
        else:
            try:
                return await self._call_deepseek(context, query, timeout), "deepseek"
            except AIUnavailableError:
                try:
                    return await self._call_ollama(context, query, timeout), "ollama"
                except AIUnavailableError:
                    pass
        return "（AI 服务暂不可用，请稍后再试。聊天功能不受影响。）", "fallback"

    async def _call_deepseek(self, context: list[dict] | None, query: str, timeout: float | None = None) -> str:
        if not self._deepseek_key:
            raise AIUnavailableError("DEEPSEEK_API_KEY 未配置")
        url = f"{settings.DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
        payload = {
            "model": settings.DEEPSEEK_MODEL,
            "messages": self._build_messages(context, query),
            "temperature": 0.3,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=timeout or settings.AI_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self._deepseek_key}", "Content-Type": "application/json"},
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            raise AIUnavailableError(f"deepseek 失败: {exc}") from exc

    async def _call_ollama(self, context: list[dict] | None, query: str, timeout: float | None = None) -> str:
        url = f"{self._ollama_base.rstrip('/')}/api/chat"
        payload = {
            "model": self._ollama_model,
            "messages": self._build_messages(context, query),
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=timeout or settings.AI_TIMEOUT_SECONDS) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                return resp.json()["message"]["content"]
        except Exception as exc:
            raise AIUnavailableError(f"ollama 失败: {exc}") from exc


def trim_history(context: list[dict] | None, max_rounds: int | None = None) -> list[dict]:
    """裁剪为最近 max_rounds 轮（user/assistant 对）。"""
    if not context:
        return []
    rounds = max_rounds or settings.AI_MAX_HISTORY_ROUNDS
    return context[-(rounds * 2):]


gateway = AIGateway()
