<template>
  <div class="page">
    <!-- AI 生成区 -->
    <el-card class="gen-card">
      <div class="gen-row">
        <span class="gen-label">📚 按主题生成课程</span>
        <el-input
          v-model="topic"
          placeholder="输入课程主题，例如：Web 渗透应急、弱口令排查"
          maxlength="100"
          show-word-limit
          style="max-width: 420px"
          @keyup.enter="generate"
        />
        <el-button type="primary" :loading="generating" @click="generate">
          {{ generating ? 'AI 生成中…' : '生成课程' }}
        </el-button>
        <span class="gen-tip">AI 将生成课程卡片 + 场景任务（草稿），可审改后发布，发布后实时推送学员端。</span>
      </div>
    </el-card>

    <!-- 课程列表 -->
    <el-card v-loading="loading">
      <div class="list-head">
        <h3>课程管理</h3>
        <el-button type="primary" plain @click="createEmpty">新建课程</el-button>
      </div>
      <el-empty v-if="!courses.length && !loading" description="暂无课程，可点击「新建课程」或输入主题用 AI 生成" />
      <el-table v-else :data="courses" stripe>
        <el-table-column prop="name" label="课程名称" min-width="200" />
        <el-table-column label="难度" width="80">
          <template #default="{ row }">{{ diffText(row.difficulty) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'published' ? 'success' : 'info'">
              {{ row.status === 'published' ? '已发布' : '草稿' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="scenario_count" label="场景数" width="80" />
        <el-table-column label="发布时间" width="180">
          <template #default="{ row }">{{ row.published_at ? fmt(row.published_at) : '—' }}</template>
        </el-table-column>
        <el-table-column prop="creator_name" label="创建人" width="120" />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openCourse(row)">编辑</el-button>
            <el-button
              v-if="row.status !== 'published'"
              size="small" type="success"
              @click="publish(row)"
            >发布</el-button>
            <el-button v-else size="small" type="warning" @click="unpublish(row)">下线</el-button>
            <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 课程编辑器 -->
    <el-dialog v-model="dialogVisible" title="课程编辑器" width="960px" class="course-dialog" top="5vh" destroy-on-close :before-close="beforeCloseEditor">
      <div v-loading="detailLoading">
        <el-form label-width="80px" class="course-form">
          <el-form-item label="课程名称" required>
            <el-input v-model="form.name" maxlength="100" />
          </el-form-item>
          <el-form-item label="课程简介">
            <el-input v-model="form.description" type="textarea" :rows="2" maxlength="500" />
          </el-form-item>
          <el-form-item label="难度">
            <el-radio-group v-model="form.difficulty">
              <el-radio :label="1">入门</el-radio>
              <el-radio :label="2">进阶</el-radio>
              <el-radio :label="3">挑战</el-radio>
            </el-radio-group>
          </el-form-item>
        </el-form>

        <div class="sc-head">
          <h4>场景与任务（{{ form.scenarios.length }}）</h4>
          <el-button size="small" type="primary" plain @click="addScenario">新增场景</el-button>
        </div>

        <el-collapse v-model="activeScenario">
          <el-collapse-item
            v-for="(sc, si) in form.scenarios"
            :key="sc._key"
            :name="sc._key"
          >
            <template #title>
              <span class="sc-title">{{ sc.id ? sc.title || '（未命名场景）' : '＋ 新场景（未保存）' }}</span>
              <el-tag v-if="sc._dirty" size="small" type="warning" class="dirty-tag">未保存</el-tag>
            </template>

            <el-form label-width="90px" size="small">
              <el-form-item label="场景标题" required>
                <el-input v-model="sc.title" maxlength="200" />
              </el-form-item>
              <el-form-item label="场景描述">
                <el-input v-model="sc.description" maxlength="300" />
              </el-form-item>
              <el-form-item label="分值/罚分/时限">
                <el-input-number v-model="sc.points" :min="0" style="width: 110px" />
                <span class="sep">/</span>
                <el-input-number v-model="sc.penalty_points" :min="0" style="width: 110px" />
                <span class="sep">/</span>
                <el-input-number v-model="sc.time_limit" :min="0" :controls="false" placeholder="分钟" style="width: 110px" />
              </el-form-item>
              <el-form-item label="场景引言">
                <el-input v-model="sc.content.intro" type="textarea" :rows="3" placeholder="给学员的任务说明与操作提示" />
              </el-form-item>

              <el-form-item label="虚拟文件">
                <div class="files-wrap">
                  <div v-for="(f, fi) in sc.content.files" :key="fi" class="file-row">
                    <el-input v-model="f.path" placeholder="/路径/文件" class="file-path" />
                    <el-input v-model="f.content" type="textarea" :rows="1" placeholder="文件内容" class="file-body" />
                    <el-button type="danger" text @click="removeFile(sc, fi)">删</el-button>
                  </div>
                  <el-button size="small" @click="addFile(sc)">+ 添加文件</el-button>
                </div>
              </el-form-item>

              <el-form-item label="任务列表">
                <div class="tasks-wrap">
                  <div v-for="(t, ti) in sc.content.tasks" :key="ti" class="task-card">
                    <div class="task-head">
                      <span>任务 {{ ti + 1 }}</span>
                      <el-button type="danger" text @click="removeTask(sc, ti)">删除任务</el-button>
                    </div>
                    <div class="task-grid">
                      <el-input v-model="t.id" placeholder="id (t1)" style="width: 90px" />
                      <el-input v-model="t.title" placeholder="任务标题" style="flex: 1" />
                      <el-input-number v-model="t.points" :min="0" style="width: 100px" />
                    </div>
                    <div class="task-grid">
                      <el-input v-model="t.hint" placeholder="提示（如 cat /var/log/auth.log）" />
                    </div>
                    <div class="task-grid">
                      <span class="chk-label">判定命令</span>
                      <el-select v-model="t.check.cmd" style="width: 140px">
                        <el-option v-for="c in COMMANDS" :key="c" :label="c" :value="c" />
                      </el-select>
                      <el-input v-model="t.check.pattern" placeholder="pattern：命令参数含此子串" style="flex: 1" />
                      <el-input v-model="t.check.args" placeholder="args：命令参数含此子串（与 pattern 二选一）" style="flex: 1" />
                    </div>
                    <div class="task-grid">
                      <el-input v-model="t.check.output_contains" placeholder="output_contains：命令输出含此文本（可选）" />
                    </div>
                  </div>
                  <el-button size="small" @click="addTask(sc)">+ 添加任务</el-button>
                </div>
              </el-form-item>
            </el-form>

            <div class="sc-actions">
              <el-button type="primary" size="small" :loading="saving" @click="saveScenario(sc)">
                {{ sc.id ? '保存场景' : '保存并创建' }}
              </el-button>
              <el-button v-if="sc.id" type="danger" size="small" plain @click="removeScenario(sc)">删除场景</el-button>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>

      <template #footer>
        <el-button @click="cancelEditor">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveCourse">保存课程</el-button>
        <el-button type="success" :loading="saving" @click="publishFromEditor">发布课程</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'
import { trainingApi } from '@/api/training'

const COMMANDS = ['help', 'ls', 'cat', 'grep', 'head', 'tail', 'find', 'who', 'last', 'ps', 'ss', 'netstat', 'ip', 'iptables', 'echo']

const courses = ref([])
const loading = ref(false)
const generating = ref(false)
const topic = ref('')

const dialogVisible = ref(false)
const detailLoading = ref(false)
const saving = ref(false)
const activeScenario = ref([])
const form = reactive({ id: null, name: '', description: '', difficulty: 1, scenarios: [] })

let keySeq = 0
function nextKey() {
  keySeq += 1
  return `sc_${keySeq}`
}

import { formatDateTime as fmt } from '@/utils/format'
function diffText(d) {
  return { 1: '入门', 2: '进阶', 3: '挑战' }[d] || '入门'
}

// 关闭编辑器前若有未保存场景修改，先确认（覆盖取消按钮 / X / 遮罩 / ESC）
async function beforeCloseEditor(done) {
  const dirty = form.scenarios.some((sc) => sc._dirty)
  if (!dirty) return done()
  try {
    await ElMessageBox.confirm('有场景修改未保存，确定放弃并关闭？', '关闭编辑器', { type: 'warning' })
    done()
  } catch { /* 用户取消关闭 */ }
}

async function cancelEditor() {
  await beforeCloseEditor(() => { dialogVisible.value = false })
}

async function load() {
  loading.value = true
  try {
    courses.value = await trainingApi.manageCourses()
  } finally {
    loading.value = false
  }
}

function blankScenario() {
  return {
    _key: nextKey(), _dirty: true, id: null,
    title: '', description: '', points: 50, penalty_points: 5, time_limit: null, order_index: 0,
    content: { intro: '', files: [{ path: '/var/log/auth.log', content: '' }], tasks: [blankTask()] }
  }
}
function blankTask() {
  return { id: 't1', title: '', points: 10, hint: '', check: { cmd: 'cat', pattern: '', args: '', output_contains: '' } }
}

function toServerContent(sc) {
  const files = {}
  for (const f of sc.content.files) {
    if (f.path && f.path.startsWith('/')) files[f.path] = f.content
  }
  const tasks = sc.content.tasks
    .filter((t) => t.title)
    .map((t) => {
      const check = { cmd: t.check.cmd || 'cat' }
      if (t.check.pattern) check.pattern = t.check.pattern
      if (t.check.args) check.args = t.check.args
      if (t.check.output_contains) check.output_contains = t.check.output_contains
      return {
        id: t.id || `t${Math.random().toString(36).slice(2, 6)}`,
        title: t.title,
        points: t.points || 0,
        hint: t.hint || '',
        check
      }
    })
  return { intro: sc.content.intro || '', files, tasks }
}

function fromServerContent(content) {
  const c = content || {}
  const files = Object.entries(c.files || {}).map(([path, body]) => ({ path, content: body }))
  const tasks = (c.tasks || []).map((t) => ({
    id: t.id || '',
    title: t.title || '',
    points: t.points || 0,
    hint: t.hint || '',
    check: { cmd: t.check?.cmd || 'cat', pattern: t.check?.pattern || '', args: t.check?.args || '', output_contains: t.check?.output_contains || '' }
  }))
  return {
    _key: nextKey(), _dirty: false, id: null,
    title: '', description: '', points: 50, penalty_points: 5, time_limit: null, order_index: 0,
    content: { intro: c.intro || '', files, tasks }
  }
}

async function generate() {
  if (!topic.value || topic.value.trim().length < 2) {
    ElMessage.warning('请输入课程主题')
    return
  }
  generating.value = true
  try {
    const data = await trainingApi.generateCourse(topic.value.trim())
    ElMessage.success(`已生成草稿课程《${data.name}》，请在编辑器中审改`)
    await load()
    // 打开生成的课程进行编辑
    const row = courses.value.find((c) => c.id === data.course_id)
    if (row) await openCourse(row)
  } catch { /* 错误提示已由拦截器处理 */ } finally {
    generating.value = false
  }
}

async function createEmpty() {
  try {
    const data = await trainingApi.createCourse({ name: `新课程-${dayjs().format('MMDDHHmm')}` })
    ElMessage.success('已创建草稿课程')
    await load()
    const row = courses.value.find((c) => c.id === data.course_id)
    if (row) await openCourse(row)
  } catch { /* 拦截器已提示 */ }
}

async function openCourse(row) {
  detailLoading.value = true
  dialogVisible.value = true
  activeScenario.value = []
  try {
    const data = await trainingApi.manageCourseDetail(row.id)
    const course = data.course
    form.id = course.id
    form.name = course.name
    form.description = course.description || ''
    form.difficulty = course.difficulty || 1
    form.scenarios = data.scenarios.map((s) => ({
      _key: nextKey(), _dirty: false,
      id: s.id, title: s.title, description: s.description || '',
      points: s.points, penalty_points: s.penalty_points,
      time_limit: s.time_limit, order_index: s.order_index,
      content: fromServerContent(s.content).content
    }))
    if (form.scenarios.length) activeScenario.value = [form.scenarios[0]._key]
  } finally {
    detailLoading.value = false
  }
}

function addScenario() {
  const sc = blankScenario()
  form.scenarios.push(sc)
  activeScenario.value = [sc._key]
}

function addFile(sc) {
  sc.content.files.push({ path: '', content: '' })
}
function removeFile(sc, fi) {
  sc.content.files.splice(fi, 1)
  sc._dirty = true
}
function addTask(sc) {
  sc.content.tasks.push(blankTask())
  sc._dirty = true
}
function removeTask(sc, ti) {
  sc.content.tasks.splice(ti, 1)
  sc._dirty = true
}

function scenarioPayload(sc) {
  return {
    title: sc.title,
    description: sc.description || null,
    points: sc.points,
    penalty_points: sc.penalty_points,
    time_limit: sc.time_limit || null,
    order_index: sc.order_index,
    content: toServerContent(sc)
  }
}

async function saveScenario(sc) {
  if (!sc.title.trim()) {
    ElMessage.warning('请填写场景标题')
    return
  }
  saving.value = true
  try {
    if (sc.id) {
      await trainingApi.updateScenario(sc.id, scenarioPayload(sc))
      ElMessage.success('场景已保存')
    } else {
      const data = await trainingApi.addScenario(form.id, scenarioPayload(sc))
      sc.id = data.id
      ElMessage.success('场景已创建')
    }
    sc._dirty = false
    await load()
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

async function saveCourse() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写课程名称')
    return
  }
  saving.value = true
  try {
    await trainingApi.updateCourse(form.id, {
      name: form.name,
      description: form.description || null,
      difficulty: form.difficulty
    })
    ElMessage.success('课程信息已保存')
    await load()
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

async function doPublish(id, name) {
  try {
    await trainingApi.publishCourse(id)
    ElMessage.success(`《${name}》已发布，学员端已收到推送`)
    await load()
  } catch { /* 拦截器已提示 */ }
}

async function publish(row) {
  await ElMessageBox.confirm(`确定发布《${row.name}》？发布后学员端将实时看到并收到通知。`, '发布课程', { type: 'warning' })
    .then(() => doPublish(row.id, row.name))
    .catch(() => {})
}

async function publishFromEditor() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写课程名称')
    return
  }
  if (!form.scenarios.length) {
    ElMessage.warning('课程至少包含 1 个场景才能发布')
    return
  }
  // 有未保存场景则先保存
  for (const sc of form.scenarios) {
    if (sc._dirty && sc.title.trim()) {
      await saveScenario(sc)
    }
  }
  await doPublish(form.id, form.name)
}

async function unpublish(row) {
  await ElMessageBox.confirm(`确定将《${row.name}》下线？学员端将立即看不到。`, '下线课程', { type: 'warning' })
    .then(async () => {
      await trainingApi.unpublishCourse(row.id)
      ElMessage.success('课程已下线')
      await load()
    })
    .catch(() => {})
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除课程《${row.name}》？删除后不可恢复。`, '删除课程', { type: 'warning' })
    .then(async () => {
      await trainingApi.deleteCourse(row.id)
      ElMessage.success('课程已删除')
      if (form.id === row.id) {
        dialogVisible.value = false
      }
      await load()
    })
    .catch(() => {})
}

async function removeScenario(sc) {
  await ElMessageBox.confirm(`确定删除场景《${sc.title}》？`, '删除场景', { type: 'warning' })
    .then(async () => {
      await trainingApi.deleteScenario(sc.id)
      form.scenarios.splice(form.scenarios.indexOf(sc), 1)
      ElMessage.success('场景已删除')
      await load()
    })
    .catch(() => {})
}

onMounted(load)
</script>

<style scoped>
.course-dialog { max-width: 92vw; }
.gen-card { margin-bottom: 14px; }
.gen-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.gen-label { font-weight: 600; }
.gen-tip { color: #909399; font-size: 12px; }
.list-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.list-head h3 { margin: 0; }
.course-form { margin-bottom: 6px; }
.sc-head { display: flex; align-items: center; justify-content: space-between; margin: 8px 0; }
.sc-head h4 { margin: 0; }
.sc-title { font-weight: 600; }
.dirty-tag { margin-left: 8px; }
.sep { margin: 0 8px; color: #c0c4cc; }
.files-wrap { width: 100%; }
.file-row { display: flex; gap: 8px; margin-bottom: 8px; width: 100%; }
.file-path { width: 220px; flex-shrink: 0; }
.file-body { flex: 1; }
.tasks-wrap { width: 100%; }
.task-card { border: 1px solid #ebeef5; border-radius: 6px; padding: 10px; margin-bottom: 10px; }
.task-head { display: flex; align-items: center; justify-content: space-between; font-weight: 600; margin-bottom: 8px; }
.task-grid { display: flex; gap: 8px; margin-bottom: 8px; }
.chk-label { width: 66px; flex-shrink: 0; line-height: 30px; color: #909399; font-size: 12px; }
.sc-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 4px; }
</style>
