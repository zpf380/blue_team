"""AI 网关降级逻辑单测（不依赖外部服务与数据库）。"""
import pytest

from app.services.ai_gateway import AIGateway, trim_history


@pytest.mark.asyncio
async def test_fallback_when_deepseek_unconfigured_and_ollama_down():
    """无 DeepSeek Key + Ollama 不可达 → 兜底提示（NFR-004），不抛出。"""
    gw = AIGateway(deepseek_api_key="", ollama_base_url="http://127.0.0.1:1", ollama_model="llama3")
    content, provider = await gw.chat([], "hello")
    assert provider == "fallback"
    assert "AI 服务暂不可用" in content


@pytest.mark.asyncio
async def test_forced_ollama_down_returns_fallback():
    gw = AIGateway(deepseek_api_key="fake-key", ollama_base_url="http://127.0.0.1:1")
    content, provider = await gw.chat([], "hi", model_pref="ollama")
    assert provider == "fallback"
    assert content


@pytest.mark.asyncio
async def test_ollama_down_falls_back_after_deepseek():
    """DeepSeek 有 key 但 Ollama 作为降级通道也失败 → fallback。"""
    gw = AIGateway(deepseek_api_key="fake-key", ollama_base_url="http://127.0.0.1:1")
    _, provider = await gw.chat([], "hi")
    assert provider == "fallback"


def test_trim_history_keeps_last_rounds():
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(20)]
    trimmed = trim_history(history, max_rounds=5)
    assert len(trimmed) == 10
    assert trimmed[0]["content"] == "m10"


def test_build_messages_includes_system_prompt_and_query():
    gw = AIGateway()
    messages = gw._build_messages([{"role": "user", "content": "ctx"}], "问题")
    assert messages[0]["role"] == "system"
    assert "蓝队" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "问题"}
