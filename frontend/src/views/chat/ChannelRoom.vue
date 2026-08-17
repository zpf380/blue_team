<template>
  <div class="room">
    <div class="room-head">
      <el-button link @click="$router.back()">← 返回</el-button>
      <span class="title">{{ channel?.name || '频道' }}</span>
      <el-tag v-if="channel" :type="typeTag(channel.type)" size="small">{{ typeText(channel.type) }}</el-tag>
      <el-tag :type="wsTag" size="small">{{ wsText }}</el-tag>
      <div style="flex: 1"></div>
      <el-input v-model="kw" placeholder="搜索频道内消息" clearable size="small" style="width: 180px" @keyup.enter="doSearch" />
    </div>

    <div ref="listEl" class="msg-list" v-loading="loading">
      <MessageItem
        v-for="m in chat.messages"
        :key="m.id"
        :msg="m"
        :mine="m.sender_type === 'user' && m.sender_id === userStore.userInfo?.id"
        :can-recall="m.sender_type === 'user'"
        @recall="onRecall"
      />
    </div>

    <div class="composer">
      <div class="composer-bar">
        <el-button size="small" type="primary" plain :loading="aiLoading" @click="askAI">🤖 @AI 智能助手</el-button>
        <el-button size="small" @click="fileInput?.click()">📎 附件</el-button>
        <span v-if="uploading" class="hint">上传中…</span>
        <span v-if="aiLoading" class="hint">AI 正在思考…</span>
      </div>

      <div v-if="atSuggestions.length" class="at-list">
        <span v-for="u in atSuggestions" :key="u.id" class="at-item" @click="applyAt(u)">
          @{{ u.real_name || u.username }}
        </span>
      </div>

      <el-input
        ref="inputEl"
        v-model="draft"
        type="textarea"
        :rows="3"
        resize="none"
        placeholder="输入消息，@+姓名 可提醒对方，Enter 发送（Shift+Enter 换行）"
        @keydown.enter.exact.prevent="send"
        @input="onInput"
      />

      <div class="composer-foot">
        <span class="hint">支持 Markdown 与代码高亮</span>
        <el-button type="primary" :loading="sending" @click="send">发送</el-button>
      </div>
    </div>

    <input ref="fileInput" type="file" hidden accept=".png,.jpg,.jpeg,.gif,.webp,.bmp,.ico,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.csv,.txt,.md,.log,.zip,.rar,.7z,.tar,.gz" @change="onFile" />

    <el-dialog v-model="searchVisible" title="搜索结果" width="640px">
      <el-empty v-if="results.length === 0" description="无匹配消息" />
      <div v-for="r in results" :key="r.id" class="sr-item">
        <div class="sr-meta"><b>{{ r.sender_name || 'AI' }}</b><span class="sr-time">{{ formatTime(r.created_at) }}</span></div>
        <div class="sr-content">{{ r.content }}</div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { chatApi } from '@/api/chat'
import { aiApi } from '@/api/ai'
import { fileApi } from '@/api/files'
import { useChatStore } from '@/stores/chat'
import { useUserStore } from '@/stores/user'
import MessageItem from '@/components/chat/MessageItem.vue'

const props = defineProps({
  channel: { type: Object, default: null }
})

const route = useRoute()
const chat = useChatStore()
const userStore = useUserStore()

const channel = ref(null)
const loading = ref(false)
const draft = ref('')
const sending = ref(false)
const aiLoading = ref(false)
const uploading = ref(false)
const kw = ref('')

const members = ref([])        // @ 提醒候选（频道成员）
const atSuggestions = ref([])
const atRegex = /(?:^|\s)@([\p{L}\p{N}_]*)$/u

const listEl = ref(null)
const inputEl = ref(null)
const fileInput = ref(null)

let conversationId = null       // 本频道内 @AI 的会话上下文

const searchVisible = ref(false)
const results = ref([])

function typeText(t) { return { public: '公开', private: '私密', trainee: '学员社区' }[t] || t }
function typeTag(t) { return { public: 'success', private: 'warning', trainee: 'info' }[t] || 'info' }
const wsTag = computed(() => (chat.wsStatus === 'connected' ? 'success' : 'info'))
const wsText = computed(() => (chat.wsStatus === 'connected' ? '实时在线' : '连接中…'))
function formatTime(s) { return s ? new Date(s).toLocaleString('zh-CN', { hour12: false }) : '' }

async function init() {
  if (props.channel) {
    channel.value = props.channel
  } else {
    const id = Number(route.params.id)
    channel.value = chat.channels.find((c) => c.id === id) || null
    if (!channel.value && chat.channels.length === 0) await chat.loadChannels()
    channel.value = chat.channels.find((c) => c.id === id) || null
  }
  if (!channel.value) {
    ElMessage.error('频道不存在')
    return
  }
  loading.value = true
  try {
    await chat.openChannel(channel.value)
    members.value = await chatApi.members(channel.value.id)
    scrollBottom()
  } finally {
    loading.value = false
  }
}

// 新消息 → 滚到底部
watch(() => chat.messages.length, () => nextTick(scrollBottom))

function scrollBottom() {
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
}

function onInput() {
  const m = draft.value.match(atRegex)
  if (m) {
    const part = m[1].toLowerCase()
    const list = members.value.filter((u) => {
      const name = (u.real_name || u.username || '').toLowerCase()
      return !part || name.includes(part) || name.startsWith(part)
    })
    atSuggestions.value = list.slice(0, 6)
  } else {
    atSuggestions.value = []
  }
}

function applyAt(u) {
  const m = draft.value.match(atRegex)
  const name = u.real_name || u.username
  if (m) {
    draft.value = draft.value.slice(0, m.index) + '@' + name + ' '
  } else {
    draft.value = '@' + name + ' '
  }
  atSuggestions.value = []
  inputEl.value?.focus()
}

function collectMentions() {
  const ids = new Set()
  const alias = new Map()
  members.value.forEach((u) => {
    alias.set((u.real_name || '').trim(), u.id)
    alias.set((u.username || '').trim(), u.id)
  })
  const re = /@([\p{L}\p{N}_一-龥]+)/gu
  let m
  while ((m = re.exec(draft.value))) {
    const id = alias.get(m[1].trim())
    if (id) ids.add(id)
  }
  return [...ids]
}

async function send() {
  const content = draft.value.trim()
  if (!content) return
  sending.value = true
  try {
    await chat.sendMessage({ content, message_type: 'text', mentions: collectMentions() })
    draft.value = ''
    atSuggestions.value = []
  } finally {
    sending.value = false
  }
}

async function onRecall(msg) {
  try {
    await chat.recallMessage(msg.id)
    ElMessage.success('已撤回')
  } catch { /* 错误提示已由拦截器处理 */ }
}

async function askAI() {
  const query = draft.value.trim()
  if (!query) {
    ElMessage.warning('请先输入要询问的内容')
    return
  }
  aiLoading.value = true
  try {
    const data = await aiApi.invoke({
      query,
      channel_id: channel.value.id,
      conversation_id: conversationId,
      model_pref: undefined
    })
    conversationId = data.conversation_id
    draft.value = ''
    atSuggestions.value = []
    // WS 已广播 AI 回复；未连接时本地补一条
    if (chat.wsStatus !== 'connected') {
      chat.messages.push({
        id: `local-ai-${Date.now()}`,
        channel_id: channel.value.id,
        sender_id: null,
        sender_name: `AI·${data.provider}`,
        sender_type: 'ai_agent',
        ai_agent_name: data.provider,
        message_type: 'text',
        content: data.reply,
        is_deleted: false,
        created_at: new Date().toISOString()
      })
    }
    nextTick(scrollBottom)
  } finally {
    aiLoading.value = false
  }
}

const MAX_UPLOAD_MB = 100  // 与后端 UPLOAD_MAX_SIZE_MB 保持一致
const ALLOWED_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'ico', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'csv', 'txt', 'md', 'log', 'zip', 'rar', '7z', 'tar', 'gz'])

async function onFile(e) {
  const file = e.target.files?.[0]
  e.target.value = ''
  if (!file) return
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    ElMessage.warning(`文件不能超过 ${MAX_UPLOAD_MB}MB`)
    return
  }
  const ext = (file.name.split('.').pop() || '').toLowerCase()
  if (!ALLOWED_EXTS.has(ext)) {
    ElMessage.warning(`不支持的文件类型 .${ext}（仅允许图片/文档/压缩包等安全类型）`)
    return
  }
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const data = await fileApi.upload(fd)
    await chat.sendMessage({
      content: '',
      message_type: file.type.startsWith('image/') ? 'image' : 'file',
      file_url: data.url,
      file_name: data.filename
    })
    ElMessage.success('文件已发送')
  } catch { /* 错误提示已由拦截器处理 */ } finally {
    uploading.value = false
  }
}

async function doSearch() {
  if (!kw.value.trim()) return
  results.value = await chatApi.search({ q: kw.value.trim(), channel_id: channel.value.id })
  searchVisible.value = true
}

onMounted(init)
onBeforeUnmount(() => chat.dispose())
</script>

<style scoped>
.room { display: flex; flex-direction: column; height: calc(100vh - 120px); }
.room-head { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-bottom: 1px solid #ebeef5; background: #fff; }
.title { font-size: 15px; font-weight: 600; }

.msg-list { flex: 1; overflow-y: auto; background: #fff; padding: 6px 0; }

.composer { border-top: 1px solid #ebeef5; background: #fff; padding: 8px 12px; }
.composer-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.hint { font-size: 12px; color: #909399; }

.at-list { display: flex; flex-wrap: wrap; gap: 6px; padding: 4px 0; }
.at-item {
  cursor: pointer; padding: 2px 10px; border-radius: 12px; background: #ecf5ff;
  color: #1e6fff; font-size: 13px;
}
.at-item:hover { background: #d9ecff; }

.composer-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 6px; }

.sr-item { padding: 8px 10px; border-radius: 6px; }
.sr-item:hover { background: #f5f7fa; }
.sr-meta { font-size: 13px; color: #606266; display: flex; gap: 8px; align-items: center; }
.sr-time { color: #a8abb2; font-size: 12px; }
.sr-content { font-size: 14px; color: #303133; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
