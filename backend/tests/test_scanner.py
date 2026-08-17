"""扫描执行器纯函数单测：XML 解析 / 风险推导 / 评分（无 DB、无 nmap）。"""
import pytest

from app.services.scanner import (
    _build_host_discovery_cmd,
    _build_nmap_cmd,
    _compute_risk_score,
    _derive_vulnerabilities,
    _parse_nmap_hosts,
    _parse_nmap_xml,
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
