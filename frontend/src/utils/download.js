import { ElMessage } from 'element-plus'

// 下载受保护资源：会话令牌在 HttpOnly Cookie（同源 fetch 自动携带），
// 附加 X-Requested-With 头满足后端 CSRF 双重校验；结果以 blob 触发浏览器下载。
export async function downloadWithAuth(url, filename) {
  const resp = await fetch(url, {
    headers: { 'X-Requested-With': 'XMLHttpRequest' }
  })
  if (!resp.ok) {
    ElMessage.error(`下载失败（HTTP ${resp.status}）`)
    throw new Error('download failed')
  }
  const blob = await resp.blob()
  const objectUrl = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = objectUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(objectUrl)
}
