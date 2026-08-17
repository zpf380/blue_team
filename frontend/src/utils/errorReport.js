import axios from 'axios'

// 前端运行时错误上报：捕获全局 error / unhandledrejection，静默上报后端。
// 独立 axios（不经过 http.js 拦截器）→ 不上报失败不弹 ElMessage、不触发 401 刷新逻辑。
// 每会话限 50 条，防错误风暴刷爆数据库。
const MAX_REPORTS = 50
let reported = 0

function send(type, e) {
  if (reported >= MAX_REPORTS) return
  reported += 1
  const err = e || {}
  const message = `[${type}] ${err?.message || String(e) || '未知错误'}`.slice(0, 1000)
  const payload = {
    message,
    url: window.location.href.slice(0, 500),
    stack: err?.stack ? err.stack.slice(0, 20000) : undefined
  }
  axios
    .post('/api/v1/monitor/client-errors', payload, {
      withCredentials: true,
      headers: { 'X-Requested-With': 'XMLHttpRequest' }  // Cookie 会话下识别 user_id（CSRF 双重防护要求）
    })
    .catch(() => {})  // 上报失败静默，绝不影响页面
}

export function initErrorReporting() {
  window.addEventListener('error', (ev) => send('error', ev.error || ev.message))
  window.addEventListener('unhandledrejection', (ev) => send('promise', ev.reason))
}
