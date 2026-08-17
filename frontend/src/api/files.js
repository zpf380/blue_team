import http from './http'

export const fileApi = {
  upload: (formData) => http.post('/files', formData)
}
