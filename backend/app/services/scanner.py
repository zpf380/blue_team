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
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

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
# 常见暴露服务 → 风险规则（service 名取自 nmap -sV，全小写）。
# 与 PORT_VULN_MAP 互补：非标准端口也能按服务名归类，不再一律降级为 info；
# CVE 仅在公开编号明确且广为引用时挂载（宁缺毋滥，避免误导）。
SERVICE_VULN_MAP: dict[str, dict] = {
    "http": {"name": "HTTP 服务暴露", "severity": "low", "cve": None},
    "https": {"name": "HTTPS 服务暴露", "severity": "low", "cve": None},
    "http-proxy": {"name": "HTTP 代理服务暴露", "severity": "medium", "cve": None},
    "ssh": {"name": "SSH 服务暴露", "severity": "low", "cve": None},
    "telnet": {"name": "Telnet 明文协议暴露", "severity": "high", "cve": None},
    "ftp": {"name": "FTP 服务暴露", "severity": "medium", "cve": None},
    "smtp": {"name": "SMTP 邮件服务暴露", "severity": "medium", "cve": None},
    "pop3": {"name": "POP3 邮件服务暴露", "severity": "low", "cve": None},
    "imap": {"name": "IMAP 邮件服务暴露", "severity": "low", "cve": None},
    "mysql": {"name": "MySQL 服务暴露", "severity": "high", "cve": None},
    "postgresql": {"name": "PostgreSQL 服务暴露", "severity": "medium", "cve": None},
    "ms-sql-s": {"name": "SQL Server 服务暴露", "severity": "high", "cve": None},
    "mongod": {"name": "MongoDB 未授权访问风险", "severity": "high", "cve": "CVE-2013-1892"},       # MongoDB 未授权 RCE
    "redis": {"name": "Redis 未授权访问", "severity": "critical", "cve": "CVE-2022-0543"},          # Lua 沙箱逃逸
    "memcached": {"name": "Memcached 反射放大风险", "severity": "high", "cve": "CVE-2018-1000115"}, # UDP 反射放大
    "elasticsearch": {"name": "Elasticsearch 服务暴露", "severity": "medium", "cve": None},
    "couchdb": {"name": "CouchDB 服务暴露", "severity": "high", "cve": "CVE-2022-24706"},            # 未授权 RCE
    "docker": {"name": "Docker API 暴露", "severity": "high", "cve": None},
    "kubernetes": {"name": "Kubernetes API 暴露", "severity": "high", "cve": None},
    "jenkins": {"name": "Jenkins 管理面板暴露", "severity": "medium", "cve": None},
    "rabbitmq": {"name": "RabbitMQ 服务暴露", "severity": "medium", "cve": None},
    "consul": {"name": "Consul 服务暴露", "severity": "high", "cve": None},
    "zookeeper": {"name": "ZooKeeper 服务暴露", "severity": "medium", "cve": None},
    "kafka": {"name": "Kafka 服务暴露", "severity": "medium", "cve": None},
    "grafana": {"name": "Grafana 面板暴露", "severity": "medium", "cve": "CVE-2021-43798"},          # 任意文件读取
    "kibana": {"name": "Kibana 面板暴露", "severity": "medium", "cve": "CVE-2019-7609"},            # Timelion RCE
    "prometheus": {"name": "Prometheus 服务暴露", "severity": "low", "cve": None},
    "ms-wbt-server": {"name": "RDP 远程桌面暴露", "severity": "high", "cve": None},
    "rdp": {"name": "RDP 远程桌面暴露", "severity": "high", "cve": None},
    "vnc": {"name": "VNC 远程桌面暴露", "severity": "high", "cve": None},
    "rfb": {"name": "VNC 远程桌面暴露", "severity": "high", "cve": None},
    "microsoft-ds": {"name": "SMB 服务暴露", "severity": "high", "cve": "CVE-2020-0796"},           # SMBGhost
    "netbios-ssn": {"name": "NetBIOS 会话服务暴露", "severity": "medium", "cve": None},
    "msrpc": {"name": "Windows RPC 服务暴露", "severity": "medium", "cve": None},
    "ldap": {"name": "LDAP 目录服务暴露", "severity": "medium", "cve": None},
    "snmp": {"name": "SNMP 服务暴露", "severity": "medium", "cve": None},
    "ntp": {"name": "NTP 服务暴露", "severity": "low", "cve": None},
    "domain": {"name": "Windows 域控制器服务暴露", "severity": "medium", "cve": None},
    "kerberos": {"name": "Kerberos 服务暴露", "severity": "medium", "cve": None},
    "nfs": {"name": "NFS 服务暴露", "severity": "high", "cve": None},
    "sip": {"name": "SIP 语音服务暴露", "severity": "medium", "cve": None},
}
# product 子串 → 规则（-sV 的 product 常带厂商修饰，如 "Node.js Express framework"，子串匹配；
# 列表有序，长串在前避免短串误命中）。端口/服务规则均未命中时才进入。
PRODUCT_RULES: list[tuple[str, dict]] = [
    ("node.js express", {"name": "Node.js Express 服务暴露", "severity": "medium", "cve": None}),
    ("apache httpd", {"name": "Apache HTTP 服务暴露", "severity": "medium", "cve": None}),
    ("tomcat", {"name": "Tomcat 服务暴露", "severity": "medium", "cve": None}),
    ("openssh", {"name": "OpenSSH 服务暴露", "severity": "low", "cve": None}),
    ("nginx", {"name": "Nginx 服务暴露", "severity": "low", "cve": None}),
]
_SEVERITY_WEIGHT = {"critical": 6, "high": 4, "medium": 3, "low": 2, "info": 1}

# 扫描失败原因分类（error_code 落库值）
SCAN_ERROR_CODES = ("cancelled", "timeout", "permission", "unreachable", "generic")

# NSE 输出里的 CVE 形如 CVE-2022-0543
_CVE_RE = re.compile(r"CVE-\d{4}-\d+")


@dataclass
class ScanOptions:
    """一次扫描的生效选项（快照持久化到 scan_reports.scan_options，重试/漂移对比用）。

    - top_ports 与 port_range 二选一：None + None → 用 NMAP_TOP_PORTS（UDP 用 NMAP_UDP_TOP_PORTS）
    - nse：per-scan 开关；实际跑 NSE 与否还看 settings.NMAP_NSE_SCRIPTS 是否非空
    """
    scan_type: str = "sS"                        # sS / sT / sU
    top_ports: int | None = None                 # 请求的 --top-ports 数
    port_range: str | None = None                # "1-1000" / "22,80,443" / None
    service_detection: bool | None = None        # None → settings.NMAP_VERSION_DETECT
    nse: bool = True


def _options_to_dict(opts: ScanOptions) -> dict:
    return {
        "scan_type": opts.scan_type,
        "top_ports": opts.top_ports,
        "port_range": opts.port_range,
        "service_detection": opts.service_detection,
        "nse": opts.nse,
    }


def _options_from_dict(d: dict | None) -> ScanOptions:
    d = d or {}
    return ScanOptions(
        scan_type=d.get("scan_type") or "sS",
        top_ports=d.get("top_ports"),
        port_range=d.get("port_range"),
        service_detection=d.get("service_detection"),
        nse=bool(d.get("nse", True)),
    )


def launch_scan(report_id: int, target_ip: str, options: ScanOptions | None = None) -> None:
    """在调用方事件循环上创建后台扫描任务并持有引用。"""
    opts = options or ScanOptions()
    task = asyncio.create_task(execute_scan(report_id, target_ip, opts.top_ports, opts))
    _active_scan_tasks[report_id] = task
    task.add_done_callback(lambda _t: _active_scan_tasks.pop(report_id, None))


async def execute_scan(report_id: int, target_ip: str, ports: int | None = None, scan_options: ScanOptions | None = None) -> None:
    """执行一次完整扫描：pending → running → completed / failed。

    `ports` 保留为第 3 位置参（兼容既有测试直调 execute_scan(r.id, ip, 100)）；
    scan_options 为完整选项快照，缺省时按 top_ports=ports 构造。
    """
    opts = scan_options or ScanOptions(top_ports=ports)
    service_detect = opts.service_detection if opts.service_detection is not None else settings.NMAP_VERSION_DETECT
    timeout = settings.NMAP_UDP_TIMEOUT_SECONDS if opts.scan_type == "sU" else settings.NMAP_TIMEOUT_SECONDS
    async with AsyncSessionLocal() as session:
        r = await session.get(ScanReport, report_id)
        if not r:
            return
        r.scan_status = "running"
        r.summary = f"目标 {target_ip} 扫描进行中…"
        await session.commit()

    try:
        async with SCAN_SEM:
            rc, stdout, stderr = await _run_nmap(target_ip, opts.top_ports, service_detect, scan_options=opts)
        open_ports = _parse_nmap_xml(stdout)
        if rc != 0 and not open_ports:
            # nmap 硬失败且无部分结果（权限不足/目标不可达/脚本崩溃等）→ 落失败并分类
            await _mark_failed(report_id, (stderr or f"nmap 退出码 {rc}")[:500], error_code=_classify_nmap_error(rc, stderr))
            return
        vulns = _merge_vulnerabilities(open_ports, _parse_nse_findings(stdout))
        risk = _compute_risk_score(open_ports, vulns)
        # 基线漂移：与同 target_ip 上次 completed 且同口径（scan_type+端口规格）扫描对比
        async with AsyncSessionLocal() as session:
            prev = await _find_previous_scan(session, target_ip, report_id)
        baseline_diff, drift_note = None, ""
        if prev is not None and _baseline_compatible(_options_from_dict(prev.scan_options), opts):
            prev_ports = (prev.scan_data or {}).get("open_ports") if prev.scan_data else None
            baseline_diff = _compute_baseline_diff(prev_ports, open_ports)
            if baseline_diff:
                drift_note = _drift_summary_text(baseline_diff)
        scan_data = {
            "target_ip": target_ip,
            "open_ports": open_ports,
            "vulnerabilities": vulns,
            "risk_score": risk,
            "scanned_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "nmap_exit": rc,
            "baseline_diff": baseline_diff,
            "nse_scripts": (settings.NMAP_NSE_SCRIPTS if opts.nse else ""),
            "nmap_warning": (stderr[:300] if rc != 0 else None),  # rc≠0 但有部分结果时的告警
        }
        summary = f"目标 {target_ip}：发现开放端口 {len(open_ports)} 个、风险 {len(vulns)} 项，风险评分 {risk}。" + drift_note
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
        await _mark_failed(report_id, f"扫描超时（>{timeout}s）", error_code="timeout")
    except asyncio.CancelledError:
        # 用户取消：cancel_scan → task.cancel() → CancelledError 注入 _run_nmap 的 wait_for
        #（子进程已在 _run_nmap 中 kill 回收），此处落 failed/cancelled 再向上传播
        await _mark_failed(report_id, "扫描已被用户取消", error_code="cancelled")
        raise
    except Exception as e:  # noqa: BLE001 —— 后台任务兜底，任何异常都落地为 failed
        await _mark_failed(report_id, str(e)[:500], error_code=_classify_nmap_error(0, "", e))


async def _mark_failed(report_id: int, msg: str, error_code: str | None = None) -> None:
    async with AsyncSessionLocal() as session:
        r = await session.get(ScanReport, report_id)
        if r:
            r.scan_status, r.error, r.error_code = "failed", msg, error_code
            await session.commit()


def _build_nmap_cmd(
    target_ip: str,
    ports: int | None,
    service_detection: bool,
    scan_type: str | None = None,
    port_range: str | None = None,
    nse_scripts: str | None = None,
) -> list[str]:
    """构造 nmap 命令行（纯函数，便于单测断言参数拼接）。

    - 有 port_range 用 `-p`（与 `--top-ports` 互斥）；否则用 --top-ports（UDP 用更小默认值）
    - sU 使用 UDP 专属 --host-timeout；NSE 脚本经 `--script` 追加在 -sV 之后
    """
    scan_type = scan_type or settings.NMAP_SCAN_TYPE
    timeout = settings.NMAP_UDP_TIMEOUT_SECONDS if scan_type == "sU" else settings.NMAP_TIMEOUT_SECONDS
    cmd = ["nmap", f"-{scan_type}", "-Pn", "--open"]
    if port_range:
        cmd += ["-p", port_range]
    else:
        top = ports or (settings.NMAP_UDP_TOP_PORTS if scan_type == "sU" else settings.NMAP_TOP_PORTS)
        cmd += ["--top-ports", str(top)]
    if service_detection:
        cmd += ["-sV", "--version-intensity", "2"]
    if nse_scripts:
        cmd += ["--script", nse_scripts]
    cmd += ["--host-timeout", f"{timeout}s", "-oX", "-"]
    try:
        if ipaddress.ip_address(target_ip).version == 6:
            cmd.append("-6")
    except ValueError:
        pass
    cmd.append(target_ip)
    return cmd


# ---------- 子进程边界（测试 monkeypatch 点） ----------
async def _run_nmap(
    target_ip: str,
    ports: int | None,
    service_detection: bool,
    scan_options: ScanOptions | None = None,
) -> tuple[int, str, str]:
    """调用真实 nmap，返回 (returncode, stdout, stderr)。唯一执行子进程的地方。"""
    opts = scan_options or ScanOptions()
    cmd = _build_nmap_cmd(
        target_ip, ports, service_detection,
        scan_type=opts.scan_type,
        port_range=opts.port_range,
        nse_scripts=(settings.NMAP_NSE_SCRIPTS if opts.nse else ""),
    )
    timeout = settings.NMAP_UDP_TIMEOUT_SECONDS if opts.scan_type == "sU" else settings.NMAP_TIMEOUT_SECONDS

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 30)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        proc.kill()
        await proc.wait()  # 超时/任务取消都回收子进程
        raise
    return proc.returncode or 0, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")


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
    """真实开放端口 × 静态风险规则；每端口至多产出一条（source=static）。

    匹配优先级：端口规则（最具体）→ 服务名规则（-sV 检测，非标准端口也能归类）→
    product 子串规则 → 兜底 info。CVE 仅在公开编号明确且广为引用时挂载。
    """
    vulns: list[dict] = []
    for p in open_ports:
        rule = PORT_VULN_MAP.get(p.get("port"))
        if rule is None:
            rule = SERVICE_VULN_MAP.get((p.get("service") or "").lower())
        if rule is None:
            prod = (p.get("product") or "").lower()
            rule = next((r for substr, r in PRODUCT_RULES if substr in prod), None)
        if rule is None:
            rule = {"name": "非标准服务端口暴露", "severity": "info", "cve": None}
        vulns.append({"name": rule["name"], "severity": rule["severity"], "cve": rule["cve"], "port": p["port"], "source": "static"})
    return vulns


def _merge_vulnerabilities(open_ports: list[dict], nse_findings: list[dict] | None = None) -> list[dict]:
    """静态端口映射（source=static）+ NSE 脚本发现（source=nse）合并；NSE 为增量补充而非替代。"""
    vulns = _derive_vulnerabilities(open_ports)
    if nse_findings:
        vulns.extend(nse_findings)
    return vulns


def _compute_risk_score(open_ports: list[dict], vulns: list[dict]) -> int:
    """min(100, 端口数*5 + Σ severity_weight*2)，权重 critical6/high4/medium3/low2/info1。"""
    score = len(open_ports) * 5 + sum(_SEVERITY_WEIGHT.get(v.get("severity"), 1) * 2 for v in vulns)
    return min(100, score)


# ---------- NSE 真实漏洞检测（nmap 自带 vuln 脚本，离线） ----------
def _parse_nse_findings(xml_text: str) -> list[dict]:
    """解析 nmap -oX XML 中的 NSE script 元素 → [{port, protocol, name, severity, cve, source, output}]。

    端口级 <port><script> 与主机级 <hostscript><script> 都提取；只保留"有意义"结果：
    output 含 VULNERABLE / 提取到 CVE / script id 含 vuln（过滤 http-title 等描述类脚本）。
    """
    root = ET.fromstring(xml_text)
    findings: list[dict] = []
    for port in root.iter("port"):
        st = port.find("state")
        if st is not None and st.get("state") != "open":
            continue
        portid, proto = int(port.get("portid")), port.get("protocol")
        for s in port.findall("script"):
            f = _nse_script_to_finding(s, portid, proto)
            if f:
                findings.append(f)
    for hs in root.iter("hostscript"):
        for s in hs.findall("script"):
            f = _nse_script_to_finding(s, None, None)
            if f:
                findings.append(f)
    return findings


def _nse_script_to_finding(script, port: int | None, proto: str | None) -> dict | None:
    sid = script.get("id", "")
    output = (script.get("output") or "")[:500]
    cves = sorted(set(_CVE_RE.findall(output)))
    if not ("VULNERABLE" in output.upper() or cves or "vuln" in sid.lower()):
        return None
    return {
        "port": port, "protocol": proto, "name": sid,
        "severity": _map_nse_severity(sid, output, cves),
        "cve": cves[0] if cves else None, "source": "nse", "output": output,
    }


def _map_nse_severity(script_id: str, output: str, cves: list) -> str:
    """启发式映射（真实 CVSS 需外接 NVD API，超出"不新增外部依赖"约束）：
    已知蠕虫级脚本 critical，有 CVE / 报 VULNERABLE 为 high，其余 medium。"""
    low = script_id.lower()
    if "ms17-010" in low or "eternalblue" in low or "smb-vuln" in low:
        return "critical"
    if cves or "VULNERABLE" in (output or "").upper():
        return "high"
    return "medium"


# ---------- port_range 校验（防注入 + 防全端口 DoS） ----------
def _validate_port_range(port_range: str) -> str:
    """校验并返回端口范围表达式；非法抛 ValueError。允许 "22,80,443" / "1-1000" / "1-1000,2000"。"""
    if not port_range:
        return port_range
    if not re.fullmatch(r"[0-9,\-]{1,200}", port_range):
        raise ValueError("端口范围仅允许数字、逗号与短横线")
    total = 0
    for item in port_range.split(","):
        item = item.strip()
        if not item:
            raise ValueError("端口范围格式不正确")
        if "-" in item:
            parts = item.split("-")
            if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
                raise ValueError(f"端口区间格式不正确：{item}")
            lo, hi = int(parts[0]), int(parts[1])
            if not (1 <= lo <= hi <= 65535):
                raise ValueError(f"端口区间越界：{item}")
            total += hi - lo + 1
        else:
            if not (item.isdigit() and 1 <= int(item) <= 65535):
                raise ValueError(f"端口越界：{item}")
            total += 1
    if total > settings.NMAP_MAX_PORTS_IN_RANGE:
        raise ValueError(f"端口范围过大（最多 {settings.NMAP_MAX_PORTS_IN_RANGE} 个端口）")
    return port_range


# ---------- 任务工程化：错误分类 + 取消 ----------
_ERROR_KEYWORDS = {
    "permission": (
        "permission denied", "operation not permitted", "requires root", "not authorized",
        "you cannot use", "cannot set", "probe type",
    ),
    "unreachable": (
        "host unreachable", "network is unreachable", "no route to host",
        "host seems down", "timed out during connect", "timeout expired",
    ),
}


def _classify_nmap_error(rc: int, stderr: str = "", exc: BaseException | None = None) -> str:
    """失败原因分类：timeout / cancelled / permission / unreachable / generic。"""
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    if isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    low = (stderr or "").lower()
    for code, kws in _ERROR_KEYWORDS.items():
        if any(k in low for k in kws):
            return code
    return "generic"


def cancel_scan(report_id: int) -> bool:
    """取消进行中的扫描任务（进程内 registry）。任务已结束返回 False。"""
    task = _active_scan_tasks.get(report_id)
    if not task or task.done():
        return False
    task.cancel()
    return True


# ---------- 基线漂移对比（与同 target_ip 上次同口径扫描对比） ----------
def _port_spec(opts: ScanOptions) -> str:
    return opts.port_range or f"top{opts.top_ports or settings.NMAP_TOP_PORTS}"


def _baseline_compatible(prev: ScanOptions, cur: ScanOptions) -> bool:
    """扫描类型 + 端口规格一致才算可比，避免 top-100 TCP 与 1-1000 UDP 误对比。"""
    return prev.scan_type == cur.scan_type and _port_spec(prev) == _port_spec(cur)


async def _find_previous_scan(session, target_ip: str, exclude_id: int):
    stmt = (
        select(ScanReport).where(
            ScanReport.target_ip == target_ip,
            ScanReport.scan_status == "completed",
            ScanReport.scan_data.is_not(None),
            ScanReport.id != exclude_id,
        )
        .order_by(ScanReport.generated_at.desc(), ScanReport.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


def _compute_baseline_diff(prev_ports: list[dict] | None, new_ports: list[dict]) -> dict | None:
    """与上次开放端口对比：新增 / 关闭 / 服务变化。无基线或完全一致返回 None。"""
    if prev_ports is None:
        return None
    prev_k = {(p.get("port"), p.get("protocol")): p for p in prev_ports}
    new_k = {(p.get("port"), p.get("protocol")): p for p in new_ports}
    new_open = [{"port": k[0], "protocol": k[1], "service": new_k[k].get("service")} for k in new_k if k not in prev_k]
    closed = [{"port": k[0], "protocol": k[1], "service": prev_k[k].get("service")} for k in prev_k if k not in new_k]
    changed = [
        {"port": k[0], "protocol": k[1], "service": new_k[k].get("service"), "previous_service": prev_k[k].get("service")}
        for k in new_k.keys() & prev_k.keys()
        if new_k[k].get("service") != prev_k[k].get("service")
    ]
    if not (new_open or closed or changed):
        return None
    return {"new_ports": new_open, "closed_ports": closed, "changed_services": changed}


def _drift_summary_text(diff: dict) -> str:
    parts = []
    if diff.get("new_ports"):
        parts.append(f"新增端口 {len(diff['new_ports'])} 个")
    if diff.get("closed_ports"):
        parts.append(f"关闭端口 {len(diff['closed_ports'])} 个")
    if diff.get("changed_services"):
        parts.append(f"服务变化 {len(diff['changed_services'])} 项")
    return "，与上次扫描相比：" + "、".join(parts)


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
