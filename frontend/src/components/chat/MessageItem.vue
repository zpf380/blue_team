<template>
  <div class="msg-row" :class="[msg.sender_type, mine ? 'mine' : 'other']">
    <div class="avatar">
      <span v-if="msg.sender_type === 'ai_agent'">🤖</span>
      <span v-else-if="msg.sender_type === 'system'">🛡️</span>
      <span v-else>{{ avatarChar }}</span>
    </div>
    <div class="bubble">
      <div class="meta">
        <span class="name">{{ displayName }}</span>
        <el-tag v-if="msg.ai_agent_name" size="small" :type="providerTag" class="provider">{{ providerLabel }}</el-tag>
        <span class="time">{{ timeText }}</span>
      </div>

      <div class="body" :class="{ 'recalled-body': msg.is_deleted }">
        <div v-if="msg.is_deleted" class="recalled">该消息已撤回</div>
        <template v-else>
          <div v-if="msg.message_type === 'file'" class="file-msg">
            <a :href="msg.file_url" target="_blank" rel="noopener">📎 {{ msg.file_name || '附件' }}</a>
          </div>
          <div v-else-if="msg.message_type === 'image'" class="img-msg">
            <el-image :src="msg.file_url" :preview-src-list="[msg.file_url]" preview-teleported fit="cover" class="chat-img" />
          </div>
          <div v-else-if="msg.message_type === 'alert'" class="alert-msg">
            <el-alert :title="msg.content" type="warning" :closable="false" show-icon />
          </div>
          <div v-else-if="msg.content" class="content">
            <MarkdownText :text="msg.content" />
          </div>
        </template>
      </div>

      <div v-if="opsVisible" class="ops">
        <el-button v-if="mine && canRecall" link type="danger" size="small" @click="$emit('recall', msg)">撤回</el-button>
        <el-button v-if="msg.sender_type === 'ai_agent'" link size="small" @click="$emit('regenerate', msg)">重新生成</el-button>
        <el-button v-if="msg.content" link size="small" @click="copyContent">复制</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import MarkdownText from './MarkdownText.vue'

const props = defineProps({
  msg: { type: Object, required: true },
  mine: { type: Boolean, default: false },
  canRecall: { type: Boolean, default: false }
})
defineEmits(['recall', 'regenerate'])

const displayName = computed(() => {
  if (props.msg.sender_type === 'ai_agent') return props.msg.sender_name || `AI·${props.msg.ai_agent_name}`
  if (props.msg.sender_type === 'system') return '系统'
  return props.msg.sender_name || '用户'
})

const avatarChar = computed(() => (displayName.value || '?').slice(0, 1).toUpperCase())

const providerLabel = computed(() => {
  const map = { deepseek: 'DeepSeek', ollama: 'Ollama', fallback: '本地兜底' }
  return map[props.msg.ai_agent_name] || props.msg.ai_agent_name || 'AI'
})
const providerTag = computed(() => {
  const map = { deepseek: 'warning', ollama: 'success', fallback: 'info' }
  return map[props.msg.ai_agent_name] || 'info'
})

const timeText = computed(() =>
  props.msg.created_at ? new Date(props.msg.created_at).toLocaleString('zh-CN', { hour12: false }) : ''
)

const opsVisible = computed(() => props.msg.sender_type !== 'system' && !props.msg.is_deleted)

async function copyContent() {
  try {
    await navigator.clipboard.writeText(props.msg.content || '')
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败')
  }
}
</script>

<style scoped>
.msg-row { display: flex; gap: 10px; padding: 8px 12px; align-items: flex-start; }
.msg-row:hover { background: #fafafa; }
/* 自己发的消息：头像在右、内容靠右（经典聊天左右布局） */
.msg-row.mine { flex-direction: row-reverse; }
/* 系统消息居中 */
.msg-row.system { justify-content: center; }
.msg-row.system .avatar { display: none; }

.avatar {
  width: 36px; height: 36px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  background: #e8f0fe; color: #1e6fff; font-weight: 600; font-size: 15px;
}
.msg-row.ai_agent .avatar { background: #fdf3e3; color: #b45309; }
.msg-row.system .avatar { background: #eef2f5; color: #687384; }
.msg-row.mine .avatar { background: #d9f0e2; color: #17734c; }

.bubble { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: flex-start; }
.msg-row.mine .bubble { align-items: flex-end; }
.msg-row.system .bubble { flex: none; align-items: center; }

.meta { display: flex; align-items: center; gap: 6px; margin-bottom: 2px; }
.msg-row.mine .meta { flex-direction: row-reverse; }
.msg-row.mine .name { display: none; }
.name { font-weight: 600; font-size: 13px; color: #303133; }
.time { font-size: 12px; color: #a8abb2; }
.provider { margin-left: 2px; }

/* 消息气泡：自己的浅蓝靠右、别人的白底靠左 */
.body {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 8px 12px;
  max-width: 560px;
  line-height: 1.6;
  word-break: break-word;
}
.msg-row.mine .body {
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-6);
}
.msg-row.system .body {
  background: #f0f2f5; border-color: transparent; border-radius: 14px; padding: 3px 12px;
}
.msg-row .body.recalled-body { background: transparent; border: none; padding: 2px 0; }

.content { font-size: 14px; color: #303133; }
.recalled { color: #a8abb2; font-size: 13px; font-style: italic; }
.file-msg a { color: var(--el-color-primary); font-size: 14px; }
.img-msg { margin-top: 2px; }
.chat-img { max-width: 260px; max-height: 260px; border-radius: 6px; }

.ops { display: flex; gap: 4px; opacity: 0; transition: opacity 0.2s; margin-top: 2px; }
.msg-row:hover .ops { opacity: 1; }
</style>
