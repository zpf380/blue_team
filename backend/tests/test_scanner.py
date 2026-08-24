"""扫描执行器纯函数单测：XML 解析 / 风险推导 / 评分 / NSE / 漂移（无 DB、无 nmap）。"""
import asyncio

import pytest

from app.services.scanner import (
    ScanOptions,
    _baseline_compatible,
    _build_host_discovery_cmd,
    _build_nmap_cmd,
    _classify_nmap_error,
    _compute_baseline_diff,
    _compute_risk_score,
    _derive_vulnerabilities,
    _merge_vulnerabilities,
    _parse_nmap_hosts,
    _parse_nmap_xml,
    _parse_nse_findings,
    _validate_port_range,
)

OPEN_XML = """<?xml version="1.0"?>
<nmaprun scanner="nmap" version="7.94">
  <host><status state="up"/>
    <ports>
      <port protocol="tcp" portid="22">
        <state state="open" reason="syn-ack"/>
        <service name="ssh" product="OpenSSH" version="8.9p1"/>
      </port>
      <port protocol="tcp" portid="80">
        <state state="open"/>
        <service name="http"/>
      </port>
      <port protocol="tcp" portid="443">
        <state state="closed"/>
        <service name="https"/>
      </port>
    </ports>
  </host>
</nmaprun>
"""


def test_build_nmap_cmd():
    # 回归：NMAP_SCAN_TYPE="sS" 时须拼出 "-sS"，而非 "f-s{sS}" 的 "-ssS"（会导致 nmap 打印 usage、rc=255）
    cmd = _build_nmap_cmd("10.0.10.11", 100, True)
    assert cmd[0] == "nmap" and cmd[1] == "-sS"
    assert "-Pn" in cmd and "--open" in cmd and "--top-ports" in cmd and "100" in cmd
    assert "--host-timeout" in cmd and "-oX" in cmd and "-" in cmd
    assert "-sV" in cmd and cmd[-1] == "10.0.10.11" and "-6" not in cmd

    # IPv6 追加 -6；关闭服务探测则不挂 -sV
    cmd6 = _build_nmap_cmd("2001:db8::1", 20, False)
    assert "-6" in cmd6 and "-sV" not in cmd6 and cmd6[-1] == "2001:db8::1"


def test_parse_xml_multiple_ports():
    result = _parse_nmap_xml(OPEN_XML)
    assert len(result) == 2  # 仅 open 端口
    p22 = next(p for p in result if p["port"] == 22)
    assert p22["protocol"] == "tcp"
    assert p22["service"] == "ssh"
    assert p22["product"] == "OpenSSH"
    assert p22["version"] == "8.9p1"
    p80 = next(p for p in result if p["port"] == 80)
    assert p80["service"] == "http"


def test_parse_xml_no_open():
    xml = """<?xml version="1.0"?><nmaprun><host><status state="down"/>
    <ports><port protocol="tcp" portid="22"><state state="filtered"/></port></ports></host></nmaprun>"""
    assert _parse_nmap_xml(xml) == []


def test_parse_xml_malformed():
    with pytest.raises(Exception):
        _parse_nmap_xml("this is not xml at all <<<")


def test_derive_vulnerabilities_port_map():
    open_ports = [
        {"port": 6379, "protocol": "tcp", "service": "redis"},
        {"port": 3306, "protocol": "tcp", "service": "mysql"},
        {"port": 80, "protocol": "tcp", "service": "http"},
        {"port": 54321, "protocol": "tcp", "service": "custom"},
    ]
    vulns = _derive_vulnerabilities(open_ports)
    by_port = {v["port"]: v for v in vulns}
    assert by_port[6379]["severity"] == "critical"
    assert by_port[6379]["cve"] == "CVE-2022-0543"
    assert by_port[3306]["severity"] == "high"
    assert by_port[80]["severity"] == "low"
    # 未命中端口 → info 兜底
    assert by_port[54321]["severity"] == "info"
    assert by_port[54321]["name"] == "非标准服务端口暴露"
    assert len(vulns) == 4  # 每端口至多一条


def test_risk_score_capping():
    # 大量高危端口 → 封顶 100
    open_ports = [{"port": 6379, "protocol": "tcp", "service": None}] * 40
    vulns = _derive_vulnerabilities(open_ports)
    assert _compute_risk_score(open_ports, vulns) == 100
    # 空端口 → 0
    assert _compute_risk_score([], []) == 0


def test_derive_vulnerabilities_service_and_product_rules():
    """增强回归：非标准端口按 service/product 归类，不再一律 info；每端口至多一条。"""
    open_ports = [
        # 端口无规则 + service http → 服务级 low（product Node.js Express 不覆盖已命中的服务规则）
        {"port": 3000, "protocol": "tcp", "service": "http", "product": "Node.js Express framework", "version": None},
        # service mongod → 服务级 high + CVE
        {"port": 27017, "protocol": "tcp", "service": "mongod", "product": None, "version": None},
        # service memcached → high + CVE（反射放大）
        {"port": 11211, "protocol": "tcp", "service": "memcached", "product": None, "version": None},
        # service 未命中 → product 子串 OpenSSH → low
        {"port": 2222, "protocol": "tcp", "service": "custom", "product": "OpenSSH", "version": "9.0p1"},
        # 全未命中 → info 兜底
        {"port": 23456, "protocol": "tcp", "service": "unknown", "product": "Some Vendor App", "version": None},
    ]
    vulns = _derive_vulnerabilities(open_ports)
    by_port = {v["port"]: v for v in vulns}
    assert by_port[3000]["severity"] == "low" and by_port[3000]["name"] == "HTTP 服务暴露"
    assert by_port[27017]["severity"] == "high" and by_port[27017]["cve"] == "CVE-2013-1892"
    assert by_port[11211]["severity"] == "high" and by_port[11211]["cve"] == "CVE-2018-1000115"
    assert by_port[2222]["severity"] == "low" and by_port[2222]["name"] == "OpenSSH 服务暴露"
    assert by_port[23456]["severity"] == "info" and by_port[23456]["name"] == "非标准服务端口暴露"
    assert len(vulns) == 5  # 每端口至多一条


# ---------- 网络发现纯函数 ----------
def test_build_host_discovery_cmd():
    cmd = _build_host_discovery_cmd("10.0.50.0/28")
    assert cmd[0] == "nmap" and cmd[1] == "-sn"
    assert "-n" in cmd and "--host-timeout" in cmd and "-oX" in cmd and "-" in cmd
    assert "-sS" not in cmd and "-sV" not in cmd and "-Pn" not in cmd  # 主机发现不带端口扫描参数
    assert "-6" not in cmd and cmd[-1] == "10.0.50.0/28"

    # IPv6 网段追加 -6
    cmd6 = _build_host_discovery_cmd("2001:db8::/64")
    assert "-6" in cmd6 and cmd6[-1] == "2001:db8::/64"


def test_parse_nmap_hosts():
    xml = """<?xml version="1.0"?>
    <nmaprun scanner="nmap" version="7.94">
      <host><status state="up"/>
        <address addr="10.0.50.2" addrtype="ipv4"/>
        <address addr="AA:BB:CC:DD:EE:FF" addrtype="mac" vendor="VMware, Inc."/></host>
      <host><status state="down"/><address addr="10.0.50.9" addrtype="ipv4"/></host>
      <host><status state="up"><address addr="2001:db8::5" addrtype="ipv6"/></status></host>
      <host><status state="up"/><address addr="AA:BB:CC:DD:EE:0F" addrtype="mac" vendor="Intel"/></host>
      <host><status state="up"><address addr="10.0.50.6" addrtype="ipv4"/></status></host>
    </nmaprun>"""
    result = _parse_nmap_hosts(xml)
    # down 过滤；MAC 归属到同 host 的 IP；只有 MAC 无 IP 的 host 不产出；无 MAC → None
    assert result == [
        {"ip": "10.0.50.2", "mac": "AA:BB:CC:DD:EE:FF", "vendor": "VMware, Inc."},
        {"ip": "2001:db8::5", "mac": None, "vendor": None},
        {"ip": "10.0.50.6", "mac": None, "vendor": None},
    ]


def test_parse_nmap_hosts_mac_merge():
    """双栈 host（ipv4 + ipv6）共享同一 MAC。"""
    xml = """<?xml version="1.0"?>
    <nmaprun scanner="nmap" version="7.94">
      <host><status state="up"/>
        <address addr="10.0.50.2" addrtype="ipv4"/>
        <address addr="2001:db8::2" addrtype="ipv6"/>
        <address addr="AA:BB:CC:DD:EE:FF" addrtype="mac" vendor="VMware, Inc."/></host>
    </nmaprun>"""
    result = _parse_nmap_hosts(xml)
    assert result == [
        {"ip": "10.0.50.2", "mac": "AA:BB:CC:DD:EE:FF", "vendor": "VMware, Inc."},
        {"ip": "2001:db8::2", "mac": "AA:BB:CC:DD:EE:FF", "vendor": "VMware, Inc."},
    ]


def test_parse_nmap_hosts_empty():
    xml = """<?xml version="1.0"?><nmaprun>
    <host><status state="down"/><address addr="10.0.50.9" addrtype="ipv4"/></host>
    </nmaprun>"""
    assert _parse_nmap_hosts(xml) == []


def test_parse_nmap_hosts_malformed():
    with pytest.raises(Exception):
        _parse_nmap_hosts("this is not xml at all <<<")


# ==================== 新增：扫描能力扩展 / NSE / 工程化 / 基线漂移 ====================

def test_build_nmap_cmd_port_range():
    # 有 port_range 用 -p，且与 --top-ports 互斥
    cmd = _build_nmap_cmd("10.0.10.11", None, False, port_range="22,80,443")
    assert "-p" in cmd and "22,80,443" in cmd and "--top-ports" not in cmd


def test_build_nmap_cmd_scan_type():
    cmd = _build_nmap_cmd("10.0.10.11", 100, False, scan_type="sT")
    assert "-sT" in cmd


def test_build_nmap_cmd_udp_defaults():
    # UDP：-sU、更小默认端口数、更保守超时
    cmd = _build_nmap_cmd("10.0.10.11", None, False, scan_type="sU")
    assert "-sU" in cmd and "--top-ports" in cmd and "20" in cmd
    assert "--host-timeout" in cmd and "300s" in cmd


def test_build_nmap_cmd_nse():
    cmd = _build_nmap_cmd("10.0.10.11", 100, False, nse_scripts="vuln")
    assert "--script" in cmd and "vuln" in cmd
    assert "--script" not in _build_nmap_cmd("10.0.10.11", 100, False)


def test_validate_port_range_ok():
    assert _validate_port_range("22,80,443") == "22,80,443"
    assert _validate_port_range("1-1000") == "1-1000"
    assert _validate_port_range("1-1000,2000") == "1-1000,2000"
    assert _validate_port_range("") == ""


def test_validate_port_range_invalid():
    for bad in ("0-5", "1-70000", "abc", "1--2", "22,,443", "1-1000,99999"):
        with pytest.raises(ValueError):
            _validate_port_range(bad)


def test_validate_port_range_too_many():
    # 全端口范围超出 NMAP_MAX_PORTS_IN_RANGE 上限 → 拒绝
    with pytest.raises(ValueError):
        _validate_port_range("1-65535")


NSE_XML = """<?xml version="1.0"?>
<nmaprun scanner="nmap" version="7.94">
  <host><status state="up"/>
    <ports>
      <port protocol="tcp" portid="445">
        <state state="open"/>
        <service name="microsoft-ds"/>
        <script id="smb-vuln-ms17-010" output="VULNERABLE: MS17-010 remote code execution"/>
        <script id="http-title" output="test page"/>
      </port>
    </ports>
    <hostscript>
      <script id="ssl-heartbleed" output="CVE-2014-0160 present, vulnerable"/>
    </hostscript>
  </host>
</nmaprun>
"""


def test_parse_nse_findings():
    findings = _parse_nse_findings(NSE_XML)
    by_id = {f["name"]: f for f in findings}
    assert "smb-vuln-ms17-010" in by_id
    f = by_id["smb-vuln-ms17-010"]
    assert f["port"] == 445 and f["protocol"] == "tcp" and f["source"] == "nse"
    assert f["severity"] == "critical"
    assert "http-title" not in by_id  # 描述类脚本被过滤
    # 主机级脚本：有 CVE → high，无端口
    assert by_id["ssl-heartbleed"]["severity"] == "high"
    assert by_id["ssl-heartbleed"]["cve"] == "CVE-2014-0160"
    assert by_id["ssl-heartbleed"]["port"] is None


def test_merge_vulnerabilities_source():
    open_ports = [{"port": 6379, "protocol": "tcp", "service": "redis"}]
    nse = [{"port": 6379, "name": "redis-vuln-x", "severity": "high", "cve": "CVE-2022-9999", "source": "nse", "output": ""}]
    merged = _merge_vulnerabilities(open_ports, nse)
    assert len(merged) == 2
    assert any(v["source"] == "nse" and v["cve"] == "CVE-2022-9999" for v in merged)
    assert any(v["source"] == "static" and v["port"] == 6379 for v in merged)
    # 纯静态调用仍带 source=static
    assert _derive_vulnerabilities(open_ports)[0]["source"] == "static"


def test_classify_nmap_error():
    assert _classify_nmap_error(255, "ERROR: You cannot use -sS for this probe type") == "permission"
    assert _classify_nmap_error(255, "Failed to resolve target: Host seems down") == "unreachable"
    assert _classify_nmap_error(1, "something odd happened") == "generic"
    assert _classify_nmap_error(0, "", asyncio.TimeoutError()) == "timeout"
    assert _classify_nmap_error(0, "", asyncio.CancelledError()) == "cancelled"


def test_compute_baseline_diff():
    prev = [{"port": 22, "protocol": "tcp", "service": "ssh"}, {"port": 80, "protocol": "tcp", "service": "http"}]
    new = [
        {"port": 22, "protocol": "tcp", "service": "ssh"},
        {"port": 443, "protocol": "tcp", "service": "https"},
        {"port": 8080, "protocol": "tcp", "service": "proxy"},
    ]
    diff = _compute_baseline_diff(prev, new)
    assert {p["port"] for p in diff["new_ports"]} == {443, 8080}
    assert {p["port"] for p in diff["closed_ports"]} == {80}
    # 服务变化
    diff2 = _compute_baseline_diff(
        [{"port": 22, "protocol": "tcp", "service": "ssh"}],
        [{"port": 22, "protocol": "tcp", "service": "telnet"}],
    )
    assert diff2["changed_services"] == [{"port": 22, "protocol": "tcp", "service": "telnet", "previous_service": "ssh"}]
    # 无基线 / 完全一致 → None
    assert _compute_baseline_diff(None, new) is None
    assert _compute_baseline_diff(prev, prev) is None


def test_baseline_compatible():
    assert _baseline_compatible(ScanOptions(scan_type="sS", top_ports=100), ScanOptions(scan_type="sS", top_ports=100))
    assert not _baseline_compatible(ScanOptions(scan_type="sU"), ScanOptions(scan_type="sS"))
    assert not _baseline_compatible(ScanOptions(top_ports=100), ScanOptions(top_ports=1000))
    # None top_ports 与显式默认值等价（都归一化为 top1000，跟随 NMAP_TOP_PORTS 配置）
    assert _baseline_compatible(ScanOptions(top_ports=None), ScanOptions(top_ports=1000))
