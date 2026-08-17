<template>
  <div class="ai-page">
    <!-- 会话列表侧栏 -->
    <aside class="ai-side">
      <div class="ai-side-head">
        <span class="ai-side-title">会话历史</span>
        <el-button type="primary" size="small" @click="newChat">＋ 新会话</el-button>
      </div>
      <div class="ai-conv-list">
        <div v-if="conversations.length === 0" class="ai-conv-empty">暂无历史会话<br />提问后自动保存</div>
        <div
          v-for="c in conversations"
          :key="c.id"
          class="ai-conv"
          :class="{ active: c.id === currentId }"
          @click="openConv(c.id)"
        >
          <div class="ai-conv-title">{{ c.title || '新会话' }}</div>
          <div class="ai-conv-meta">{{ c.message_count }} 轮 · {{ fmtTime(c.updated_at) }}</div>
          <el-button link type="danger" size="small" class="ai-conv-del" @click.stop="removeConv(c)">删除</el-button>
        </div>
      </div>
    </aside>

    <!-- 聊天主区 -->
    <div class="ai-main">
      <div class="ai-head">
        <span class="title">🤖 AI 安全助手</span>
        <span class="sub">蓝队防御专家 · DeepSeek 为主，Ollama 降级</span>
        <div style="flex: 1"></div>
        <el-select v-model="modelPref" size="small" style="width: 150px">
          <el-option label="自动选择" value="" />
          <el-option label="DeepSeek" value="deepseek" />
          <el-option label="Ollama 本地" value="ollama" />
        </el-select>
      </div>

      <div ref="listEl" class="ai-list">
        <div v-if="turns.length === 0" class="ai-empty">
          <div class="logo">🛡️</div>
          <p>我是蓝队业务系统的 AI 安全助手，可以帮你：</p>
          <ul>
            <li>分析安全日志与告警，判断攻击类型与处置建议</li>
            <li>解释漏洞原理、危害与修复方案</li>
            <li>编写/优化检测规则、应急响应预案</li>
            <li>回答网络攻防、合规审计类问题</li>
          </ul>
        </div>

        <div v-for="(t, i) in turns" :key="i" class="ai-turn" :class="t.role">
          <div class="ai-avatar">{{ t.role === 'user' ? '我' : '🤖' }}</div>
          <div class="ai-body">
            <div class="ai-meta">
              <span v-if="t.role === 'ai'" class="ai-name">AI · {{ providerLabel(t.provider) }}</span>
              <span v-else class="ai-name">我</span>
              <el-tag v-if="t.role === 'ai' && t.provider" size="small" :type="providerTag(t.provider)">{{ providerLabel(t.provider) }}</el-tag>
            </div>
            <div class="ai-bubble">
              <MarkdownText v-if="t.role === 'ai'" :text="t.content" />
              <div v-else class="user-text">{{ t.content }}</div>
            </div>
            <div v-if="t.role === 'ai'" class="ai-ops">
              <el-button link size="small" @click="copyText(t.content)">复制</el-button>
              <el-button link size="small" :loading="regenerating === i" @click="regenerate(i)">重新生成</el-button>
            </div>
          </div>
        </div>

        <div v-if="loading" class="ai-turn ai">
          <div class="ai-avatar">🤖</div>
          <div class="ai-body">
            <div class="ai-bubble typing"><span class="dot" /><span class="dot" /><span class="dot" /></div>
          </div>
        </div>
      </div>

      <div class="ai-input">
        <el-input
          ref="inputEl"
          v-model="draft"
          type="textarea"
          :rows="3"
          resize="none"
          placeholder="向 AI 安全助手提问，Enter 发送（Shift+Enter 换行）"
          @keydown.enter.exact.prevent="send"
        />
        <div class="ai-input-foot">
          <span class="hint">模型不可用时自动降级，不会中断</span>
          <el-button type="primary" :loading="loading" @click="send">发送</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { aiApi } from '@/api/ai'
import MarkdownText from '@/components/chat/MarkdownText.vue'

const draft = ref('')
const loading = ref(false)
const modelPref = ref('')
const turns = ref([])
const regenerating = ref(-1)
const listEl = ref(null)
const inputEl = ref(null)

// 会话管理：列表 + 当前会话 id（null = 未选择，将新建）
const conversations = ref([])
const currentId = ref(null)

function providerLabel(p) {
  return { deepseek: 'DeepSeek', ollama: 'Ollama', fallback: '本地兜底' }[p] || p || 'AI'
}
function providerTag(p) {
  return { deepseek: 'warning', ollama: 'success', fallback: 'info' }[p] || 'info'
}

function fmtTime(t) {
  if (!t) return ''
  const d = new Date(t)
  const now = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return d.toDateString() === now.toDateString()
    ? `${p(d.getHours())}:${p(d.getMinutes())}`
    : `${d.getMonth() + 1}/${d.getDate()}`
}

async function scrollBottom() {
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
}

async function refreshList() {
  const data = await aiApi.conversations()
  conversations.value = data.items || []
}

async function send() {
  const query = draft.value.trim()
  if (!query || loading.value) return
  turns.value.push({ role: 'user', content: query })
  draft.value = ''
  loading.value = true
  await scrollBottom()
  try {
    const data = await aiApi.invoke({
      query,
      model_pref: modelPref.value || undefined,
      conversation_id: currentId.value || undefined
    })
    turns.value.push({ role: 'ai', content: data.reply, provider: data.provider })
    // 新会话时后端返回新 conversation_id，记住它；已续接则不变
    if (data.conversation_id) currentId.value = data.conversation_id
    await refreshList()
    await scrollBottom()
  } finally {
    loading.value = false
  }
}

async function regenerate(i) {
  const userTurn = turns.value[i - 1]
  if (!userTurn) return
  regenerating.value = i
  try {
    // 以当前会话重新生成（模型偏好保持一致），后端会追加一轮新回复
    const data = await aiApi.invoke({
      query: userTurn.content,
      model_pref: modelPref.value || undefined,
      conversation_id: currentId.value || undefined
    })
    turns.value[i] = { role: 'ai', content: data.reply, provider: data.provider }
    await refreshList()
    await scrollBottom()
  } finally {
    regenerating.value = -1
  }
}

function newChat() {
  currentId.value = null
  turns.value = []
  draft.value = ''
  inputEl.value?.focus()
}

async function openConv(id) {
  if (id === currentId.value && turns.value.length > 0) return
  try {
    const data = await aiApi.conversation(id)
    turns.value = (data.messages || []).map((m) =>
      m.role === 'user'
        ? { role: 'user', content: m.content }
        : { role: 'ai', content: m.content, provider: undefined }
    )
    currentId.value = id
    await scrollBottom()
  } catch { /* 拦截器已提示 */ }
}

async function removeConv(c) {
  try {
    await ElMessageBox.confirm(`确认删除会话「${c.title || '新会话'}」？删除后不可恢复。`, '删除会话', { type: 'warning' })
  } catch {
    return
  }
  try {
    await aiApi.removeConversation(c.id)
    conversations.value = conversations.value.filter((x) => x.id !== c.id)
    if (currentId.value === c.id) {
      currentId.value = null
      turns.value = []
      const next = conversations.value[0]
      if (next) await openConv(next.id)
    }
    ElMessage.success('已删除')
  } catch { /* 拦截器已提示 */ }
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text || '')
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败')
  }
}

onMounted(async () => {
  try {
    await refreshList()
    // 切回页面自动续接最近一次会话
    if (conversations.value.length > 0) await openConv(conversations.value[0].id)
  } finally {
    inputEl.value?.focus()
  }
})
</script>

<style scoped>
.ai-page { display: flex; height: calc(100vh - 120px); background: #fff; border-radius: 8px; overflow: hidden; }

.ai-side { width: 240px; flex-shrink: 0; border-right: 1px solid #ebeef5; display: flex; flex-direction: column; }
.ai-side-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; border-bottom: 1px solid #ebeef5; }
.ai-side-title { font-size: 14px; font-weight: 600; }
.ai-conv-list { flex: 1; overflow-y: auto; padding: 8px; }
.ai-conv-empty { text-align: center; color: #909399; font-size: 13px; margin-top: 48px; line-height: 1.8; }
.ai-conv { position: relative; padding: 10px 30px 10px 12px; border-radius: 6px; cursor: pointer; margin-bottom: 2px; }
.ai-conv:hover { background: #f5f7fa; }
.ai-conv.active { background: #ecf5ff; }
.ai-conv-title { font-size: 13px; color: #303133; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding-right: 8px; }
.ai-conv-meta { font-size: 12px; color: #909399; margin-top: 2px; }
.ai-conv-del { position: absolute; right: 6px; top: 10px; padding: 0; }

.ai-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.ai-head { display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-bottom: 1px solid #ebeef5; }
.title { font-size: 16px; font-weight: 600; }
.sub { font-size: 12px; color: #909399; }

.ai-list { flex: 1; overflow-y: auto; padding: 16px; }
.ai-empty { text-align: center; color: #909399; margin-top: 60px; }
.ai-empty .logo { font-size: 40px; }
.ai-empty ul { display: inline-block; text-align: left; margin-top: 8px; line-height: 1.9; }

.ai-turn { display: flex; gap: 10px; margin-bottom: 16px; }
.ai-avatar {
  width: 34px; height: 34px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: #fdf3e3; font-size: 15px;
}
.ai-turn.user .ai-avatar { background: #e8f0fe; color: #1e6fff; font-weight: 600; font-size: 13px; }
.ai-body { flex: 1; min-width: 0; }
.ai-meta { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.ai-name { font-size: 13px; font-weight: 600; color: #303133; }
.ai-bubble {
  display: inline-block; max-width: 100%; padding: 10px 14px; border-radius: 8px;
  background: #f6f8fa; font-size: 14px; color: #303133; line-height: 1.7;
}
.ai-turn.user .ai-bubble { background: #e8f0fe; }
.user-text { white-space: pre-wrap; word-break: break-word; }
.ai-ops { margin-top: 4px; display: flex; gap: 4px; }

.typing { display: flex; gap: 4px; align-items: center; }
.dot { width: 6px; height: 6px; border-radius: 50%; background: #c0c4cc; animation: blink 1.2s infinite; }
.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink { 0%, 80%, 100% { opacity: 0.3; } 40% { opacity: 1; } }

.ai-input { border-top: 1px solid #ebeef5; padding: 10px 16px; }
.ai-input-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 6px; }
.hint { font-size: 12px; color: #909399; }
</style>
