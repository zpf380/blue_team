"""设备在线自动巡检：后台定时对 active 子网做主机发现，刷新设备在线状态。

与 NetworkDiscovery（手动、登记流程）不同：巡检是纯状态刷新（在线→active / 未响应→offline），
不产生登记，仅把每轮结果（在线/离线/幽灵 IP 分组）落 device_patrols 供追溯与展示。

- 子进程边界复用 scanner._run_host_discovery / _parse_nmap_hosts / SCAN_SEM（同扫描/发现共享）。
- `_classify_ledger` 为纯函数（NetworkDiscovery.execute_discovery 同款比对逻辑），便于单测。
- `_patrol_running` 模块级标志：上一轮未结束则本轮跳过，防长轮询重叠。
"""
import asyncio
import datetime as dt
import ipaddress

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models import Device, DevicePatrol, IPAllocation, IPSubnet
from app.services import scanner

_patrol_running = False


def _classify_ledger(online_ips: list[str], network: str, device_ips: set[str], allocation_ips: set[str]) -> dict:
    """比对在线 IP 与台账（设备 IP ∪ active 分配 IP），返回 registered / ghost / offline 三组。

    纯函数（同 NetworkDiscovery.execute_discovery 的分类逻辑）：
    - online：本轮在线
    - ghost：在线但未登记（幽灵设备）
    - offline：台账在册但本轮未响应
    """
    net = ipaddress.ip_network(network)

    def _in_net(ip_str: str) -> bool:
        try:
            return ipaddress.ip_address(ip_str) in net
        except ValueError:
            return False

    registered_set = {ip for ip in (allocation_ips | device_ips) if _in_net(ip)}
    in_net_online = {ip for ip in online_ips if _in_net(ip)}  # 仅统计网段内在线（nmap 只报本网段，纯函数兜底）
    return {
        "online": sorted(in_net_online),
        "ghost": sorted(in_net_online - registered_set),
        "offline": sorted(registered_set - in_net_online),
    }


async def patrol_all_subnets(now: dt.datetime | None = None) -> dict:
    """遍历全部 active 子网做一轮巡检：刷新设备状态并逐子网写 device_patrols 行。

    状态规则（用户已确认直接复用状态列）：
    - 在线：status='active'、last_seen_at=now、offline_since=None
    - 未响应且 status not in (maintenance, archived)：status='offline'、offline_since 首次判定才落值
    - maintenance / archived 跳过不覆盖（停机维护设备不因未响应被置离线）

    返回 {skipped, subnets, online, ghost, offline}；上一轮仍在跑时 skipped=True 直接返回。
    """
    global _patrol_running
    if _patrol_running:
        return {"skipped": True, "subnets": 0, "online": 0, "ghost": 0, "offline": 0}
    _patrol_running = True
    now = now or dt.datetime.now(dt.timezone.utc)
    stats = {"skipped": False, "subnets": 0, "online": 0, "ghost": 0, "offline": 0}
    try:
        # 整轮使用单一 session：设备对象全程在会话内，逐子网 commit 一并落库状态刷新与巡检行
        # （expire_on_commit=False，commit 后对象不失效，后续子网仍可直接修改再 commit）
        async with AsyncSessionLocal() as session:
            subnets = (await session.execute(
                select(IPSubnet).where(IPSubnet.is_active.is_(True))
            )).scalars().all()
            if not subnets:
                return stats
            # 台账一次全量取出供各子网复用（INET/CIDR 列读回 ipaddress 对象，统一 str 归一化）
            dev_ips = {str(x) for x in (await session.execute(select(Device.ip_address))).scalars()}
            alloc_ips = {str(a.ip_address) for a in (await session.execute(
                select(IPAllocation).where(IPAllocation.is_active.is_(True))
            )).scalars()}
            devices = {str(d.ip_address): d for d in (await session.execute(select(Device))).scalars()}

            for sub in subnets:
                network = str(sub.network)
                patrol = DevicePatrol(subnet_id=sub.id, network=network, scan_status="running", started_at=now)
                session.add(patrol)
                try:
                    async with scanner.SCAN_SEM:
                        _rc, stdout = await scanner._run_host_discovery(network)
                    hosts = scanner._parse_nmap_hosts(stdout)
                    groups = _classify_ledger([h["ip"] for h in hosts], network, dev_ips, alloc_ips)

                    for ip in groups["online"]:
                        d = devices.get(ip)
                        if d and d.status in ("active", "offline"):
                            d.status, d.last_seen_at, d.offline_since = "active", now, None
                    for ip in groups["offline"]:
                        d = devices.get(ip)
                        if d and d.status not in ("maintenance", "archived"):
                            d.status = "offline"
                            d.offline_since = d.offline_since or now

                    patrol.online_ips, patrol.ghost_ips, patrol.offline_ips = (
                        groups["online"], groups["ghost"], groups["offline"])
                    patrol.scan_status = "completed"
                    patrol.completed_at = now
                    stats["online"] += len(groups["online"])
                    stats["ghost"] += len(groups["ghost"])
                    stats["offline"] += len(groups["offline"])
                except asyncio.TimeoutError:
                    patrol.scan_status, patrol.error = "failed", f"发现超时（>{settings.NMAP_HOST_TIMEOUT}s）"
                except Exception as e:  # noqa: BLE001 —— 单个子网失败不拖垮整轮，其余子网照常巡检
                    patrol.scan_status, patrol.error = "failed", str(e)[:500]
                stats["subnets"] += 1
                await session.commit()
    finally:
        _patrol_running = False
    return stats
