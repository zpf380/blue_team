<template>
  <div class="sb-page">
    <div class="sb-side">
      <el-button link type="primary" @click="$router.push('/training/agents')">← 返回课程</el-button>
      <div class="sec-title">我的沙箱会话</div>
      <div v-if="sessions.length === 0" class="sec-empty">暂无会话，请先进入课程开始实训</div>
      <div
        v-for="s in sessions"
        :key="s.session_id"
        class="sb-item"
        :class="{ active: s.session_id === currentId }"
        @click="openSession(s)"
      >
        <div class="sb-item-title">{{ s.scenario_title || s.session_id }}</div>
        <div class="sb-item-meta">
          {{ s.completed_tasks }}/{{ s.task_count }} 任务 · {{ s.points }} 分
          <el-tag size="small" :type="s.is_active ? 'success' : 'info'" style="margin-left: 4px">{{ s.is_active ? '进行中' : '已结束' }}</el-tag>
        </div>
      </div>
    </div>

    <div class="sb-main" v-loading="loading">
      <el-empty v-if="!current" description="选择一个会话或从课程开始实训" />

      <template v-else>
        <div class="sb-head">
          <div>
            <div class="sb-title">{{ current.scenario_title }}</div>
            <div class="sb-score">得分 {{ current.points }}<span v-if="current.penalty" class="penalty">（扣 {{ current.penalty }}）</span> · 任务 {{ current.completed_tasks.length }}/{{ current.tasks.length }}</div>
          </div>
          <div>
            <el-button type="primary" :loading="submitting" @click="submit">提交结算</el-button>
          </div>
        </div>

        <div class="sb-body">
          <div class="terminal">
            <div ref="termEl" class="term-out">
              <div class="term-line intro">{{ current.intro || current.scenario_title }}</div>
              <div v-for="(line, i) in lines" :key="i" class="term-line" :class="line.cls">
                <template v-if="line.prompt"><span class="prompt">trainee@blueteam:~$ </span>{{ line.text }}</template>
                <template v-else>{{ line.text }}</template>
              </div>
              <div class="term-line input-line">
                <span class="prompt">trainee@blueteam:~$ </span>
                <input
                  ref="cmdEl"
                  v-model="cmd"
                  class="term-input"
                  autocomplete="off"
                  spellcheck="false"
                  :disabled="submitting || !current.is_active"
                  @keydown.enter.prevent="run"
                />
              </div>
            </div>
          </div>

          <div class="tasks">
            <div class="task-title">📋 任务清单</div>
            <div
              v-for="t in current.tasks"
              :key="t.id"
              class="task"
              :class="{ done: current.completed_tasks.includes(t.id) }"
            >
              <span class="task-icon">{{ current.completed_tasks.includes(t.id) ? '✅' : '⬜' }}</span>
              <span class="task-name">{{ t.title }}</span>
              <span class="task-pts">+{{ t.points }}</span>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { trainingApi } from '@/api/training'

const route = useRoute()
const router = useRouter()

const sessions = ref([])
const current = ref(null)
const currentId = ref('')
const lines = ref([])
const cmd = ref('')
const loading = ref(false)
const submitting = ref(false)
const termEl = ref(null)
const cmdEl = ref(null)

function pushLine(text, cls = '') {
  lines.value.push({ text, cls })
}

function scrollTerm() {
  nextTick(() => {
    if (termEl.value) termEl.value.scrollTop = termEl.value.scrollHeight
  })
}

async function loadSessions() {
  sessions.value = await trainingApi.sessions()
  // 若路由带 sessionId，优先打开
  const sid = route.params.sessionId
  const target = sid ? sessions.value.find((s) => s.session_id === sid) : null
  if (target) openSession(target)
}

function openSession(s) {
  currentId.value = s.session_id
  current.value = s
  lines.value = []
  cmd.value = ''
  if (s.intro) pushLine(s.intro)
  // 历史命令不持久化；提示可用命令
  pushLine('（沙箱已就绪，输入 help 查看可用命令）', 'hint')
  scrollTerm()
}

async function run() {
  const command = cmd.value.trim()
  if (!command) return
  pushLine(command, 'input')
  cmd.value = ''
  try {
    const res = await trainingApi.command(currentId.value, command)
    const data = res
    if (data.output) pushLine(data.output)
    for (const t of data.newly_completed || []) {
      pushLine(`🎉 任务完成：${t.title}（+${t.points} 分）`, 'success')
    }
    if (data.all_completed) {
      pushLine('✅ 全部任务已完成！点击右上角「提交结算」获得积分。', 'success')
    }
    // 刷新当前会话得分与任务
    current.value.points = data.points
    current.value.penalty = data.penalty
    current.value.completed_tasks = data.completed_tasks
    const s = sessions.value.find((x) => x.session_id === currentId.value)
    if (s) {
      s.points = data.points
      s.penalty = data.penalty
      s.completed_tasks = data.completed_tasks
    }
    scrollTerm()
  } catch { /* 错误提示已由拦截器处理 */ }
}

async function submit() {
  const done = current.value.completed_tasks.length
  const total = current.value.tasks.length
  if (done < total) {
    try {
      await ElMessageBox.confirm(`当前完成 ${done}/${total} 个任务，未完成将记为未达标，确定提交？`, '提交结算', { type: 'warning' })
    } catch {
      return // 用户取消
    }
  }
  await doSubmit()
}

async function doSubmit() {
  submitting.value = true
  try {
    const data = await trainingApi.submit(current.value.scenario_id)
    const badgeText = data.earned_badges?.length ? `，获得徽章：${data.earned_badges.map((b) => `「${b.name}」`).join('')}` : ''
    if (data.status === 'completed') {
      ElMessage.success(`提交成功，得分 ${data.score}${badgeText}`)
    } else {
      ElMessage.warning(`本场景未达标，得分 ${data.score}${badgeText}`)
    }
    await loadSessions()
    const updated = sessions.value.find((s) => s.session_id === currentId.value)
    if (updated) openSession(updated)
  } finally {
    submitting.value = false
  }
}

onMounted(loadSessions)
</script>

<style scoped>
.sb-page { display: flex; gap: 12px; height: calc(100vh - 110px); }
.sb-side { width: 260px; flex-shrink: 0; background: #fff; border-radius: 8px; padding: 10px; overflow-y: auto; }
.sec-title { font-size: 12px; color: #909399; margin: 10px 0 6px; }
.sec-empty { font-size: 12px; color: #c0c4cc; padding: 8px 0; }
.sb-item { padding: 8px 10px; border-radius: 6px; cursor: pointer; }
.sb-item:hover { background: #f5f7fa; }
.sb-item.active { background: #ecf5ff; }
.sb-item-title { font-size: 13px; font-weight: 600; }
.sb-item-meta { font-size: 12px; color: #909399; margin-top: 2px; display: flex; align-items: center; }

.sb-main { flex: 1; min-width: 0; background: #fff; border-radius: 8px; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
.sb-head { display: flex; align-items: center; justify-content: space-between; }
.sb-title { font-size: 16px; font-weight: 600; }
.sb-score { font-size: 13px; color: #909399; margin-top: 2px; }
.penalty { color: #f56c6c; }

.sb-body { flex: 1; display: flex; gap: 12px; min-height: 0; }
.terminal { flex: 1; display: flex; flex-direction: column; background: #0f172a; border-radius: 8px; overflow: hidden; min-width: 0; }
.term-out { flex: 1; overflow-y: auto; padding: 12px 14px; font-family: Consolas, Menlo, monospace; font-size: 13px; line-height: 1.7; color: #e2e8f0; }
.term-line { white-space: pre-wrap; word-break: break-word; }
.term-line.intro { color: #93c5fd; margin-bottom: 6px; }
.term-line.hint { color: #64748b; }
.term-line.input { color: #cbd5e1; }
.term-line.success { color: #4ade80; font-weight: 600; }
.prompt { color: #4ade80; }
.input-line { display: flex; align-items: center; }
.term-input {
  flex: 1; background: transparent; border: none; outline: none; color: #e2e8f0;
  font-family: inherit; font-size: 13px; caret-color: #4ade80;
}

.tasks { width: 240px; flex-shrink: 0; background: #f8fafc; border-radius: 8px; padding: 12px; overflow-y: auto; }
.task-title { font-weight: 600; font-size: 14px; margin-bottom: 8px; }
.task { display: flex; align-items: center; gap: 8px; padding: 6px 4px; font-size: 13px; color: #475569; }
.task.done { color: #10b981; }
.task-icon { width: 18px; text-align: center; }
.task-name { flex: 1; }
.task-pts { font-size: 12px; color: #94a3b8; }
.task.done .task-pts { color: #10b981; }
</style>
