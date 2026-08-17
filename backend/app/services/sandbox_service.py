"""模拟沙箱：脚本化 Linux 终端 + 训练任务判定 + 判分。

零成本实现：不做真实容器，而是基于场景预置的「虚拟文件系统」与任务规则，
对常见蓝队命令（ls/cat/grep/iptables 等）做模拟响应，并自动判定解题步骤。
每个场景在 content 中定义：intro / files / tasks（含 solution 检查规则与分值）。
"""
import shlex

from app.models.training import TrainingScenario

# 模拟终端支持的常见命令
HELP_TEXT = """可用命令（模拟环境，仅供训练）：
  ls [目录]          列出目录
  cat <文件>         查看文件内容
  grep <模式> <文件> 在文件中查找
  head/tail <文件>   查看文件头/尾
  find <目录>        查找文件
  who / last         登录会话
  ps                 进程列表
  ss / netstat       网络连接
  ip a               网卡信息
  iptables -A INPUT -s <IP> -j DROP   封禁 IP
  echo <文本>        输出文本
  输入 Ctrl 组合不可用，直接敲命令按回车执行"""

# 危险命令：扣罚分并提示（模拟环境同样禁止真实破坏行为）
DANGEROUS = ("rm", "shutdown", "reboot", "mkfs", "format", "dd", "kill", "chmod 777", "sudo su")


def build_virtual_fs(files: dict) -> dict[str, dict]:
    """返回 {路径: {type: file, content: str}} 扁平映射；目录结构由 _ls 从路径推导。"""
    fs: dict[str, dict] = {}
    for path, content in (files or {}).items():
        p = path if path.startswith("/") else "/" + path
        fs[p] = {"type": "file", "content": content}
    return fs


def _normalize_dir(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    return path


def _ls(path: str, fs: dict) -> str:
    """列目录：从文件路径推导目录结构（仅一层）。"""
    path = path.rstrip("/")
    if not path:
        path = "/"
    # 收集直接子项
    dirs, files = set(), set()
    for p in fs:
        if p == "/":
            continue
        rel = p[1:] if p.startswith("/") else p
        parts = [x for x in rel.split("/") if x]
        if path == "/":
            dirs.add(parts[0])
        elif path in fs and fs[path]["type"] == "dir":
            # 匹配 path 前缀下的一级子项
            if p.startswith(path + "/"):
                rest = p[len(path) + 1:]
                first = rest.split("/")[0]
                if "/" in rest:
                    dirs.add(first)
                else:
                    files.add(first)
        else:
            if p.startswith(path + "/"):
                rest = p[len(path) + 1:]
                first = rest.split("/")[0]
                dirs.add(first) if "/" in rest else files.add(first)
    lines = [f"total 0", *[f"drwxr-xr-x  {d}" for d in sorted(dirs)], *[f"-rw-r--r--  {f}" for f in sorted(files)]]
    return "\n".join(lines) if len(lines) > 1 else f"ls: {path}: 没有那个文件或目录"


def _cat(path: str, fs: dict) -> str:
    path = path if path.startswith("/") else "/" + path
    node = fs.get(path)
    if not node or node["type"] != "file":
        return f"cat: {path}: 没有那个文件或目录"
    return node["content"]


def _grep(pattern: str, path: str, fs: dict) -> str:
    node = fs.get(path if path.startswith("/") else "/" + path)
    if not node or node["type"] != "file":
        return f"grep: {path}: 没有那个文件或目录"
    lines = [ln for ln in node["content"].splitlines() if pattern in ln]
    return "\n".join(lines) if lines else f"（在 {path} 中未找到包含 '{pattern}' 的内容）"


def _head_tail(path: str, n: int, fs: dict, tail: bool = False) -> str:
    content = _cat(path, fs)
    if content.startswith("cat:"):
        return content
    lines = content.splitlines()
    picked = lines[-n:] if tail else lines[:n]
    return "\n".join(picked)


def _dispatch(prog: str, args: list[str], fs: dict) -> str:
    joined = " ".join(args)
    if prog in ("help",):
        return HELP_TEXT
    if prog in ("ls",):
        return _ls(args[0] if args else "/", fs)
    if prog in ("cat",):
        return _cat(args[0], fs) if args else "usage: cat <文件>"
    if prog in ("grep",):
        return _grep(args[0], args[1], fs) if len(args) >= 2 else "usage: grep <模式> <文件>"
    if prog in ("head", "tail"):
        n = 10
        if len(args) >= 2 and args[0].startswith("-") and args[0][1:].isdigit():
            n = int(args[0][1:])
            args = args[1:]
        return _head_tail(args[0], n, fs, tail=(prog == "tail")) if args else f"usage: {prog} [-n] <文件>"
    if prog in ("who", "last"):
        return "root     pts/0    2026-08-13 09:12   (10.0.0.2)\nadmin    pts/1    2026-08-13 03:40   (203.0.113.5)  <- 可疑来源"
    if prog in ("ps",):
        return "  PID  USER     COMMAND\n  101  root     nginx: master\n  102  nginx    nginx: worker\n  345  mysql    mysqld\n 2333  www      /tmp/.x (可疑进程，建议核查)"
    if prog in ("ss", "netstat"):
        return "State     Local Addr:Port     Peer Addr:Port\nESTAB    10.0.0.10:22         203.0.113.5:51243\nESTAB    10.0.0.10:3306       10.0.0.20:40123\nLISTEN   10.0.0.10:80         *:*"
    if prog in ("ip",):
        return "1: lo: <LOOPBACK> mtu 65536\n    inet 127.0.0.1/8 scope host lo\n2: eth0: <BROADCAST> mtu 1500\n    inet 10.0.0.10/24 brd 10.0.0.255 scope global eth0"
    if prog in ("find",):
        return "find 在模拟环境中仅列出日志目录：\n/var/log/auth.log\n/var/log/syslog\n/etc/passwd\n/var/log/nginx/access.log"
    if prog in ("iptables",):
        if "-L" in args or "--list" in args:
            return "Chain INPUT (policy ACCEPT)\ntarget  prot  source         destination\nDROP    all   203.0.113.5    anywhere\nACCEPT  all   anywhere      anywhere\n\nChain OUTPUT (policy ACCEPT)\nACCEPT  all   anywhere      anywhere"
        ip = None
        if "-s" in args:
            idx = args.index("-s")
            if idx + 1 < len(args):
                ip = args[idx + 1]
        if ip and "-j" in args and "DROP" in args:
            return f"iptables 规则已添加：拒绝来自 {ip} 的所有入站连接（模拟环境已生效）"
        return "usage: iptables -A INPUT -s <IP> -j DROP 或 iptables -L"
    if prog in ("echo",):
        return " ".join(args)
    return f"bash: {prog}: command not found（训练沙箱仅模拟常用命令，输入 help 查看可用命令）"


def _matches(task: dict, prog: str, joined_args: str, output: str = "") -> bool:
    """任务命中规则：check.cmd 匹配命令；pattern/args 匹配参数行；output_contains 匹配命令输出。"""
    check = task.get("check") or {}
    if check.get("cmd") and check["cmd"] != prog:
        return False
    if check.get("output_contains"):
        return check["output_contains"] in output
    if check.get("pattern"):
        if check["pattern"] not in joined_args:
            return False
    if check.get("args"):
        if check["args"] not in joined_args:
            return False
    return True


def create_initial_state(scenario: TrainingScenario) -> dict:
    content = scenario.content or {}
    return {
        "completed_tasks": [],
        "points": 0,
        "penalty": 0,
        "commands": 0,
    }


def run_command(scenario: TrainingScenario, state: dict, command: str) -> dict:
    """执行一条沙箱命令，返回输出与任务/积分变化。"""
    content = scenario.content or {}
    fs = build_virtual_fs(content.get("files") or {})
    tasks = content.get("tasks") or []
    command = (command or "").strip()
    state.setdefault("completed_tasks", [])
    state.setdefault("points", 0)
    state.setdefault("penalty", 0)
    state["commands"] = state.get("commands", 0) + 1

    output_lines: list[str] = []
    penalty = 0
    if command:
        try:
            argv = shlex.split(command)
        except ValueError:
            argv = command.split()
        prog = argv[0].lower() if argv else ""
        args = argv[1:]
        joined = " ".join(args)

        if not prog:
            output_lines.append("")
        elif prog in DANGEROUS or joined.startswith("rm "):
            penalty = scenario.penalty_points or 5
            output_lines.append(f"⚠️ 检测到危险命令「{command}」，训练分 -{penalty}（真实环境中切勿执行破坏性操作）")
        else:
            output_lines.append(_dispatch(prog, args, fs))
    else:
        output_lines.append("")

    # 任务判定（output_contains 类任务基于命令输出判定）
    newly = []
    out_text = "\n".join(output_lines)
    for task in tasks:
        if task.get("id") in state["completed_tasks"]:
            continue
        if _matches(task, prog, joined, out_text):
            state["completed_tasks"].append(task["id"])
            pts = int(task.get("points", 10))
            state["points"] += pts
            newly.append({"id": task["id"], "title": task.get("title", ""), "points": pts})

    state["penalty"] += penalty
    net = max(0, state["points"] - state["penalty"])

    return {
        "output": "\n".join(output_lines),
        "completed_tasks": state["completed_tasks"],
        "points": state["points"],
        "penalty": state["penalty"],
        "net_score": net,
        "newly_completed": newly,
        "task_count": len(tasks),
        "all_completed": len(tasks) > 0 and len(state["completed_tasks"]) == len(tasks),
    }


def calc_final_score(scenario: TrainingScenario, state: dict) -> tuple[int, str]:
    """提交结算：返回 (分数, 状态)。全部任务完成且无扣分为 completed，否则 failed。"""
    content = scenario.content or {}
    tasks = content.get("tasks") or []
    done = set(state.get("completed_tasks", []))
    all_done = len(tasks) > 0 and all(t.get("id") in done for t in tasks)
    score = max(0, state.get("points", 0) - state.get("penalty", 0))
    if all_done:
        return score, "completed"
    return score, "failed"
