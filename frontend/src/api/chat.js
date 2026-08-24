import http from './http'

export const chatApi = {
  channels: () => http.get('/channels'),
  createChannel: (data) => http.post('/channels', data),
  joinChannel: (name) => http.post('/channels/join', { name }),
  members: (id) => http.get(`/channels/${id}/members`),
  messages: (id, params) => http.get(`/channels/${id}/messages`, { params }),
  send: (id, data) => http.post(`/channels/${id}/messages`, data),
  read: (id) => http.post(`/channels/${id}/read`),
  recall: (id) => http.post(`/messages/${id}/recall`),
  search: (params) => http.get('/chat/search', { params }),
  dm: (user_id) => http.post('/channels/dm', { user_id }),
  candidates: (params) => http.get('/chat/users', { params }),
  // 联系人
  contacts: () => http.get('/chat/contacts'),
  contactRequests: () => http.get('/chat/contacts/requests'),
  sendContactRequest: (target_id) => http.post('/chat/contacts/requests', { target_id }),
  acceptContactRequest: (id) => http.post(`/chat/contacts/requests/${id}/accept`),
  rejectContactRequest: (id) => http.post(`/chat/contacts/requests/${id}/reject`),
  removeContact: (id) => http.delete(`/chat/contacts/${id}`)
}
