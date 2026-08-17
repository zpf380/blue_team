// WebSocket 聊天客户端：自动重连（指数退避）+ 30s 心跳
export class ChatSocket {
  constructor(url, { onMessage, onStatus } = {}) {
    this.url = url
    this.onMessage = onMessage
    this.onStatus = onStatus
    this.ws = null
    this.heartbeatTimer = null
    this.reconnectTimer = null
    this.retry = 0
    this.closed = false
  }

  connect() {
    this.closed = false
    const ws = new WebSocket(this.url)
    this.ws = ws

    ws.onopen = () => {
      this.retry = 0
      this.onStatus?.('connected')
      this.startHeartbeat()
    }
    ws.onmessage = (e) => {
      let data
      try {
        data = JSON.parse(e.data)
      } catch {
        return
      }
      if (data.type === 'pong') return
      this.onMessage?.(data)
    }
    ws.onclose = () => {
      this.stopHeartbeat()
      this.onStatus?.('disconnected')
      if (!this.closed) this.scheduleReconnect()
    }
    ws.onerror = () => {
      try {
        ws.close()
      } catch { /* 忽略 */ }
    }
  }

  startHeartbeat() {
    this.stopHeartbeat()
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }))
      }
    }, 30000)
  }

  stopHeartbeat() {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer)
    this.heartbeatTimer = null
  }

  scheduleReconnect() {
    if (this.reconnectTimer) return
    const delay = Math.min(30000, 1000 * 2 ** this.retry)
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.retry += 1
      this.connect()
    }, delay)
  }

  close() {
    this.closed = true
    this.stopHeartbeat()
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    try {
      this.ws?.close()
    } catch { /* 忽略 */ }
  }

  send(obj) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(obj))
      return true
    }
    return false
  }
}
