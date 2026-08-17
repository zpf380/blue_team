import http from './http'

export const aiApi = {
  invoke: (data) => http.post('/ai/invoke', data),
  conversations: () => http.get('/ai/conversations'),
  conversation: (id) => http.get(`/ai/conversations/${id}`),
  removeConversation: (id) => http.delete(`/ai/conversations/${id}`)
}
