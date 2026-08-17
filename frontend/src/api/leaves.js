import http from './http'

// 考勤管理：休假/外勤申请与审批
export const leaveApi = {
  create: (data) => http.post('/leaves', data),
  mine: (params) => http.get('/leaves/mine', { params }),
  cancel: (id) => http.post(`/leaves/${id}/cancel`),
  list: (params) => http.get('/leaves', { params }),
  approve: (id, data) => http.post(`/leaves/${id}/approve`, data),
  reject: (id, data) => http.post(`/leaves/${id}/reject`, data)
}
