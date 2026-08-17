"""扫描目标安全策略纯函数单测：内网判定（IPv4/IPv6）边界覆盖。"""
import ipaddress

import pytest

from app.services.scan_policy import is_internal_ip, is_internal_network

# 允许扫描的内网地址：RFC1918 + 链路本地 + 回环
_INTERNAL_IPS = [
    "10.0.0.1", "10.206.88.2", "172.16.0.1", "172.19.0.5", "172.31.255.254",
    "192.168.1.10", "192.168.255.254", "169.254.0.1", "127.0.0.1",
    "fd00::1", "fdb8::1234", "fe80::1", "::1",
]
# 公网 / 非允许内网：必须拒绝
_EXTERNAL_IPS = [
    "8.8.8.8", "11.0.0.1", "1.2.3.4", "100.64.0.1", "223.5.5.5", "172.15.0.1", "172.32.0.1",
    "192.169.0.1", "2001:4860:4860::8888", "2400:3200::1",
]


@pytest.mark.parametrize("addr", _INTERNAL_IPS)
def test_internal_ip_true(addr):
    assert is_internal_ip(ipaddress.ip_address(addr)), addr


@pytest.mark.parametrize("addr", _EXTERNAL_IPS)
def test_internal_ip_false(addr):
    assert not is_internal_ip(ipaddress.ip_address(addr)), addr


def test_internal_network_true():
    for net in ["10.0.0.0/8", "10.206.0.0/28", "172.19.0.0/24", "192.168.0.0/16", "169.254.0.0/16"]:
        assert is_internal_network(ipaddress.ip_network(net)), net


def test_internal_network_false():
    for net in ["8.8.8.0/24", "11.0.0.0/16", "0.0.0.0/0", "172.32.0.0/12", "2001:4860::/32"]:
        assert not is_internal_network(ipaddress.ip_network(net)), net
