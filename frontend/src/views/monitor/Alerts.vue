<template>
  <div class="page">
    <el-card v-loading="loading">
      <div class="head">
        <div>
          <h3>🚨 告警管理</h3>
          <p class="sub">汇聚设备安全事件告警，支持确认与解决闭环流转。</p>
        </div>
        <div class="ops">
          <el-button type="primary" v-permission="'monitor:alert:manage'" @click="openCreate">新增告警</el-button>
          <el-button :icon="'Refresh'" @click="load">刷新</el-button>
        </div>
      </div>

      <div class="filters">
        <el-select v-model="query.status" placeholder="状态" clearable style="width: 130px" @change="load">
          <el-option label="待处理" value="open" />
          <el-option label="已确认" value="acknowledged" />
          <el-option label="已解决" value="resolved" />
        </el-select>
        <el-select v-model="query.severity" placeholder="级别" clearable style="width: 130px" @change="load">
          <el-option v-for="s in severities" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
        <el-button type="primary" plain @click="load">查询</el-button>
      </div>

      <el-empty v-if="!items.length && !loading" description="暂无告警" />
      <el-table v-else :data="items" stripe>
        <el-table-column label="级别" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="sevTag(row.severity)">{{ sevText(row.severity) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="告警标题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="device_name" label="关联设备" width="120">
          <template #default="{ row }">{{ row.device_name || '—' }}</template>
        </el-table-column>
        <el-table-column prop="alert_type" label="类型" width="100" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTag(row.status)">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="acknowledged_by_name" label="处理人" width="100">
          <template #default="{ row }">{{ row.acknowledged_by_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="时间" width="170">
          <template #default="{ row }">
            <div class="muted">{{ fmt(row.created_at) }}</div>
            <div v-if="row.resolved_at" class="muted green">解决 {{ fmt(row.resolved_at) }}</div>
            <div v-if="row.notified_at" class="muted blue">通知 {{ fmt(row.notified_at) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'open'">
              <el-button v-permission="'monitor:alert:manage'" link type="warning" @click="ack(row)">确认</el-button>
              <el-button v-permission="'monitor:alert:manage'" link type="success" @click="resolve(row)">解决</el-button>
            </template>
            <span v-else-if="row.status === 'acknowledged'">
              <el-button v-permission="'monitor:alert:manage'" link type="success" @click="resolve(row)">解决</el-button>
            </span>
            <span v-else class="muted">已闭环</span>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        class="pager" background layout="total, prev, pager, next" :total="total"
        :page-size="query.size" v-model:current-page="query.page" @current-change="load"
      />
    </el-card>

    <el-dialog v-model="visible" title="新增告警" width="500px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="告警级别">
          <el-select v-model="form.severity" style="width: 100%">
            <el-option v-for="s in severities" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="告警类型">
          <el-select v-model="form.alert_type" clearable style="width: 100%">
            <el-option v-for="t in alertTypes" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="关联设备">
          <el-select v-model="form.device_id" clearable filterable style="width: 100%">
            <el-option v-for="d in devices" :key="d.id" :label="`${d.name}（${d.ip_address}）`" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题" prop="title"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { monitorApi } from '@/api/monitor'

import { formatDateTime as fmt } from '@/utils/format'
const severities = [
  { value: 'critical', label: '严重', tag: 'danger' },
  { value: 'high', label: '高危', tag: 'danger' },
  { value: 'medium', label: '中危', tag: 'warning' },
  { value: 'low', label: '低危', tag: 'info' },
  { value: 'info', label: '提示', tag: 'info' }
]
const sevText = (v) => severities.find((s) => s.value === v)?.label || v
const sevTag = (v) => severities.find((s) => s.value === v)?.tag || 'info'
const statusText = (s) => ({ open: '待处理', acknowledged: '已确认', resolved: '已解决' }[s] || s)
const statusTag = (s) => ({ open: 'danger', acknowledged: 'warning', resolved: 'success' }[s] || 'info')
const alertTypes = ['intrusion', 'malware', 'abnormal', 'resource_exhaustion', 'compliance', 'other']

const loading = ref(false)
const items = ref([])
const total = ref(0)
const query = reactive({ page: 1, size: 10, status: '', severity: '' })
const devices = ref([])

const visible = ref(false)
const saving = ref(false)
const formRef = ref()
const form = reactive({ severity: 'medium', alert_type: '', device_id: null, title: '', description: '' })
const rules = { title: [{ required: true, message: '请输入告警标题', trigger: 'blur' }] }

async function load() {
  loading.value = true
  try {
    const data = await monitorApi.alerts({
      page: query.page, size: query.size,
      status: query.status || undefined,
      severity: query.severity || undefined
    })
    items.value = data.items
    total.value = data.total
  } finally { loading.value = false }
}

async function loadDevices() {
  try { devices.value = (await monitorApi.devices({ size: 500 })).items } catch { /* 忽略 */ }
}

function openCreate() {
  Object.assign(form, { severity: 'medium', alert_type: '', device_id: null, title: '', description: '' })
  visible.value = true
}

async function save() {
  await formRef.value.validate()
  saving.value = true
  try {
    await monitorApi.createAlert({
      ...form,
      alert_type: form.alert_type || undefined,
      device_id: form.device_id || undefined,
      description: form.description || undefined
    })
    ElMessage.success('告警已提交')
    visible.value = false
    load()
  } catch { /* 拦截器已提示 */ } finally { saving.value = false }
}

async function ack(row) {
  try {
    await monitorApi.acknowledgeAlert(row.id)
    ElMessage.success('已确认')
    load()
  } catch { /* 拦截器已提示 */ }
}

async function resolve(row) {
  try {
    await ElMessageBox.confirm(`确认将告警「${row.title}」标记为已解决？`, '解决告警', { type: 'info' })
  } catch {
    return // 用户取消
  }
  try {
    await monitorApi.resolveAlert(row.id)
    ElMessage.success('已解决')
    load()
  } catch { /* 拦截器已提示 */ }
}

onMounted(() => { load(); loadDevices() })
</script>

<style scoped>
.head { display: flex; align-items: flex-start; justify-content: space-between; }
.head h3 { margin: 0 0 4px; }
.sub { margin: 0 0 12px; color: #909399; font-size: 13px; }
.ops { display: flex; gap: 8px; }
.filters { display: flex; gap: 10px; margin-bottom: 12px; }
.muted { color: #a8abb2; font-size: 12px; }
.muted.green { color: #67c23a; }
.muted.blue { color: #409eff; }
.pager { margin-top: 14px; justify-content: flex-end; }
</style>
