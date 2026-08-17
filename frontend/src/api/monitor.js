import http from './http'

// 监控中心：设备 / IPAM / 告警 / 漏洞扫描（真实 nmap 探测）
export const monitorApi = {
  // 设备
  devices: (params) => http.get('/monitor/devices', { params }),
  createDevice: (data) => http.post('/monitor/devices', data),
  updateDevice: (id, data) => http.put(`/monitor/devices/${id}`, data),
  deleteDevice: (id, data) => http.delete(`/monitor/devices/${id}`, { data }),
  pingDevice: (id) => http.post(`/monitor/devices/${id}/ping`),
  exportDevices: () => http.get('/monitor/devices/export', { responseType: 'blob' }),
  importDevices: (formData) => http.post('/monitor/devices/import', formData),

  // IPAM
  subnets: () => http.get('/monitor/subnets'),
  createSubnet: (data) => http.post('/monitor/subnets', data),
  updateSubnet: (id, data) => http.put(`/monitor/subnets/${id}`, data),
  deleteSubnet: (id, data) => http.delete(`/monitor/subnets/${id}`, { data }),
  subnetUsage: (id) => http.get(`/monitor/subnets/${id}/usage`),
  allocations: (params) => http.get('/monitor/allocations', { params }),
  createAllocation: (data) => http.post('/monitor/allocations', data),
  updateAllocation: (id, data) => http.put(`/monitor/allocations/${id}`, data),
  releaseAllocation: (id) => http.delete(`/monitor/allocations/${id}`),
  recycleAllocations: () => http.post('/monitor/allocations/recycle'),
  allocationHistory: (ip) => http.get('/monitor/allocations/history', { params: { ip } }),

  // 网络发现
  discoverSubnet: (data) => http.post('/monitor/discover', data),
  discovery: (id) => http.get(`/monitor/discover/${id}`),
  discoveries: (params) => http.get('/monitor/discover', { params }),
  registerDiscovery: (id, data) => http.post(`/monitor/discover/${id}/register`, data),

  // 设备自动巡检（后台定时刷新设备状态）
  patrols: (params) => http.get('/monitor/patrols', { params }),

  // 告警
  alerts: (params) => http.get('/monitor/alerts', { params }),
  createAlert: (data) => http.post('/monitor/alerts', data),
  acknowledgeAlert: (id) => http.post(`/monitor/alerts/${id}/acknowledge`),
  resolveAlert: (id) => http.post(`/monitor/alerts/${id}/resolve`),

  // 漏洞扫描
  createScan: (data) => http.post('/monitor/scans', data),
  scanReports: (params) => http.get('/monitor/scans/reports', { params }),
  scanReport: (id) => http.get(`/monitor/scans/reports/${id}`),
  reviewScanReport: (id, approve) => http.post(`/monitor/scans/reports/${id}/review`, null, { params: { approve } }),

  // 扫描授权名单
  scanAuths: () => http.get('/monitor/scan-auth'),
  createScanAuth: (data) => http.post('/monitor/scan-auth', data),
  revokeScanAuth: (id) => http.post(`/monitor/scan-auth/${id}/revoke`)
}
