import http from './http'

export const statsApi = {
  overview: () => http.get('/stats/overview')
}
