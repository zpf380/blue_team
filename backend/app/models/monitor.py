"""监控子系统：devices / ip_subnets / ip_allocations / alerts / scan_reports。"""
import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CIDR, INET, JSONB, MACADDR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (Index("idx_device_dept_owner", "department_id", "owner_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    ip_address: Mapped[str] = mapped_column(INET, unique=True, nullable=False)
    mac_address: Mapped[str | None] = mapped_column(MACADDR, nullable=True)
    device_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    snmp_community: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offline_since: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 自动巡检判定离线的时间
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IPSubnet(Base):
    __tablename__ = "ip_subnets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    network: Mapped[str] = mapped_column(CIDR, nullable=False)
    gateway: Mapped[str | None] = mapped_column(INET, nullable=True)
    dns_servers: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    vlan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    reserved_ranges: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # 保留地址段，如 ["10.0.10.100/28"]，自动分配跳过
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class IPAllocation(Base):
    __tablename__ = "ip_allocations"
    __table_args__ = (UniqueConstraint("ip_address"), Index("idx_ipalloc_subnet_active", "subnet_id", "is_active"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subnet_id: Mapped[int | None] = mapped_column(ForeignKey("ip_subnets.id"), nullable=True)
    ip_address: Mapped[str] = mapped_column(INET, nullable=False)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    allocated_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    allocation_type: Mapped[str] = mapped_column(String(20), default="static")  # static/dhcp/reserved
    purpose: Mapped[str | None] = mapped_column(String(200), nullable=True)
    allocated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("idx_alert_status_time", "status", "created_at"), Index("idx_alert_target_type", "target_ip", "alert_type"))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    target_ip: Mapped[str | None] = mapped_column(INET, nullable=True)  # 告警对象 IP（扫描自动告警必填，用于去重）
    alert_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open/acknowledged/resolved
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 外部通知发送成功时间
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClientErrorReport(Base):
    """前端运行时错误上报（全局 error/unhandledrejection 捕获），用于无日志环境下定位页面故障。"""
    __tablename__ = "client_error_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    stack: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScanAuthorization(Base):
    """扫描授权名单：管理员登记的允许扫描/发现的内网网段。

    目标必须在「active 子网台账」或「active 且未过期授权」范围内才能扫描；
    支持有效期（start_date/end_date）与吊销（status），到期/吊销自动失效。
    """
    __tablename__ = "scan_authorizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    network: Mapped[str] = mapped_column(CIDR, nullable=False)  # 授权网段，如 192.168.10.0/24
    status: Mapped[str] = mapped_column(String(16), default="active")  # active / revoked
    start_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 到期自动失效
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScanReport(Base):
    __tablename__ = "scan_reports"
    __table_args__ = (Index("idx_report_status_time", "status", "generated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # daily/weekly/monthly/on_demand
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    target_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    scan_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # pending_review / approved / rejected / archived
    status: Mapped[str] = mapped_column(String(20), default="pending_review")
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    generated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    file_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # pending / running / completed / failed —— 扫描执行生命周期（与 status 审核流正交）
    scan_status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)  # 失败原因（截断 500 字符）
    scan_options: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # 本次扫描生效选项快照（重试/漂移对比用）
    # cancelled / timeout / permission / unreachable / generic —— 失败原因分类（NULL=未失败）
    error_code: Mapped[str | None] = mapped_column(String(20), nullable=True)


class NetworkDiscovery(Base):
    """网络发现任务：对单个子网做主机发现，比对台账得出幽灵设备/在管/离线分组。

    一次发现 = 一个子网（pending/running/completed/failed）；结果分组在后台
    execute_discovery 完成后写回，供前端勾选确认登记。
    """
    __tablename__ = "network_discoveries"
    __table_args__ = (Index("idx_discovery_subnet_status", "subnet_id", "scan_status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subnet_id: Mapped[int | None] = mapped_column(ForeignKey("ip_subnets.id"), nullable=True)
    network: Mapped[str] = mapped_column(CIDR, nullable=False)  # 目标网段快照
    scan_status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)  # 失败原因（截断 500 字符）
    hosts: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # 在线终端元数据 [{ip, mac, vendor}]
    online_ips: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # 扫描在线 IP
    unregistered_ips: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # 在线未登记（幽灵设备）
    registered_ips: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # 在线已登记
    offline_ips: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # 已登记但当前不在线
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DevicePatrol(Base):
    """设备在线自动巡检：后台定时对 active 子网做主机发现，刷新设备在线状态。

    与 NetworkDiscovery（手动、登记流程）不同：巡检是纯状态刷新（在线→active/未响应→offline），
    不产生登记，仅把每轮结果（在线/离线/幽灵 IP 分组）落库供追溯与展示。
    """
    __tablename__ = "device_patrols"
    __table_args__ = (Index("idx_patrol_subnet_status", "subnet_id", "scan_status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subnet_id: Mapped[int | None] = mapped_column(ForeignKey("ip_subnets.id"), nullable=True)
    network: Mapped[str] = mapped_column(CIDR, nullable=False)  # 目标网段快照
    scan_status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)  # 失败原因（截断 500 字符）
    online_ips: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # 本轮在线 IP
    offline_ips: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # 台账在册但本轮未响应
    ghost_ips: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # 在线但未登记（幽灵设备）
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
