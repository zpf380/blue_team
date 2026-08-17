"""沙箱模拟引擎单元测试：命令模拟 / 任务判定 / 判分 / 扣分（不依赖数据库）。"""
from app.models import TrainingScenario
from app.services.sandbox_service import calc_final_score, create_initial_state, run_command


def _scenario() -> TrainingScenario:
    return TrainingScenario(
        title="日志分析",
        content={
            "intro": "排查认证日志",
            "files": {
                "/var/log/auth.log": "Failed password for root from 203.0.113.5 port 22\nAccepted password for root from 10.0.0.2",
            },
            "tasks": [
                {"id": "t1", "title": "查看认证日志", "points": 10, "check": {"cmd": "cat", "args": "/var/log/auth.log"}},
                {"id": "t2", "title": "定位攻击源", "points": 20, "check": {"cmd": "grep", "pattern": "203.0.113.5"}},
                {"id": "t3", "title": "封禁 IP", "points": 30, "check": {"cmd": "iptables", "pattern": "203.0.113.5"}},
            ],
        },
        points=60,
        penalty_points=5,
    )


def test_cat_and_ls_virtual_fs():
    sc = _scenario()
    r = run_command(sc, create_initial_state(sc), "ls /")
    assert "var" in r["output"]
    r = run_command(sc, create_initial_state(sc), "cat /var/log/auth.log")
    assert "Failed password" in r["output"]
    assert "cat: /etc/shadow: 没有那个文件或目录" in run_command(sc, create_initial_state(sc), "cat /etc/shadow")["output"]


def test_task_progression_and_scoring():
    sc = _scenario()
    state = create_initial_state(sc)
    r = run_command(sc, state, "cat /var/log/auth.log")
    assert r["completed_tasks"] == ["t1"]
    assert r["points"] == 10
    assert not r["all_completed"]

    r = run_command(sc, state, "grep '203.0.113.5' /var/log/auth.log")
    assert r["completed_tasks"] == ["t1", "t2"]
    assert r["points"] == 30

    r = run_command(sc, state, "iptables -A INPUT -s 203.0.113.5 -j DROP")
    assert r["completed_tasks"] == ["t1", "t2", "t3"]
    assert r["points"] == 60
    assert r["all_completed"]

    score, status = calc_final_score(sc, state)
    assert (score, status) == (60, "completed")


def test_dangerous_command_penalty():
    sc = _scenario()
    state = create_initial_state(sc)
    # 先完成两个任务拿 30 分
    run_command(sc, state, "cat /var/log/auth.log")
    run_command(sc, state, "grep '203.0.113.5' /var/log/auth.log")
    r = run_command(sc, state, "rm -rf /")
    assert r["penalty"] == 5
    assert r["net_score"] == 25
    # 扣分不新增任务
    assert len(r["completed_tasks"]) == 2


def test_output_based_check():
    sc = _scenario()
    sc.content = {
        "tasks": [
            {"id": "t1", "title": "确认异常连接", "points": 15, "check": {"cmd": "ss", "output_contains": "203.0.113.5"}},
        ]
    }
    state = create_initial_state(sc)
    # 命令参数不含 IP，但输出含 IP → 命中
    r = run_command(sc, state, "ss -antp")
    assert r["completed_tasks"] == ["t1"]
    assert r["points"] == 15


def test_wrong_command_no_match():
    sc = _scenario()
    state = create_initial_state(sc)
    r = run_command(sc, state, "ls /etc")
    assert r["completed_tasks"] == []
    assert r["points"] == 0
    assert not r["all_completed"]
