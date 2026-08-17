import { defineStore } from 'pinia'
import { ElNotification } from 'element-plus'
import { ref } from 'vue'
import router from '@/router'
import { ChatSocket } from '@/utils/ws'

// 全局通知：连接 /ws/notifications（需要 training:agent:view 权限的学员/分析师）。
// 收到「新课程发布」推送 → 弹通知 + 自增 refreshVersion 供页面刷新。
export const useNotificationsStore = defineStore('notifications', () => {
  const socket = ref(null)
  const connected = ref(false)
  const refreshVersion = ref(0)

  function wsUrl() {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    return `${proto}://${window.location.host}/ws/notifications`
  }

  function connect() {
    if (socket.value) return
    const s = new ChatSocket(wsUrl(), {
      onMessage: handleMessage,
      onStatus: (st) => {
        connected.value = st === 'connected'
      }
    })
    socket.value = s
    s.connect()
  }

  function handleMessage(payload) {
    if (payload.type === 'training_course_published') {
      const d = payload.data || {}
      refreshVersion.value += 1
      ElNotification({
        title: '📚 新课程发布',
        message: `《${d.name}》已上线，共 ${d.scenario_count} 个场景，点击前往训练。`,
        type: 'success',
        duration: 8000,
        onClick: () => router.push('/training/agents')
      })
    }
  }

  function dispose() {
    socket.value?.close()
    socket.value = null
  }

  return { connected, refreshVersion, connect, dispose }
})
