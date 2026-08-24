import { defineStore } from 'pinia'
import { ElNotification } from 'element-plus'
import { ref } from 'vue'
import { chatApi } from '@/api/chat'
import { ChatSocket } from '@/utils/ws'

export const useChatStore = defineStore('chat', () => {
  const channels = ref([])
  const currentChannel = ref(null)
  const messages = ref([])
  const wsStatus = ref('idle')
  const socket = ref(null)
  const mentionCount = ref(0)

  async function loadChannels() {
    channels.value = await chatApi.channels()
    return channels.value
  }

  async function openChannel(channel) {
    currentChannel.value = channel
    const data = await chatApi.messages(channel.id)
    messages.value = data.items
    chatApi.read(channel.id).catch(() => {})
    connectWs(channel.id)
  }

  function wsUrl(channelId) {
    // 认证令牌在 HttpOnly Cookie 中，同源 WebSocket 握手自动携带
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    return `${proto}://${window.location.host}/ws/chat/${channelId}`
  }

  function connectWs(channelId) {
    socket.value?.close()
    const s = new ChatSocket(wsUrl(channelId), {
      onMessage: handleMessage,
      onStatus: (st) => {
        wsStatus.value = st
      }
    })
    socket.value = s
    s.connect()
  }

  function handleMessage(payload) {
    if (payload.type === 'message') {
      const m = payload.data
      if (m.channel_id === currentChannel.value?.id) {
        messages.value.push(m)
      }
    } else if (payload.type === 'recall') {
      const idx = messages.value.findIndex((m) => m.id === payload.data.message_id)
      if (idx >= 0) messages.value[idx] = { ...messages.value[idx], is_deleted: true, content: null }
    } else if (payload.type === 'mention') {
      mentionCount.value += 1
      ElNotification({
        title: '@ 提及',
        message: `${payload.data.from} 在 ${payload.data.channel_name} @了你：${payload.data.preview}`,
        type: 'warning',
        duration: 5000
      })
    } else if (payload.type === 'system') {
      // 系统消息（入频道/离开频道等）：WS 按频道连接，收到的即当前频道，直接插入列表
      if (currentChannel.value) {
        messages.value.push({
          id: `sys-${Date.now()}`,
          channel_id: currentChannel.value.id,
          sender_id: null,
          sender_name: '系统',
          sender_type: 'system',
          message_type: 'text',
          content: payload.data?.text || '',
          is_deleted: false,
          created_at: new Date().toISOString()
        })
      }
    }
  }

  async function sendMessage(payload) {
    const msg = await chatApi.send(currentChannel.value.id, payload)
    // 后端会经 WS 广播回显；WS 未连时本地补一条
    if (wsStatus.value !== 'connected') messages.value.push(msg)
    return msg
  }

  async function recallMessage(id) {
    await chatApi.recall(id)
    const idx = messages.value.findIndex((m) => m.id === id)
    if (idx >= 0) messages.value[idx] = { ...messages.value[idx], is_deleted: true, content: null }
  }

  function dispose() {
    socket.value?.close()
    socket.value = null
  }

  return {
    channels, currentChannel, messages, wsStatus, mentionCount,
    loadChannels, openChannel, sendMessage, recallMessage, dispose
  }
})
