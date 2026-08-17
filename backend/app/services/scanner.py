"""真实 nmap 扫描执行器：编排 / XML 解析 / 风险推导 / 状态落地。

设计要点：
- `_run_nmap` 是唯一的子进程边界，测试通过 monkeypatch 它注入假扫描结果。
- 后台任务用进程内 asyncio.create_task（单机 demo 足够）；将来升级 Redis 队列
  只需替换 `launch_scan` 实现，API / 前端零改动。
- executor 使用独立 AsyncSessionLocal，绝不复用请求会话（请求结束即关闭）。
"""
import asyncio
import datetime as dt
import ipaddress
import xml.etree.ElementTree as ET

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models import Alert, Device, IPAllocation, NetworkDiscovery, ScanReport
from app.services.notify import notify_alert_task

# 模块级持有后台任务引用，防止协程被 GC；done 后自动移除
# （scan 与 discovery 分开持引用，避免 report_id / discovery_id 自增撞 key 互相覆盖）
_active_scan_tasks: dict[int, asyncio.Task] = {}
_active_discovery_tasks: dict[int, asyncio.Task] = {}

# 全局并发信号量：限制同时在跑的 nmap 子进程（扫描 + 发现共享），
# 防高频触发扫描/发现把服务器资源打满。Python 3.10+ 惰性绑定事件循环，
# 并发未超上限时串行 acquire 不创建 waiter，跨测试/调用方事件循环安全。
SCAN_SEM = asyncio.Semaphore(settings.SCAN_MAX_CONCURRENT)

# 常见高危/暴露端口 → 静态服务风险映射（真实开放端口 × 风险规则，非 NSE 脚本）
PORT_VULN_MAP: dict[int, dict] = {
    6379: {"name": "Redis 未授权访问", "severity": "critical", "cve": "CVE-2022-0543"},
    3306: {"name": "MySQL 服务暴露", "severity": "high", "cve": None},
    3389: {"name": "RDP 远程桌面暴露", "severity": "high", "cve": None},
    23: {"name": "Telnet 明文协议暴露", "severity": "high", "cve": None},
    445: {"name": "SMB 服务暴露", "severity": "high", "cve": "CVE-2020-0796"},
    1433: {"name": "SQL Server 服务暴露", "severity": "high", "cve": None},
    5432: {"name": "PostgreSQL 服务暴露", "severity": "medium", "cve": None},
    5900: {"name": "VNC 服务暴露", "severity": "high", "cve": None},
    9200: {"name": "Elasticsearch 服务暴露", "severity": "medium", "cve": None},
    8080: {"name": "备用 Web 端口暴露", "severity": "medium", "cve": None},
    8000: {"name": "备用 Web 端口暴露", "severity": "medium", "cve": None},
    22: {"name": "SSH 服务暴露", "severity": "low", "cve": None},
    80: {"name": "HTTP 服务暴露", "severity": "low", "cve": None},
    443: {"name": "HTTPS 服务暴露", "severity": "low", "cve": None},
}
_SEVERITY_WEIGHT = {"critical": 6, "high": 4, "medium": 3, "low": 2, "info": 1}


def launch_scan(report_id: int, target_ip: str, ports: int | None = None) -> None:
    """在调用方事件循环上创建后台扫描任务并持有引用。"""
    task = asyncio.create_task(execute_scan(report_id, target_ip, ports or settings.NMAP_TOP_PORTS))
    _active_scan_tasks[report_id] = task
    task.add_done_callback(lambda _t: _active_scan_tasks.pop(report_id, None))


async def execute_scan(report_id: int, target_ip: str, ports: int) -> None:
    """执行一次完整扫描：pending → running → completed / failed。"""
    async with AsyncSessionLocal() as session:
        r = await session.get(ScanReport, report_id)
        if not r:
            return
        r.scan_status = "running"
        r.summary = f"目标 {target_ip} 扫描进行中…"
        await session.commit()

    try:
        async with SCAN_SEM:
            rc, stdout = await _run_nmap(target_ip, ports, settings.NMAP_VERSION_DETECT)
        open_ports = _parse_nmap_xml(stdout)
        vulns = _derive_vulnerabilities(open_ports)
        risk = _compute_risk_score(open_ports, vulns)
        scan_data = {
            "target_ip": target_ip,
            "open_ports": open_ports,
            "vulnerabilities": vulns,
            "risk_score": risk,
            "scanned_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "nmap_exit": rc,
        }
        summary = f"目标 {target_ip}：发现开放端口 {len(open_ports)} 个、风险 {len(vulns)} 项，风险评分 {risk}。"
        alert = None
        async with AsyncSessionLocal() as session:
            r = await session.get(ScanReport, report_id)
            if r:
                r.scan_data, r.risk_score, r.summary, r.scan_status = scan_data, risk, summary, "completed"
            # 自动告警：评分达到阈值即产生告警并触发外部通知（扫描是最大风险来源，必须开箱即用）
            # 去重：同 target_ip+alert_type 且未解决（open/acknowledged）且在去重窗口内 → 跳过，防重复扫描刷屏
            if risk >= settings.ALERT_RISK_THRESHOLD:
                critical = any(v.get("severity") == "critical" for v in vulns)
                alert_type = "intrusion" if critical else "abnormal"
                dup_cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=settings.ALERT_DEDUP_HOURS)
                dup = await session.execute(
                    select(Alert.id).where(
                        Alert.target_ip == target_ip,
                        Alert.alert_type == alert_type,
                        Alert.status.in_(("open", "acknowledged")),
                        Alert.created_at >= dup_cutoff,
                    ).limit(1)
                )
                if dup.scalar_one_or_none() is None:
                    alert = Alert(
                        alert_type=alert_type,
                        severity="critical" if risk >= 90 else "high",
                        title=f"扫描发现高风险：{target_ip}（评分 {risk}）",
                        description=f"{summary}\n主要风险：{('、'.join(str(v.get('name', '')) for v in vulns[:8])) if vulns else '开放高危端口'}",
                        target_ip=target_ip,
                    )
                    session.add(alert)
                    await session.flush()
            await session.commit()
        if alert is not None:
            # 后台通知，不阻塞信号量释放 / 后续扫描排队
            asyncio.create_task(notify_alert_task(alert.id, alert.title, alert.description or "", alert.severity))
    except asyncio.TimeoutError:
        await _mark_failed(report_id, f"扫描超时（>{settings.NMAP_TIMEOUT_SECONDS}s）")
    except Exception as e:  # noqa: BLE001 —— 后台任务兜底，任何异常都落地为 failed
        await _mark_failed(report_id, str(e)[:500])


async def _mark_failed(report_id: int, msg: str) -> None:
    async with AsyncSessionLocal() as session:
        r = await session.get(ScanReport, report_id)
        if r:
            r.scan_status, r.error = "failed", msg
            await session.commit()


def _build_nmap_cmd(target_ip: str, ports: int, service_detection: bool) -> list[str]:
    """构造 nmap 命令行（纯函数，便于单测断言参数拼接）。"""
    cmd = ["nmap", f"-{settings.NMAP_SCAN_TYPE}", "-Pn", "--open", "--top-ports", str(ports)]
    if service_detection:
        cmd += ["-sV", "--version-intensity", "2"]
    cmd += ["--host-timeout", f"{settings.NMAP_TIMEOUT_SECONDS}s", "-oX", "-"]
    try:
        if ipaddress.ip_address(target_ip).version == 6:
            cmd.append("-6")
    except ValueError:
        pass
    cmd.append(target_ip)
    return cmd


# ---------- 子进程边界（测试 monkeypatch 点） ----------
async def _run_nmap(target_ip: str, ports: int, service_detection: bool) -> tuple[int, str]:
    """调用真实 nmap，返回 (returncode, stdout)。唯一执行子进程的地方。"""
    cmd = _build_nmap_cmd(target_ip, ports, service_detection)

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, _stderr = await asyncio.wait_for(
            proc.communicate(), timeout=settings.NMAP_TIMEOUT_SECONDS + 30
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()  # 回收僵尸进程
        raise
    return proc.returncode or 0, stdout.decode("utf-8", errors="replace")


# ---------- 纯函数（重点单测对象） ----------
def _parse_nmap_xml(xml_text: str) -> list[dict]:
    """解析 nmap -oX XML，提取 open 端口。返回 [{port, protocol, service, product, version}]。"""
    root = ET.fromstring(xml_text)
    result: list[dict] = []
    for port in root.iter("port"):
        state_el = port.find("state")
        if state_el is None or state_el.get("state") != "open":
            continue
        service_el = port.find("service")
        result.append({
            "port": int(port.get("portid")),
            "protocol": port.get("protocol"),
            "service": service_el.get("name") if service_el is not None else None,
            "product": service_el.get("product") if service_el is not None else None,
            "version": service_el.get("version") if service_el is not None else None,
        })
    return result


def _derive_vulnerabilities(open_ports: list[dict]) -> list[dict]:
    """真实开放端口 × 静态服务风险映射；每端口至多产出一条。"""
    vulns: list[dict] = []
    for p in open_ports:
        rule = PORT_VULN_MAP.get(p.get("port"))
        if rule:
            vulns.append({"name": rule["name"], "severity": rule["severity"], "cve": rule["cve"], "port": p["port"]})
        else:
            vulns.append({"name": "非标准服务端口暴露", "severity": "info", "cve": None, "port": p["port"]})
    return vulns


def _compute_risk_score(open_ports: list[dict], vulns: list[dict]) -> int:
    """min(100, 端口数*5 + Σ severity_weight*2)，权重 critical6/high4/medium3/low2/info1。"""
    score = len(open_ports) * 5 + sum(_SEVERITY_WEIGHT.get(v.get("severity"), 1) * 2 for v in vulns)
    return min(100, score)


# ==================== 网络发现（主机发现 + 幽灵设备比对） ====================

def _build_host_discovery_cmd(network: str) -> list[str]:
    """构造 nmap 主机发现命令行（纯函数，便于单测断言）。

    用 `-sn`（ping/ARP 主机发现，不做端口扫描）；局域网内自动走 ARP 探测，
    无需 root 权限、禁 ICMP 的主机也能发现；`-n` 跳过 DNS 反查加速。
    """
    cmd = ["nmap", "-sn", "-n", "--host-timeout", f"{settings.NMAP_HOST_TIMEOUT}s", "-oX", "-"]
    try:
        if ipaddress.ip_network(network).version == 6:
            cmd.append("-6")
    except ValueError:
        pass
    cmd.append(network)
    return cmd


# ---------- 子进程边界（测试 monkeypatch 点，与 _run_nmap 同模式） ----------
async def _run_host_discovery(network: str) -> tuple[int, str]:
    """调用真实 nmap 主机发现，返回 (returncode, stdout)。"""
    cmd = _build_host_discovery_cmd(network)

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, _stderr = await asyncio.wait_for(
            proc.communicate(), timeout=settings.NMAP_HOST_TIMEOUT + 30
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()  # 回收僵尸进程
        raise
    return proc.returncode or 0, stdout.decode("utf-8", errors="replace")


def _parse_nmap_hosts(xml_text: str) -> list[dict]:
    """解析 nmap -sn -oX XML，提取在线主机 [{ip, mac, vendor}]。

    mac/vendor 仅在 ARP 可达（同网段）时存在，跨网段探测可能缺失；
    IPv6 地址无 MAC，返回 mac=None。同一 host 的 MAC 归属到其全部 IP。
    """
    root = ET.fromstring(xml_text)
    result: list[dict] = []
    for host in root.iter("host"):
        status_el = host.find("status")
        if status_el is None or status_el.get("state") != "up":
            continue
        mac, vendor = None, None
        ips: list[str] = []
        for addr in host.iter("address"):
            t = addr.get("addrtype")
            if t in ("ipv4", "ipv6"):
                ips.append(addr.get("addr"))
            elif t == "mac":
                mac = addr.get("addr")
                vendor = addr.get("vendor")
        for ip in ips:
            result.append({"ip": ip, "mac": mac, "vendor": vendor})
    return result


def launch_discovery(discovery_id: int, network: str) -> None:
    """在调用方事件循环上创建后台发现任务并持有引用（同 launch_scan 模式）。"""
    task = asyncio.create_task(execute_discovery(discovery_id, network))
    _active_discovery_tasks[discovery_id] = task
    task.add_done_callback(lambda _t: _active_discovery_tasks.pop(discovery_id, None))


async def execute_discovery(discovery_id: int, network: str) -> None:
    """执行一次网络发现：pending → running → completed / failed。

    完成后用独立 session 比对台账：在线 IP × 该子网 active 分配
    → unregistered（幽灵）/ registered / offline 三个分组写回 JSONB。
    """
    async with AsyncSessionLocal() as session:
        d = await session.get(NetworkDiscovery, discovery_id)
        if not d:
            return
        d.scan_status = "running"
        await session.commit()

    try:
        async with SCAN_SEM:
            _rc, stdout = await _run_host_discovery(network)
        hosts = _parse_nmap_hosts(stdout)  # [{ip, mac, vendor}]
        online_ips = [h["ip"] for h in hosts]
        async with AsyncSessionLocal() as session:
            d = await session.get(NetworkDiscovery, discovery_id)
            if not d:
                return
            net = ipaddress.ip_network(network)

            def _in_net(ip_str: str) -> bool:
                try:
                    return ipaddress.ip_address(ip_str) in net
                except ValueError:
                    return False

            # 登记目标含设备 + 分配：全量查询后按目标网段过滤（手动网段可能无 subnet_id 关联，
            # 不能按 subnet_id 查；INET 列读回 IPv4Address，str 归一化）
            alloc_ips = {str(a.ip_address) for a in (await session.execute(
                select(IPAllocation).where(IPAllocation.is_active.is_(True))
            )).scalars()}
            dev_ips = {str(x) for x in (await session.execute(select(Device.ip_address))).scalars()}
            registered_set = {ip for ip in (alloc_ips | dev_ips) if _in_net(ip)}
            online_set = set(online_ips)
            d.hosts = hosts
            d.online_ips = sorted(online_set)
            d.unregistered_ips = sorted(online_set - registered_set)
            d.registered_ips = sorted(online_set & registered_set)
            d.offline_ips = sorted(registered_set - online_set)
            d.scan_status = "completed"
            d.completed_at = dt.datetime.now(dt.timezone.utc)
            await session.commit()
    except asyncio.TimeoutError:
        await _mark_discovery_failed(discovery_id, f"发现超时（>{settings.NMAP_HOST_TIMEOUT}s）")
    except Exception as e:  # noqa: BLE001 —— 后台任务兜底，任何异常都落地为 failed
        await _mark_discovery_failed(discovery_id, str(e)[:500])


async def _mark_discovery_failed(discovery_id: int, msg: str) -> None:
    async with AsyncSessionLocal() as session:
        d = await session.get(NetworkDiscovery, discovery_id)
        if d:
            d.scan_status, d.error = "failed", msg
            await session.commit()
