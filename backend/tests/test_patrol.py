"""设备自动巡检测试：_classify_ledger 纯函数 + patrol_all_subnets 集成（状态刷新/分组落库/并发跳过）。"""
import datetime as dt
import ipaddress
import uuid

import pytest
from sqlalchemy import delete, select

from app.models import Device, DevicePatrol, IPAllocation, IPSubnet
from app.services import patrol as patrol_mod
from app.services.patrol import _classify_ledger


async def _clear_network_residue(session, net: str) -> None:
    """清理目标网段内的测试残留台账，保证巡检测试可重复运行。"""
    net = ipaddress.ip_network(net)
    ips = [str(net.network_address + i) for i in range(1, net.num_addresses)]
    await session.execute(delete(IPAllocation).where(IPAllocation.ip_address.in_(ips)))
    await session.execute(delete(Device).where(Device.ip_address.in_(ips)))
    await session.execute(delete(DevicePatrol).where(DevicePatrol.network == str(net)))
    await session.execute(delete(IPSubnet).where(IPSubnet.network == str(net)))
    await session.commit()


# ---------- 纯函数 ----------
def test_classify_ledger():
    net = "10.200.8.0/28"
    base = ipaddress.ip_network(net).network_address
    b = [str(base + i) for i in range(8)]
    # 在线：.2/.3/.4；台账设备：.2/.5/.6（.4 在线但未登记=幽灵）
    groups = _classify_ledger([b[2], b[3], b[4]], net, {b[2], b[5], b[6]}, set())
    assert groups["online"] == [b[2], b[3], b[4]]
    assert groups["ghost"] == [b[3], b[4]]      # 在线未登记
    assert groups["offline"] == [b[5], b[6]]    # 台账在册未响应
    # 网段外 IP 不计入（如 10.99.1.1 不在 /28 内）
    groups2 = _classify_ledger(["10.99.1.1", b[2]], net, {b[2]}, set())
    assert groups2["online"] == [b[2]]
    assert groups2["ghost"] == []


# ---------- 集成：状态刷新 + 分组落库 ----------
@pytest.mark.asyncio
async def test_patrol_updates_device_statuses(client, test_session, monkeypatch):
    """在线→active+last_seen 刷新；未响应→offline+offline_since；maintenance/archived 跳过。"""
    a = 200 + int(uuid.uuid4().hex[:2], 16) % 3
    b2 = int(uuid.uuid4().hex[:4], 16) % 250
    net = f"10.{a}.{b2}.0/28"
    await _clear_network_residue(test_session, net)
    base = ipaddress.ip_network(net).network_address
    ip = lambda i: str(base + i)  # noqa: E731 本网段第 i 个主机 IP

    now = dt.datetime(2026, 8, 16, 10, 30, tzinfo=dt.timezone.utc)
    earlier = now - dt.timedelta(days=1)

    # 台账设备：.2 在线（曾离线）、.5 未响应、.6 维护、.7 已归档
    test_session.add_all([
        Device(name="巡检-在线", ip_address=ip(2), status="offline", last_seen_at=earlier, offline_since=earlier),
        Device(name="巡检-离线", ip_address=ip(5), status="active"),
        Device(name="巡检-维护", ip_address=ip(6), status="maintenance"),
        Device(name="巡检-归档", ip_address=ip(7), status="archived"),
    ])
    sub = IPSubnet(name="巡检子网", network=net, is_active=True)
    test_session.add(sub)
    await test_session.commit()

    async def _fake_discovery(network):
        if network == net:
            return 0, (
                f'<?xml version="1.0"?><nmaprun scanner="nmap" version="7.94">'
                f'<host><status state="up"/><address addr="{ip(2)}" addrtype="ipv4"/></host>'
                f'<host><status state="up"/><address addr="{ip(3)}" addrtype="ipv4"/></host>'
                f'</nmaprun>'
            )
        return 0, '<?xml version="1.0"?><nmaprun scanner="nmap" version="7.94"></nmaprun>'
    monkeypatch.setattr("app.services.scanner._run_host_discovery", _fake_discovery)

    stats = await patrol_mod.patrol_all_subnets(now=now)

    assert stats["skipped"] is False
    assert stats["online"] == 2  # .2/.3（含幽灵）
    assert stats["ghost"] == 1   # .3 在线未登记
    assert stats["offline"] >= 3  # 含本网 .5/.6/.7 + 种子网设备（不精确断言总数）

    # 状态刷新断言
    on = (await test_session.execute(select(Device).where(Device.name == "巡检-在线"))).scalar_one()
    assert on.status == "active" and on.last_seen_at == now and on.offline_since is None
    off = (await test_session.execute(select(Device).where(Device.name == "巡检-离线"))).scalar_one()
    assert off.status == "offline" and off.offline_since == now
    maint = (await test_session.execute(select(Device).where(Device.name == "巡检-维护"))).scalar_one()
    assert maint.status == "maintenance" and maint.offline_since is None  # 维护跳过不覆盖
    arch = (await test_session.execute(select(Device).where(Device.name == "巡检-归档"))).scalar_one()
    assert arch.status == "archived" and arch.offline_since is None  # 归档跳过不覆盖

    # 巡检行落库：分组与状态
    p = (await test_session.execute(
        select(DevicePatrol).where(DevicePatrol.subnet_id == sub.id).order_by(DevicePatrol.id.desc()).limit(1)
    )).scalar_one()
    assert p.scan_status == "completed"
    assert p.online_ips == [ip(2), ip(3)]
    assert p.ghost_ips == [ip(3)]
    assert p.offline_ips == [ip(5), ip(6), ip(7)]
    assert p.started_at == now and p.completed_at == now


@pytest.mark.asyncio
async def test_patrol_skips_when_previous_round_running(client):
    """上一轮巡检未结束（_patrol_running 标志置位）→ 本轮直接跳过，不做任何 DB 操作。"""
    patrol_mod._patrol_running = True
    try:
        stats = await patrol_mod.patrol_all_subnets(now=dt.datetime(2026, 8, 16, tzinfo=dt.timezone.utc))
        assert stats["skipped"] is True
        assert stats["subnets"] == 0
    finally:
        patrol_mod._patrol_running = False
