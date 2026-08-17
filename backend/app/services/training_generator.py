"""AI 训练课程生成器：按主题调用 AI 网关生成完整智能体实训课程。

生成的课程结构与手工录入一致（TrainingAgent + TrainingScenario.content JSON）：
含 1~3 个场景 × 2~4 个任务，任务 check 规则限定在沙箱支持的命令集内，
确保生成结果能在模拟沙箱中实际可判分。
"""
import json
import re
from typing import Any

from app.core.config import settings
from app.services.ai_gateway import gateway

# 沙箱支持的模拟命令（与 sandbox_service.HELP_TEXT 一致，check.cmd 白名单）
ALLOWED_COMMANDS = (
    "help", "ls", "cat", "grep", "head", "tail", "find",
    "who", "last", "ps", "ss", "netstat", "ip", "iptables", "echo",
)


class CourseGenerationError(Exception):
    """AI 生成课程失败（含可读中文原因），由 API 层转 40001。"""


def build_course_query(topic: str) -> str:
    """构造生成请求的用户消息：system 复用网关蓝队 PROMPT，严格 JSON 指令全放这里。"""
    allowed = "、".join(ALLOWED_COMMANDS)
    return f"""请为网络安全蓝队实训生成一门《{topic}》训练课程。仅输出一个 JSON 对象，不要输出任何其他文字，不要用 Markdown 围栏。JSON 结构固定如下：
{{
  "name": "课程名称（不超过 20 字，贴合主题）",
  "difficulty": 1,
  "description": "课程简介（一段话）",
  "scenarios": [
    {{
      "title": "场景标题",
      "description": "场景简述",
      "points": 50,
      "penalty_points": 5,
      "time_limit": 30,
      "order_index": 1,
      "content": {{
        "intro": "场景引言/任务说明（给学员的操作步骤提示）",
        "files": {{ "/var/log/auth.log": "日志内容…", "/etc/passwd": "文件内容…" }},
        "tasks": [
          {{
            "id": "t1",
            "title": "任务标题",
            "points": 10,
            "hint": "提示命令，如 cat /var/log/auth.log",
            "check": {{"cmd": "cat", "args": "/var/log/auth.log"}}
          }}
        ]
      }}
    }}
  ]
}}

严格要求：
1. 场景数量 1~3 个，每个场景任务 2~4 个。
2. 每个任务 check.cmd 必须是以下命令之一：{allowed}。
3. check 三选一或组合：args/pattern 匹配命令行参数子串，output_contains 匹配命令输出子串（若指定 output_contains，必须保证该文本确实出现在对应命令在 files 中的输出内容里）。
4. content.files 的 key 必须以 / 开头，文件内容要真实可查，且包含与任务相关的线索（如日志中的攻击 IP、异常进程、可疑连接）。
5. 每个场景 points = 该场景所有任务 points 之和；任务分值合理递增。
6. 全部为防御/分析操作（查看日志、定位攻击、封禁 IP 等），禁止任何攻击破坏性操作。
7. 内容宁少勿编，不要捏造场景中用不到的复杂内容。输出必须是合法 JSON。"""


def _brace_balanced_extract(text: str) -> dict[str, Any]:
    """兜底：手工扫描首个 { 与配对的 }，跳过字符串与转义，取出 JSON 子串解析。"""
    start = text.find("{")
    if start == -1:
        raise CourseGenerationError("AI 输出中未找到 JSON 内容")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if esc:
            esc = False
            continue
        if in_str:
            if ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError as exc:
                    raise CourseGenerationError(f"AI 返回的不是合法 JSON：{exc}") from exc
    raise CourseGenerationError("AI 返回的 JSON 不完整（括号未闭合）")


def extract_json(text: str) -> dict[str, Any]:
    """从 AI 输出中提取首个完整 JSON 对象：去围栏 → raw_decode → 括号平衡兜底。"""
    if not text or not text.strip():
        raise CourseGenerationError("AI 返回为空")
    stripped = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.S)
    if fence:
        stripped = fence.group(1).strip()
    start = stripped.find("{")
    if start != -1:
        try:
            obj, _ = json.JSONDecoder().raw_decode(stripped[start:])
            return obj
        except json.JSONDecodeError:
            pass
    return _brace_balanced_extract(stripped)


def _validate_task(t: dict, seen_ids: set) -> None:
    if not isinstance(t, dict):
        raise CourseGenerationError("任务结构非法：任务应为对象")
    tid = t.get("id")
    if not tid or tid in seen_ids:
        raise CourseGenerationError("任务 id 缺失或重复")
    seen_ids.add(tid)
    if not str(t.get("title") or "").strip():
        raise CourseGenerationError(f"任务「{tid}」标题不能为空")
    try:
        t["points"] = int(t.get("points", 0))
    except (TypeError, ValueError):
        raise CourseGenerationError(f"任务「{tid}」分值必须为数字")
    check = t.get("check")
    if not isinstance(check, dict) or not check.get("cmd"):
        raise CourseGenerationError(f"任务「{tid}」缺少 check.cmd")
    cmd = str(check.get("cmd")).strip()
    if cmd not in ALLOWED_COMMANDS:
        raise CourseGenerationError(f"任务「{tid}」check.cmd「{cmd}」不在沙箱支持命令集内")
    check["cmd"] = cmd
    if not (check.get("pattern") or check.get("args") or check.get("output_contains")):
        raise CourseGenerationError(f"任务「{tid}」需指定 pattern/args/output_contains 之一")


def _validate_scenario(sc: dict, idx: int) -> None:
    if not isinstance(sc, dict):
        raise CourseGenerationError(f"第 {idx} 个场景结构非法")
    title = str(sc.get("title") or "").strip()
    if not title:
        raise CourseGenerationError(f"第 {idx} 个场景标题不能为空")
    content = sc.get("content")
    if not isinstance(content, dict) or not str(content.get("intro") or "").strip():
        raise CourseGenerationError(f"场景「{title}」缺少 content.intro")
    files = content.get("files")
    if not isinstance(files, dict) or not files:
        raise CourseGenerationError(f"场景「{title}」content.files 必须为非空对象")
    for path in files:
        if not str(path).startswith("/"):
            raise CourseGenerationError(f"场景「{title}」文件路径必须以 / 开头：{path}")
    tasks = content.get("tasks")
    if not isinstance(tasks, list) or not 2 <= len(tasks) <= 4:
        raise CourseGenerationError(f"场景「{title}」任务应为 2~4 个，实际 {len(tasks) if isinstance(tasks, list) else '非列表'}")
    seen_ids: set = set()
    points_sum = 0
    for t in tasks:
        _validate_task(t, seen_ids)
        points_sum += t["points"]
    try:
        sc["points"] = int(sc.get("points", 0))
    except (TypeError, ValueError):
        raise CourseGenerationError(f"场景「{title}」分值必须为数字")
    if sc["points"] != points_sum:
        raise CourseGenerationError(f"场景「{title}」分值({sc['points']})不等于任务分值之和({points_sum})")
    for key in ("penalty_points", "time_limit"):
        if sc.get(key) is not None:
            try:
                sc[key] = int(sc[key])
            except (TypeError, ValueError):
                raise CourseGenerationError(f"场景「{title}」{key} 必须为数字")


def validate_course(course: dict) -> None:
    """结构校验：不合法抛 CourseGenerationError 并给具体原因；校验通过则已规范化各数值字段。"""
    if not isinstance(course, dict):
        raise CourseGenerationError("AI 返回结构非法：顶层应为 JSON 对象")
    name = str(course.get("name") or "").strip()
    if not name:
        raise CourseGenerationError("课程名称不能为空")
    course["name"] = name
    try:
        course["difficulty"] = int(course.get("difficulty", 1))
    except (TypeError, ValueError):
        raise CourseGenerationError("课程难度必须为数字")
    scenarios = course.get("scenarios")
    if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 3:
        count = len(scenarios) if isinstance(scenarios, list) else "非列表"
        raise CourseGenerationError(f"场景数量应为 1~3 个，实际 {count}")
    for i, sc in enumerate(scenarios, start=1):
        _validate_scenario(sc, i)


async def generate_course(topic: str) -> dict:
    """按主题调用 AI 网关生成并校验课程；失败抛 CourseGenerationError。"""
    query = build_course_query(topic)
    content, provider = await gateway.chat(None, query, timeout=settings.AI_COURSE_TIMEOUT_SECONDS)
    if provider == "fallback":
        raise CourseGenerationError("AI 服务暂不可用，请稍后再试")
    course = extract_json(content)
    validate_course(course)
    return course
