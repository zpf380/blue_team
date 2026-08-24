<template>
  <div class="page">
    <el-card>
      <div class="toolbar">
        <el-input v-model="keyword" placeholder="搜索聊天消息（支持中文）" clearable style="width: 240px" @keyup.enter="doSearch" />
        <el-button type="primary" @click="doSearch">搜索</el-button>
        <div style="flex: 1"></div>
        <el-badge v-if="chat.mentionCount" :value="chat.mentionCount" :max="99" class="mention-badge">
          <el-button type="warning" plain @click="chat.mentionCount = 0">@ 提及</el-button>
        </el-badge>
        <el-button type="warning" plain @click="openJoin">加入群组</el-button>
        <el-button v-permission="'chat:channel'" type="success" @click="openCreate">创建频道</el-button>
      </div>

      <div v-loading="loading">
        <el-empty v-if="channels.length === 0 && !loading" :description="emptyText">
          <el-button v-if="!isAdmin" type="primary" plain @click="openJoin">输入群组名称加入群聊</el-button>
        </el-empty>
        <div v-else class="ch-grid">
          <div v-for="ch in channels" :key="ch.id" class="ch-card" @click="open(ch)">
            <div class="ch-head">
              <el-tag :type="typeTag(ch.type)" size="small">{{ typeText(ch.type) }}</el-tag>
              <span class="ch-name">{{ ch.name }}</span>
              <el-badge v-if="ch.unread_count" :value="ch.unread_count" :max="99" class="unread" />
            </div>
            <div class="ch-desc">{{ ch.description || '暂无简介' }}</div>
            <div class="ch-foot">
              <span class="members">{{ ch.member_count }} 人</span>
              <span class="last">{{ ch.last_message || '暂无消息' }}</span>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 加入群组 -->
    <el-dialog v-model="joinVisible" title="加入群组" width="460px">
      <el-form label-width="90px" @submit.prevent>
        <el-form-item label="群组名称">
          <el-input v-model="joinName" maxlength="100" placeholder="输入群组名称（如：应急响应组）" @keyup.enter="join" />
        </el-form-item>
        <el-form-item>
          <el-alert type="info" :closable="false" title="输入名称加入后即可查看并参与该群组通信" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="joinVisible = false">取消</el-button>
        <el-button type="primary" :loading="joining" @click="join">加入</el-button>
      </template>
    </el-dialog>

    <!-- 创建频道 -->
    <el-dialog v-model="createVisible" title="创建频道" width="480px">
      <el-form ref="createFormRef" :rules="createRules" label-width="80px">
        <el-form-item label="频道名称" prop="name"><el-input v-model="form.name" maxlength="100" placeholder="如：应急响应演练" /></el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="form.type">
            <el-radio value="public">公开频道</el-radio>
            <el-radio value="private">私密频道</el-radio>
            <el-radio value="trainee">学员社区</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="简介"><el-input v-model="form.description" type="textarea" :rows="2" maxlength="200" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="create">创建</el-button>
      </template>
    </el-dialog>

    <!-- 搜索结果 -->
    <el-dialog v-model="searchVisible" title="搜索结果" width="640px">
      <el-empty v-if="results.length === 0" description="无匹配消息" />
      <div v-for="r in results" :key="r.id" class="sr-item" @click="jumpTo(r)">
        <div class="sr-meta">
          <b>{{ r.sender_name || 'AI' }}</b>
          <span>· #{{ channelName(r.channel_id) }}</span>
          <span class="sr-time">{{ formatTime(r.created_at) }}</span>
        </div>
        <div class="sr-content">{{ r.content }}</div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { chatApi } from '@/api/chat'
import { useChatStore } from '@/stores/chat'
import { formatDateTime } from '@/utils/format'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const chat = useChatStore()
const userStore = useUserStore()

const isAdmin = computed(() => userStore.role === 'admin')
const emptyText = computed(() => (isAdmin.value ? '暂无可用频道' : '尚未加入任何群组'))

const channels = ref([])
const loading = ref(false)
const keyword = ref('')

const createVisible = ref(false)
const saving = ref(false)
const createFormRef = ref()
const createRules = { name: [{ required: true, message: '请输入频道名称', trigger: 'blur' }] }
const form = reactive({ name: '', type: 'public', description: '' })

const joinVisible = ref(false)
const joining = ref(false)
const joinName = ref('')

const searchVisible = ref(false)
const results = ref([])

function typeText(t) {
  return { public: '公开', private: '私密', trainee: '学员社区' }[t] || t
}
function typeTag(t) {
  return { public: 'success', private: 'warning', trainee: 'info' }[t] || 'info'
}
function formatTime(s) {
  return formatDateTime(s)
}

async function load() {
  loading.value = true
  try {
    channels.value = await chat.loadChannels()
  } finally {
    loading.value = false
  }
}

function open(ch) {
  router.push(`/chat/channels/${ch.id}`)
}

function openCreate() {
  form.name = ''
  form.type = 'public'
  form.description = ''
  createVisible.value = true
}

async function create() {
  if (!createFormRef.value) return
  try {
    await createFormRef.value.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    await chatApi.createChannel({ name: form.name.trim(), type: form.type, description: form.description })
    ElMessage.success('频道创建成功')
    createVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

function openJoin() {
  joinName.value = ''
  joinVisible.value = true
}

async function join() {
  const name = joinName.value.trim()
  if (!name) {
    ElMessage.warning('请输入群组名称')
    return
  }
  joining.value = true
  try {
    await chatApi.joinChannel(name)
    ElMessage.success(`已加入群组「${name}」`)
    joinVisible.value = false
    load()
  } catch {
    /* 错误提示已由拦截器处理 */
  } finally {
    joining.value = false
  }
}

async function doSearch() {
  if (!keyword.value.trim()) return
  results.value = await chatApi.search({ q: keyword.value.trim() })
  searchVisible.value = true
}

function channelName(id) {
  const ch = channels.value.find((c) => c.id === id)
  return ch ? ch.name : id
}

function jumpTo(r) {
  searchVisible.value = false
  router.push(`/chat/channels/${r.channel_id}`)
}

onMounted(load)
</script>

<style scoped>
.toolbar { display: flex; gap: 8px; margin-bottom: 16px; }
.mention-badge { margin-right: 4px; }
.ch-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
.ch-card {
  border: 1px solid #ebeef5; border-radius: 8px; padding: 14px 16px; cursor: pointer;
  transition: box-shadow 0.2s, transform 0.1s; background: #fff;
}
.ch-card:hover { box-shadow: 0 4px 14px rgba(0, 0, 0, 0.08); transform: translateY(-1px); }
.ch-head { display: flex; align-items: center; gap: 8px; }
.ch-name { font-weight: 600; font-size: 15px; color: #303133; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.unread { flex-shrink: 0; }
.ch-desc { margin: 8px 0; color: #909399; font-size: 13px; height: 20px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ch-foot { display: flex; gap: 10px; font-size: 12px; color: #a8abb2; }
.ch-foot .last { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: right; }
.sr-item { padding: 8px 10px; border-radius: 6px; cursor: pointer; }
.sr-item:hover { background: #f5f7fa; }
.sr-meta { font-size: 13px; color: #606266; display: flex; gap: 6px; align-items: center; }
.sr-time { color: #a8abb2; font-size: 12px; }
.sr-content { font-size: 14px; color: #303133; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
