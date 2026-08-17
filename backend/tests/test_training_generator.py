"""AI 训练课程生成器单元测试（mock AI 网关，不触网不碰库）。"""
import copy
import json

import pytest

from app.services.ai_gateway import gateway
from app.services.training_generator import (
    CourseGenerationError,
    build_course_query,
    extract_json,
    generate_course,
    validate_course,
)

VALID_COURSE = {
    "name": "日志分析强化",
    "difficulty": 1,
    "description": "训练学员快速定位异常登录并封禁。",
    "scenarios": [
        {
            "title": "暴力破解处置",
            "description": "分析认证日志。",
            "points": 50,
            "penalty_points": 5,
            "time_limit": 30,
            "order_index": 1,
            "content": {
                "intro": "请分析 /var/log/auth.log 并定位攻击来源。",
                "files": {
                    "/var/log/auth.log": "Aug 13 02:11:07 login sshd[1042]: Failed password for root from 203.0.113.5 port 51243 ssh2\n",
                    "/etc/passwd": "root:x:0:0:root:/root:/bin/bash\n",
                },
                "tasks": [
                    {"id": "t1", "title": "查看认证日志", "points": 10, "hint": "cat /var/log/auth.log", "check": {"cmd": "cat", "args": "/var/log/auth.log"}},
                    {"id": "t2", "title": "定位攻击 IP", "points": 15, "hint": "grep '203.0.113.5' /var/log/auth.log", "check": {"cmd": "grep", "pattern": "203.0.113.5"}},
                    {"id": "t3", "title": "封禁攻击 IP", "points": 25, "hint": "iptables -A INPUT -s 203.0.113.5 -j DROP", "check": {"cmd": "iptables", "pattern": "203.0.113.5"}},
                ],
            },
        }
    ],
}


@pytest.mark.asyncio
async def test_generate_course_valid(monkeypatch):
    async def fake_chat(context, query, model_pref=None, timeout=None):
        assert timeout == 90.0  # 使用课程生成专用超时
        assert "日志分析" in query and "iptables" in query
        return f"```json\n{json.dumps(VALID_COURSE, ensure_ascii=False)}\n```", "deepseek"

    monkeypatch.setattr(gateway, "chat", fake_chat)
    course = await generate_course("日志分析")
    assert course["name"] == "日志分析强化"
    assert len(course["scenarios"]) == 1
    assert course["scenarios"][0]["points"] == 50


@pytest.mark.asyncio
async def test_generate_course_fallback_raises(monkeypatch):
    async def fake_chat(context, query, model_pref=None, timeout=None):
        return "（AI 服务暂不可用，请稍后再试。聊天功能不受影响。）", "fallback"

    monkeypatch.setattr(gateway, "chat", fake_chat)
    with pytest.raises(CourseGenerationError, match="AI 服务暂不可用"):
        await generate_course("日志分析")


@pytest.mark.asyncio
async def test_generate_course_invalid_json_raises(monkeypatch):
    async def fake_chat(context, query, model_pref=None, timeout=None):
        return "抱歉，我无法生成 JSON。", "deepseek"

    monkeypatch.setattr(gateway, "chat", fake_chat)
    with pytest.raises(CourseGenerationError):
        await generate_course("日志分析")


def test_extract_json_fence_and_trailing():
    text = "好的，结果如下：\n```json\n" + json.dumps(VALID_COURSE, ensure_ascii=False) + "\n```\n以上为最终结果。"
    obj = extract_json(text)
    assert obj["name"] == "日志分析强化"


def test_extract_json_brace_in_string_and_escape():
    text = '{"name": "a{b\\\\c}", "scenarios": []} trailing text'
    obj = extract_json(text)
    assert obj == {"name": "a{b\\c}", "scenarios": []}


def test_extract_json_no_json():
    with pytest.raises(CourseGenerationError):
        extract_json("完全没有 JSON 的文本")


def test_extract_json_unclosed():
    with pytest.raises(CourseGenerationError):
        extract_json('{"name": "x", "scenarios": [')


def test_validate_course_ok():
    validate_course(copy.deepcopy(VALID_COURSE))


def test_validate_course_missing_intro():
    bad = copy.deepcopy(VALID_COURSE)
    bad["scenarios"][0]["content"]["intro"] = ""
    with pytest.raises(CourseGenerationError, match="content.intro"):
        validate_course(bad)


def test_validate_course_cmd_whitelist():
    bad = copy.deepcopy(VALID_COURSE)
    bad["scenarios"][0]["content"]["tasks"][2]["check"]["cmd"] = "rm"
    with pytest.raises(CourseGenerationError, match="沙箱支持命令集"):
        validate_course(bad)


def test_validate_course_points_mismatch():
    bad = copy.deepcopy(VALID_COURSE)
    bad["scenarios"][0]["points"] = 99
    with pytest.raises(CourseGenerationError, match="不等于"):
        validate_course(bad)


def test_validate_course_scenario_count():
    bad = copy.deepcopy(VALID_COURSE)
    bad["scenarios"] = []
    with pytest.raises(CourseGenerationError, match="场景数量"):
        validate_course(bad)


def test_validate_course_dup_task_id():
    bad = copy.deepcopy(VALID_COURSE)
    bad["scenarios"][0]["content"]["tasks"][1]["id"] = "t1"
    with pytest.raises(CourseGenerationError, match="重复"):
        validate_course(bad)


def test_validate_course_missing_check():
    bad = copy.deepcopy(VALID_COURSE)
    bad["scenarios"][0]["content"]["tasks"][0]["check"] = {}
    with pytest.raises(CourseGenerationError, match="check.cmd"):
        validate_course(bad)


def test_build_course_query_has_constraints():
    q = build_course_query("日志分析")
    assert "iptables" in q
    assert "JSON" in q
    assert "output_contains" in q
