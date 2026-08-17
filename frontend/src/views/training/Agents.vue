<template>
  <div class="page">
    <el-card v-loading="loading">
      <div class="intro">
        <h3>🛡️ 智能体实训</h3>
        <p>按课程智能体逐级闯关：完成场景任务赢取积分与徽章。沙箱为模拟环境，可放心敲命令练习。</p>
      </div>

      <el-empty v-if="agents.length === 0 && !loading" description="暂无训练课程" />
      <div v-else class="ag-grid">
        <div
          v-for="a in agents"
          :key="a.id"
          class="ag-card"
          :class="{ active: current?.id === a.id }"
          @click="select(a)"
        >
          <div class="ag-head">
            <span class="ag-emoji">{{ emoji(a.code) }}</span>
            <span class="ag-name">{{ a.name }}</span>
            <el-tag v-if="isNew(a)" size="small" type="danger" effect="dark">NEW</el-tag>
            <el-tag size="small" :type="diffTag(a.difficulty)">{{ diffText(a.difficulty) }}</el-tag>
          </div>
          <div class="ag-desc">{{ a.description }}</div>
          <div class="ag-foot">
            <span>课程 {{ a.completed_count }}/{{ a.scenario_count }}</span>
            <el-progress
              :percentage="progressPct(a)"
              :stroke-width="6"
              :show-text="false"
              style="width: 90px"
            />
          </div>
        </div>
      </div>
    </el-card>

    <el-card v-if="current" class="scenario-card" v-loading="detailLoading">
      <div class="sc-head">
        <h3>{{ current.name }} · 场景列表</h3>
        <span v-if="current.prerequisites?.length" class="pre">前置：{{ current.prerequisites.join('、') }}</span>
      </div>
      <el-empty v-if="scenarios.length === 0 && !detailLoading" description="暂无场景" />
      <div v-for="s in scenarios" :key="s.id" class="sc-row">
        <div class="sc-info">
          <div class="sc-title">{{ s.title }}</div>
          <div class="sc-desc">{{ s.description }}</div>
          <div class="sc-meta">
            <el-tag size="small">+{{ s.points }} 分</el-tag>
            <el-tag v-if="s.time_limit" size="small" type="info">限时 {{ s.time_limit }} 分钟</el-tag>
            <el-tag size="small" type="info">{{ s.task_count }} 个任务</el-tag>
            <el-tag v-if="s.my_progress" size="small" :type="statusTag(s.my_progress.status)">{{ statusText(s.my_progress.status) }}</el-tag>
            <span v-if="s.my_progress?.score != null" class="score">得分 {{ s.my_progress.score }}</span>
          </div>
        </div>
        <div class="sc-action">
          <el-button type="primary" plain @click.stop="start(s)">
            {{ s.my_progress?.status === 'in_progress' ? '继续实训' : '开始实训' }}
          </el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import { ElMessage } from 'element-plus'
import { trainingApi } from '@/api/training'
import { useNotificationsStore } from '@/stores/notifications'

const router = useRouter()
const notifyStore = useNotificationsStore()
const agents = ref([])
const current = ref(null)
const scenarios = ref([])
const loading = ref(false)
const detailLoading = ref(false)

// 新课程推送（发布 7 天内标记 NEW）
function isNew(a) {
  if (!a.published_at) return false
  return dayjs().diff(dayjs(a.published_at), 'day') <= 7
}

function emoji(code) {
  return { foundation: '📘', incident: '🚨', hardening: '🔧' }[code] || '🎯'
}
function diffText(d) {
  return { 1: '入门', 2: '进阶', 3: '挑战' }[d] || '入门'
}
function diffTag(d) {
  return { 1: 'success', 2: 'warning', 3: 'danger' }[d] || 'info'
}
function progressPct(a) {
  if (!a.scenario_count) return 0
  return Math.round((a.completed_count / a.scenario_count) * 100)
}
function statusText(s) {
  return { not_started: '未开始', in_progress: '进行中', completed: '已完成', failed: '未达标' }[s] || s
}
function statusTag(s) {
  return { not_started: 'info', in_progress: 'warning', completed: 'success', failed: 'danger' }[s] || 'info'
}

async function load() {
  loading.value = true
  try {
    agents.value = await trainingApi.agents()
    if (agents.value.length) select(agents.value[0])
  } finally {
    loading.value = false
  }
}

async function select(a) {
  current.value = a
  detailLoading.value = true
  try {
    const data = await trainingApi.agentDetail(a.id)
    scenarios.value = data.scenarios
  } finally {
    detailLoading.value = false
  }
}

async function start(s) {
  try {
    const data = await trainingApi.startScenario(s.id)
    ElMessage.success('已进入沙箱实训')
    router.push(`/training/sandbox/${data.session_id}`)
  } catch { /* 错误提示已由拦截器处理 */ }
}

onMounted(load)

// 主管/管理员发布新课程 → WebSocket 推送 → 刷新课程列表
watch(() => notifyStore.refreshVersion, () => {
  load()
})
</script>

<style scoped>
.intro h3 { margin: 0 0 6px; }
.intro p { margin: 0 0 14px; color: #909399; font-size: 13px; }
.ag-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
.ag-card {
  border: 1px solid #ebeef5; border-radius: 8px; padding: 14px 16px; cursor: pointer;
  transition: box-shadow 0.2s, transform 0.1s; background: #fff;
}
.ag-card:hover { box-shadow: 0 4px 14px rgba(0, 0, 0, 0.08); transform: translateY(-1px); }
.ag-card.active { border-color: var(--el-color-primary); box-shadow: 0 0 0 1px var(--el-color-primary) inset; }
.ag-head { display: flex; align-items: center; gap: 8px; }
.ag-emoji { font-size: 22px; }
.ag-name { font-weight: 600; font-size: 15px; flex: 1; }
.ag-desc { margin: 8px 0; color: #909399; font-size: 13px; min-height: 38px; }
.ag-foot { display: flex; align-items: center; justify-content: space-between; font-size: 12px; color: #a8abb2; }

.scenario-card { margin-top: 14px; }
.sc-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 6px; }
.sc-head h3 { margin: 0; }
.pre { font-size: 12px; color: #909399; }
.sc-row {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 12px; border: 1px solid #f0f2f5; border-radius: 8px; margin-top: 10px;
}
.sc-info { flex: 1; min-width: 0; }
.sc-title { font-weight: 600; font-size: 14px; }
.sc-desc { color: #909399; font-size: 13px; margin: 4px 0; }
.sc-meta { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.score { color: var(--el-color-success); font-weight: 600; }
.sc-action { flex-shrink: 0; }
</style>
