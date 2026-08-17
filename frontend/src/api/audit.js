import http from './http'

export const auditApi = {
  logs: (params) => http.get('/audit/logs', { params }),
  reportStats: (params) => http.get('/audit/reports/stats', { params }),
  createReport: (data) => http.post('/audit/reports', data),
  reports: (params) => http.get('/audit/reports', { params }),
  report: (id) => http.get(`/audit/reports/${id}`)
}
