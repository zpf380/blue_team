import http from './http'

export const departmentApi = {
  tree: () => http.get('/departments/tree'),
  create: (data) => http.post('/departments', data),
  update: (id, data) => http.put(`/departments/${id}`, data),
  remove: (id) => http.delete(`/departments/${id}`)
}
