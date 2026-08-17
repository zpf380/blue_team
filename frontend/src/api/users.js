import http from './http'

export const userApi = {
  list: (params) => http.get('/users', { params }),
  create: (data) => http.post('/users', data),
  update: (id, data) => http.put(`/users/${id}`, data),
  remove: (id) => http.delete(`/users/${id}`),
  tree: () => http.get('/departments/tree'),
  roles: () => http.get('/roles'),
  import: (formData) => http.post('/users/import', formData)
}
