<template>
  <div class="page">
    <el-card v-loading="loading">
      <div class="head">
        <div>
          <h3>🖥️ 设备监控</h3>
          <p class="sub">按数据范围展示资产设备，支持关键字/状态/类型过滤与在线探测。探测为模拟实现，仅更新在线状态。</p>
        </div>
        <div class="ops">
          <el-button :icon="'Download'" @click="exportDevices">导出 Excel</el-button>
          <el-upload :show-file-list="false" :auto-upload="false" accept=".xlsx,.csv" :on-change="onImportFile">
            <el-button v-permission="'monitor:device:manage'" :icon="'Upload'" :loading="importing">导入 Excel</el-button>
          </el-upload>
          <el-button :icon="'Document'" @click="downloadTemplate">下载模板</el-button>
          <el-button type="primary" v-permission="'monitor:device:manage'" @click="openDialog()">
            新增设备
          </el-button>
          <el-button :icon="'Refresh'" @click="load">刷新</el-button>
        </div>
      </div>

      <div class="filters">
        <el-input
          v-model="query.keyword" placeholder="名称 / IP / 位置" clearable style="width: 220px"
          @keyup.enter="load" @clear="load"
        />
        <el-select v-model="query.status" placeholder="状态" clearable style="width: 130px" @change="load">
          <el-option label="在线" value="active" />
          <el-option label="离线" value="offline" />
          <el-option label="维护" value="maintenance" />
        </el-select>
        <el-select v-model="query.device_type" placeholder="设备类型" clearable style="width: 130px" @change="load">
          <el-option v-for="t in deviceTypes" :key="t" :label="t" :value="t" />
        </el-select>
        <el-button type="primary" plain @click="load">查询</el-button>
      </div>

      <el-empty v-if="!items.length && !loading" description="暂无设备" />
      <el-table v-else :data="items" stripe>
        <el-table-column prop="name" label="设备名称" min-width="120" fixed="left">
          <template #default="{ row }">
            <span :class="['dot', row.status]"></span>{{ row.name }}
          </template>
        </el-table-column>
        <el-table-column prop="ip_address" label="IP 地址" min-width="130" />
        <el-table-column label="类型" width="110">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ row.device_type || '未知' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTag(row.status)">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="department_name" label="部门" width="110" />
        <el-table-column prop="owner_name" label="负责人" width="90" />
        <el-table-column prop="location" label="位置" min-width="110" show-overflow-tooltip />
        <el-table-column label="最近在线" width="180">
          <template #default="{ row }">
            <span class="muted">{{ row.last_seen_at ? fmt(row.last_seen_at) : '—' }}</span>
            <div v-if="row.offline_since" class="offline-note">离线自 {{ fmt(row.offline_since) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="ping(row)">探测</el-button>
            <el-button v-permission="'monitor:device:manage'" link type="primary" @click="openDialog(row)">编辑</el-button>
            <el-button v-permission="'monitor:device:manage'" link type="danger" @click="openDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        class="pager" background layout="total, prev, pager, next" :total="total"
        :page-size="query.size" v-model:current-page="query.page" @current-change="load"
      />
    </el-card>

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑设备' : '新增设备'" width="560px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="设备名称" prop="name"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="IP 地址" prop="ip_address">
          <el-input v-model="form.ip_address" :disabled="!!form.id" placeholder="如 10.0.10.11" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="MAC 地址"><el-input v-model="form.mac_address" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="设备类型">
              <el-select v-model="form.device_type" clearable style="width: 100%">
                <el-option v-for="t in deviceTypes" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="厂商"><el-input v-model="form.manufacturer" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="型号"><el-input v-model="form.model" /></el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="所属部门">
          <el-select v-model="form.department_id" clearable filterable style="width: 100%">
            <el-option v-for="d in flatDepts" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="位置"><el-input v-model="form.location" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="delVisible" title="删除设备" width="480px" :close-on-click-modal="false">
      <div v-if="delTarget" class="del-box">
        <el-descriptions :column="2" size="small" border>
          <el-descriptions-item label="设备名称">{{ delTarget.name }}</el-descriptions-item>
          <el-descriptions-item label="IP 地址">{{ delTarget.ip_address }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag size="small" :type="statusTag(delTarget.status)">{{ statusText(delTarget.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="类型">{{ delTarget.device_type || '—' }}</el-descriptions-item>
          <el-descriptions-item label="位置" :span="2">{{ delTarget.location || '—' }}</el-descriptions-item>
        </el-descriptions>
        <el-alert class="del-alert" type="warning" :closable="false"
          title="删除后将不可恢复；若设备关联告警，将自动转为归档保留。"
        />
        <el-form label-position="top">
          <el-form-item label="删除原因（审计留痕，可选）">
            <el-input v-model="delReason" type="textarea" :rows="3" maxlength="200" show-word-limit
              placeholder="如：设备下线报废 / 误录入 / 迁移替换…"
            />
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="delVisible = false">取消</el-button>
        <el-button type="danger" :loading="removing" @click="remove">确认删除</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { monitorApi } from '@/api/monitor'
import { departmentApi } from '@/api/departments'

const deviceTypes = ['server', 'switch', 'firewall', 'router', 'edr', 'workstation', 'database', 'other']
const statusText = (s) => ({ active: '在线', offline: '离线', maintenance: '维护', archived: '已归档' }[s] || s)
const statusTag = (s) => ({ active: 'success', offline: 'info', maintenance: 'warning', archived: 'danger' }[s] || 'info')
import { formatDateTime as fmt } from '@/utils/format'

const loading = ref(false)
const saving = ref(false)
const importing = ref(false)
const items = ref([])
const total = ref(0)
const query = reactive({ page: 1, size: 10, keyword: '', status: '', device_type: '' })
const dialogVisible = ref(false)
const formRef = ref()
const delVisible = ref(false)
const delTarget = ref(null)
const delReason = ref('')
const removing = ref(false)
const flatDepts = ref([])
const form = reactive({ id: null, name: '', ip_address: '', mac_address: '', device_type: '', manufacturer: '', model: '', department_id: null, location: '' })
const rules = {
  name: [{ required: true, message: '请输入设备名称', trigger: 'blur' }],
  ip_address: [{ required: true, message: '请输入 IP 地址', trigger: 'blur' }]
}

async function load(silent = false) {
  // silent：自动巡检刷新用，不触发整卡 loading，避免每 30s 一次遮罩闪烁
  if (!silent) loading.value = true
  try {
    const data = await monitorApi.devices({
      page: query.page, size: query.size,
      keyword: query.keyword || undefined,
      status: query.status || undefined,
      device_type: query.device_type || undefined
    })
    items.value = data.items
    total.value = data.total
  } finally {
    if (!silent) loading.value = false
  }
}

// 30s 静默自动刷新：让后台设备巡检的结果无需手动刷新即可见（仿 Scan.vue 轮询模式）
let patrolTimer = null
function startAutoRefresh() {
  stopAutoRefresh()
  patrolTimer = setInterval(() => load(true), 30000)
}
function stopAutoRefresh() {
  if (patrolTimer) { clearInterval(patrolTimer); patrolTimer = null }
}

async function loadDepts() {
  try {
    const roots = await departmentApi.tree()
    const flat = []
    const walk = (nodes, depth = 0) => {
      nodes.forEach((n) => {
        flat.push({ ...n, name: (depth ? '　'.repeat(depth) : '') + n.name })
        if (n.children?.length) walk(n.children, depth + 1)
      })
    }
    walk(Array.isArray(roots) ? roots : [])
    flatDepts.value = flat
  } catch { /* 部门加载失败不阻塞页面 */ }
}

function openDialog(row) {
  Object.assign(form, { id: null, name: '', ip_address: '', mac_address: '', device_type: '', manufacturer: '', model: '', department_id: null, location: '' })
  if (row) Object.assign(form, {
    id: row.id, name: row.name, ip_address: row.ip_address, mac_address: row.mac_address,
    device_type: row.device_type, manufacturer: row.manufacturer, model: row.model,
    department_id: row.department_id, location: row.location
  })
  dialogVisible.value = true
}

async function save() {
  await formRef.value.validate()
  saving.value = true
  try {
    const payload = { ...form }
    delete payload.id
    if (form.id) await monitorApi.updateDevice(form.id, payload)
    else await monitorApi.createDevice(payload)
    ElMessage.success(form.id ? '已保存' : '已创建')
    dialogVisible.value = false
    load()
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

async function ping(row) {
  try {
    const data = await monitorApi.pingDevice(row.id)
    ElMessage.success(`设备在线，最近在线 ${fmt(data.last_seen_at)}`)
    load()
  } catch { /* 拦截器已提示 */ }
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

async function exportDevices() {
  try {
    const blob = await monitorApi.exportDevices()
    downloadBlob(blob, `devices_${new Date().toISOString().slice(0, 10)}.xlsx`)
    ElMessage.success('已导出设备清单（XLSX）')
  } catch { /* 拦截器已提示 */ }
}

function downloadTemplate() {
  // 表头与后端 _DEVICE_IMPORT_COLUMNS 一致，UTF-8 BOM 保证 Excel 中文不乱码
  const header = 'name,ip_address,mac_address,device_type,manufacturer,model,location,department,status'
  const row = '示例设备,10.0.11.20,AA:BB:CC:DD:EE:FF,server,思科,WS-C2960,机房A,技术部,active'
  const blob = new Blob([`﻿${header}\n${row}\n`], { type: 'text/csv;charset=utf-8' })
  downloadBlob(blob, 'device_import_template.csv')
}

async function onImportFile(file) {
  const fd = new FormData()
  fd.append('file', file.raw)
  importing.value = true
  try {
    const res = await monitorApi.importDevices(fd)
    ElMessage.success(`导入完成：成功 ${res.created} 条`)
    if (res.failed?.length) {
      const brief = res.failed.slice(0, 3).map((f) => `第${f.row}行 ${f.error}`).join('；')
      ElMessage.warning(`失败 ${res.failed.length} 条：${brief}${res.failed.length > 3 ? '…' : ''}`)
    }
    load()
  } catch { /* 拦截器已提示 */ } finally {
    importing.value = false
  }
}

function openDelete(row) {
  delTarget.value = row
  delReason.value = ''
  delVisible.value = true
}

async function remove() {
  removing.value = true
  try {
    const data = await monitorApi.deleteDevice(delTarget.value.id, { reason: delReason.value || null })
    ElMessage.success(data.message)
    delVisible.value = false
    load()
  } catch { /* 拦截器已提示 */ } finally {
    removing.value = false
  }
}

onMounted(() => { load(); loadDepts(); startAutoRefresh() })
onBeforeUnmount(stopAutoRefresh)
</script>

<style scoped>
.head { display: flex; align-items: flex-start; justify-content: space-between; }
.head h3 { margin: 0 0 4px; }
.sub { margin: 0 0 12px; color: #909399; font-size: 13px; }
.ops { display: flex; gap: 8px; }
.filters { display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.dot.active { background: #67c23a; }
.dot.offline { background: #c0c4cc; }
.dot.maintenance { background: #e6a23c; }
.dot.archived { background: #f56c6c; }
.muted { color: #a8abb2; font-size: 12px; }
.offline-note { color: #f56c6c; font-size: 12px; margin-top: 2px; }
.pager { margin-top: 14px; justify-content: flex-end; }
.del-box .del-alert { margin: 12px 0; }
.del-box .el-form-item { margin-bottom: 0; }
</style>
