<template>
  <div class="dm-page">
    <div class="dm-side">
      <!-- 收到的添加请求 -->
      <template v-if="requests.length">
        <div class="sec-title">收到的请求</div>
        <div v-for="r in requests" :key="r.id" class="req-item">
          <div class="req-info">
            <span class="dm-name">{{ r.requester_real_name || r.requester_username }}</span>
            <el-tag size="small" type="info">{{ r.requester_role_name || '—' }}</el-tag>
          </div>
          <div class="req-actions">
            <el-button size="small" type="primary" :loading="processingReq === r.id" @click="acceptReq(r)">同意</el-button>
            <el-button size="small" @click="rejectReq(r)">拒绝</el-button>
          </div>
        </div>
      </template>

      <!-- 联系人列表 -->
      <div class="sec-row">
        <div class="sec-title" style="margin: 0">联系人</div>
        <el-button link type="primary" size="small" @click="addVisible = true">+ 添加</el-button>
      </div>
      <div v-if="contacts.length === 0" class="sec-empty">暂无联系人，添加后经对方同意即可私聊</div>
      <div
        v-for="c in contacts"
        :key="c.id"
        class="dm-item"
        :class="{ active: activeContactId === c.id }"
        @click="openDm(c)"
      >
        <span class="dm-name">{{ c.real_name || c.username }}</span>
        <el-tag size="small" type="info">{{ c.role_name || '—' }}</el-tag>
        <el-popconfirm
          title="删除该联系人？"
          confirm-button-text="删除"
          cancel-button-text="取消"
          width="200"
          @confirm="removeContact(c)"
        >
          <template #reference>
            <el-button link type="danger" size="small" class="del-btn" @click.stop>删除</el-button>
          </template>
        </el-popconfirm>
      </div>
    </div>

    <div class="dm-main">
      <ChannelRoom v-if="activeChannel" :channel="activeChannel" />
      <el-empty v-else description="选择左侧联系人开始私聊" />
    </div>

    <!-- 添加联系人 -->
    <el-dialog v-model="addVisible" title="添加联系人" width="520px">
      <el-input v-model="kw" placeholder="搜索用户（学员仅可添加学员）" clearable size="small" @input="loadCandidates" />
      <div class="cand-list" v-loading="candLoading">
        <el-empty v-if="!candidates.length && !candLoading" description="没有可添加的用户" />
        <div v-for="u in candidates" :key="u.id" class="cand-item">
          <span class="dm-name">{{ u.real_name || u.username }}</span>
          <el-tag size="small" type="info">{{ u.role || '—' }}</el-tag>
          <el-button size="small" type="primary" @click="sendReq(u)">添加</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { chatApi } from '@/api/chat'
import { useChatStore } from '@/stores/chat'
import ChannelRoom from './ChannelRoom.vue'

const chat = useChatStore()

const activeChannel = ref(null)
const activeContactId = ref(null)
const contacts = ref([])
const requests = ref([])
const processingReq = ref(null)

const addVisible = ref(false)
const kw = ref('')
const candidates = ref([])
const candLoading = ref(false)

async function loadContacts() {
  contacts.value = await chatApi.contacts()
  requests.value = await chatApi.contactRequests()
}

async function loadCandidates() {
  candLoading.value = true
  try {
    const list = await chatApi.candidates({ keyword: kw.value || undefined })
    const reqIds = new Set(requests.value.map((r) => r.requester_id))
    candidates.value = list.filter((u) => !contacts.value.some((c) => c.id === u.id) && !reqIds.has(u.id))
  } finally {
    candLoading.value = false
  }
}

// 点击联系人：调出与该用户的所有记录（私聊频道，不可重复）
async function openDm(c) {
  try {
    const ch = await chatApi.dm(c.id)
    activeContactId.value = c.id
    activeChannel.value = { ...ch, unread_count: 0, member_count: ch.member_count || 2 }
    await chat.loadChannels()
  } catch {
    activeContactId.value = null
  }
}

async function sendReq(u) {
  try {
    await chatApi.sendContactRequest(u.id)
    ElMessage.success(`已向 ${u.real_name || u.username} 发送添加请求，等待对方同意`)
    loadCandidates()
  } catch {
    /* 错误提示已由拦截器处理 */
  }
}

async function acceptReq(r) {
  processingReq.value = r.id
  try {
    await chatApi.acceptContactRequest(r.id)
    ElMessage.success('已同意，成为联系人')
    await loadContacts()
  } finally {
    processingReq.value = null
  }
}

async function rejectReq(r) {
  processingReq.value = r.id
  try {
    await chatApi.rejectContactRequest(r.id)
    ElMessage.info('已拒绝该请求')
    await loadContacts()
  } finally {
    processingReq.value = null
  }
}

async function removeContact(c) {
  try {
    await chatApi.removeContact(c.id)
    ElMessage.success('已删除联系人')
    if (activeContactId.value === c.id) {
      activeContactId.value = null
      activeChannel.value = null
    }
    await loadContacts()
  } catch {
    /* 错误提示已由拦截器处理 */
  }
}

onMounted(async () => {
  await chat.loadChannels()
  await loadContacts()
})
</script>

<style scoped>
.dm-page { display: flex; gap: 12px; height: calc(100vh - 110px); }
.dm-side { width: 300px; flex-shrink: 0; background: #fff; border-radius: 8px; padding: 10px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
.sec-title { font-size: 12px; color: #909399; margin-top: 8px; }
.sec-row { display: flex; align-items: center; justify-content: space-between; margin-top: 8px; }
.sec-empty { font-size: 12px; color: #c0c4cc; padding: 6px 0; }
.dm-item {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 8px 10px; border-radius: 6px; cursor: pointer;
}
.dm-item:hover { background: #f5f7fa; }
.dm-item.active { background: #ecf5ff; }
.del-btn { opacity: 0; transition: opacity 0.2s; }
.dm-item:hover .del-btn { opacity: 1; }
.dm-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.req-item {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 8px 10px; border-radius: 6px; background: #fdf6ec; margin-bottom: 4px;
}
.req-info { display: flex; align-items: center; gap: 6px; min-width: 0; }
.req-info .dm-name { font-size: 13px; }
.req-actions { display: flex; gap: 4px; flex-shrink: 0; }
.cand-list { margin-top: 10px; max-height: 360px; overflow-y: auto; }
.cand-item { display: flex; align-items: center; gap: 8px; padding: 8px 6px; border-radius: 6px; }
.cand-item:hover { background: #f5f7fa; }
.dm-main { flex: 1; min-width: 0; background: #fff; border-radius: 8px; padding: 8px; }
</style>
