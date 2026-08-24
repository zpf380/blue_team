import axios from 'axios'
import { ElMessage } from 'element-plus'

// 统一 axios 实例：
// - 会话令牌存于 HttpOnly Cookie（同源请求自动携带），JS 不再管理 token；
// - 写操作附加 X-Requested-With 头，满足后端 Cookie 认证的 CSRF 双重校验；
// - 统一解包 {code,message,data}，认证失效（HTTP 401 或业务码 40100）自动刷新（Cookie 轮换）后重试一次。
const ERR_UNAUTHORIZED = 40100
const http = axios.create({ baseURL: '/api/v1', timeout: 20000, withCredentials: true })

http.interceptors.request.use((config) => {
  const method = (config.method || 'get').toLowerCase()
  if (!['get', 'head', 'options'].includes(method)) {
    config.headers['X-Requested-With'] = 'XMLHttpRequest'
  }
  return config
})

async function refreshToken() {
  try {
    // refresh 令牌同样在 HttpOnly Cookie 中，后端优先从 Cookie 读取
    const resp = await axios.post('/api/v1/auth/refresh', {}, { withCredentials: true, timeout: 20000, headers: { 'X-Requested-With': 'XMLHttpRequest' } })
    return resp.data && resp.data.code === 0
  } catch {
    return false
  }
}

// 正在进行的刷新，避免并发 401 时重复刷新
let refreshing = null

// 业务 40100 也走令牌刷新重试一次（后端 AppError 统一返回 HTTP 200，故仅看 HTTP 401 会漏）
async function refreshAndRetry(config) {
  if (!refreshing) {
    refreshing = refreshToken().finally(() => { refreshing = null })
  }
  const ok = await refreshing
  if (ok) {
    config._retried = true
    return http(config)
  }
  window.location.href = '/login'
  throw new Error('认证已过期，请重新登录')
}

http.interceptors.response.use(
  async (resp) => {
    const body = resp.data
    if (body && typeof body.code === 'number') {
      if (body.code === ERR_UNAUTHORIZED && resp.config && !resp.config._retried && resp.config.url !== '/auth/login') {
        return refreshAndRetry(resp.config)
      }
      if (body.code !== 0) {
        ElMessage.error(body.message || '请求失败')
        return Promise.reject(new Error(body.message || '请求失败'))
      }
      return body.data
    }
    return body
  },
  async (error) => {
    const { config, response } = error
    if (response?.status === 401 && config && !config._retried && config.url !== '/auth/login') {
      try {
        return await refreshAndRetry(config)
      } catch (e) {
        return Promise.reject(e)
      }
    }
    if (config?.url !== '/auth/login') {
      const msg = response?.data?.message || error.message || '网络错误'
      ElMessage.error(msg)
    }
    return Promise.reject(error)
  }
)

export default http
