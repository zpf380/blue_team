"""扫描/发现目标安全策略：仅允许内网地址，公网一律拒绝。

设计：蓝队扫描/发现是内部作业，目标必须落在内网（RFC1918 + 链路本地 + 回环 +
IPv6 ULA/链路本地），防止平台被滥用为对公网任意主机的探测跳板
（SSRF/横向滥用）。与 Python 标准库 is_private 不同，这里显式列出允许集合，
避免标准库随版本收窄/放宽策略。

- IP 判定：地址 ∈ 任一允许网段。
- 网段判定：网段必须被某个允许大网段包含（子集）才算内网。
"""
import ipaddress

# 允许扫描的内网地址块（IPv4）：RFC1918 + 链路本地 + 回环
_PRIVATE_V4 = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # 链路本地
    ipaddress.ip_network("127.0.0.0/8"),     # 回环（本机/容器内扫描场景）
]
# 允许扫描的内网地址块（IPv6）：ULA + 链路本地 + 回环
_PRIVATE_V6 = [
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::1/128"),
]


def is_internal_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """单个地址是否为内网地址。"""
    blocks = _PRIVATE_V4 if ip.version == 4 else _PRIVATE_V6
    return any(ip in b for b in blocks)


def is_internal_network(net: ipaddress.IPv4Network | ipaddress.IPv6Network) -> bool:
    """网段是否为内网：必须完全落在某个允许内网块内。"""
    blocks = _PRIVATE_V4 if net.version == 4 else _PRIVATE_V6
    return any(net.subnet_of(b) for b in blocks)
