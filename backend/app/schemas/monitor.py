"""监控子系统 Schema：设备 / IPAM / 告警 / 扫描。"""
import datetime as dt
from typing import Optional

from pydantic import BaseModel, Field


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    ip_address: str = Field(min_length=1, max_length=45)
    mac_address: Optional[str] = None
    device_type: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    location: Optional[str] = None
    department_id: Optional[int] = None
    owner_id: Optional[int] = None
    snmp_community: Optional[str] = None
    status: str = Field(default="active", pattern="^(active|offline|maintenance|archived)$")


class DeviceDelete(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=200)  # 删除原因（审计留痕，可选）


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    mac_address: Optional[str] = None
    device_type: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    location: Optional[str] = None
    department_id: Optional[int] = None
    owner_id: Optional[int] = None
    snmp_community: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(active|offline|maintenance|archived)$")


class SubnetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    network: str = Field(min_length=1, max_length=45)
    gateway: Optional[str] = None  # 留空自动取子网第一个可用地址
    dns_servers: Optional[list[str]] = None
    vlan_id: Optional[int] = None
    department_id: Optional[int] = None
    reserved_ranges: Optional[list[str]] = None  # 保留地址段（CIDR 列表），自动分配跳过


class SubnetUpdate(BaseModel):
    name: Optional[str] = None
    gateway: Optional[str] = None  # 修改后自动分配/校验以新网关为准
    dns_servers: Optional[list[str]] = None
    vlan_id: Optional[int] = None
    department_id: Optional[int] = None
    reserved_ranges: Optional[list[str]] = None  # 传入即整体替换


class SubnetDelete(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=200)  # 删除原因（审计留痕，可选）


class AllocationCreate(BaseModel):
    subnet_id: Optional[int] = None
    ip_address: Optional[str] = None  # 留空自动从子网分配
    allocated_to: Optional[int] = None
    device_id: Optional[int] = None
    allocation_type: str = Field(default="static", pattern="^(static|dhcp|reserved)$")
    purpose: Optional[str] = None
    expires_at: Optional[dt.datetime] = None


class AllocationUpdate(BaseModel):
    purpose: Optional[str] = None
    allocated_to: Optional[int] = None
    device_id: Optional[int] = None
    allocation_type: Optional[str] = Field(default=None, pattern="^(static|dhcp|reserved)$")
    expires_at: Optional[dt.datetime] = None


class DiscoveryCreate(BaseModel):
    network: Optional[str] = Field(default=None, min_length=1, max_length=45)  # 目标网段 CIDR，如 "192.168.1.0/24"
    subnet_id: Optional[int] = None  # 可选：从已登记子网快捷选择时携带（此时可省略 network）


class DiscoveryRegister(BaseModel):
    ips: list[str] = Field(min_length=1, max_length=256)
    purpose: Optional[str] = None


class AlertCreate(BaseModel):
    device_id: Optional[int] = None
    alert_type: Optional[str] = None
    severity: str = Field(default="medium", pattern="^(critical|high|medium|low|info)$")
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class ScanAuthCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    network: str = Field(min_length=1, max_length=45)  # 授权网段 CIDR，如 192.168.10.0/24
    start_date: Optional[dt.datetime] = None
    end_date: Optional[dt.datetime] = None  # 到期自动失效
    note: Optional[str] = Field(default=None, max_length=200)


class ClientErrorReportIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    url: Optional[str] = Field(default=None, max_length=500)
    stack: Optional[str] = Field(default=None, max_length=20000)


class ScanCreate(BaseModel):
    target_ip: str = Field(min_length=1, max_length=45)
    report_type: str = Field(default="on_demand", pattern="^(daily|weekly|monthly|on_demand)$")
    device_id: Optional[int] = None
    ports: Optional[int] = Field(default=None, ge=1, le=10000)  # None → 用 NMAP_TOP_PORTS
    # 与 ports 二选一；语义校验在 API 层（_validate_port_range）
    port_range: Optional[str] = Field(default=None, max_length=200, pattern=r"^[0-9,\-]{1,200}$")
    # None → 用 NMAP_SCAN_TYPE
    scan_type: Optional[str] = Field(default=None, pattern="^(sS|sT|sU)$")
    # per-scan NSE 开关；实际生效还看 NMAP_NSE_SCRIPTS 是否非空
    nse: bool = True
