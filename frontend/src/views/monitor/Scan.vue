<template>
  <div class="page">
    <el-card class="auth-card">
      <div class="head">
        <div>
          <h3>🛡️ 扫描授权名单</h3>
          <p class="sub">扫描/发现目标必须为内网地址，且落在「已登记子网」或本授权名单内；吊销或过期后立即失效。</p>
        </div>
        <el-button v-if="isReviewer" type="primary" @click="openAuthDialog">登记授权</el-button>
      </div>
      <el-table :data="auths" size="small" stripe>
        <el-table-column prop="network" label="授权网段" width="160" />
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'revoked' ? 'info' : row.expired ? 'danger' : 'success'">
              {{ row.status === 'revoked' ? '已吊销' : row.expired ? '已过期' : '生效中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="有效期" width="230">
          <template #default="{ row }">{{ fmt(row.start_date) }} ~ {{ fmt(row.end_date) || '长期' }}</template>
        </el-table-column>
        <el-table-column prop="approved_by_name" label="批准人" width="110" />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button v-if="isReviewer && row.status === 'active' && !row.expired" link type="danger" @click="revokeAuth(row)">吊销</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="scan-card">
      <div class="head">
        <div>
          <h3>🔍 漏洞扫描</h3>
          <p class="sub">针对已登记网段内的目标 IP 发起真实 nmap 探测；报告需 manager/admin 审核后生效。</p>
        </div>
      </div>
      <el-form :model="scanForm" inline @submit.prevent>
        <el-form-item label="目标 IP">
          <el-input v-model="scanForm.target_ip" placeholder="如 10.0.10.11" style="width: 180px" />
        </el-form-item>
        <el-form-item label="报告类型">
          <el-select v-model="scanForm.report_type" style="width: 130px">
            <el-option label="按需扫描" value="on_demand" />
            <el-option label="日报" value="daily" />
            <el-option label="周报" value="weekly" />
            <el-option label="月报" value="monthly" />
          </el-select>
        </el-form-item>
        <el-form-item label="端口数">
          <el-input-number v-model="scanForm.ports" :min="1" :max="10000" placeholder="默认 100" style="width: 130px" />
        </el-form-item>
        <el-form-item label="关联设备">
          <el-select v-model="scanForm.device_id" clearable filterable style="width: 200px">
            <el-option v-for="d in devices" :key="d.id" :label="`${d.name}（${d.ip_address}）`" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="scanning" @click="runScan">开始扫描</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="report-card" v-loading="loading">
      <div class="head">
        <h3 class="reports-title">扫描报告</h3>
        <div class="ops">
          <el-select v-model="query.status" placeholder="状态" clearable style="width: 130px" @change="load">
            <el-option label="待审核" value="pending_review" />
            <el-option label="已通过" value="approved" />
            <el-option label="已驳回" value="rejected" />
          </el-select>
          <el-button :icon="'Refresh'" @click="load">刷新</el-button>
        </div>
      </div>

      <el-table :data="items" stripe>
        <el-table-column prop="target_ip" label="目标 IP" min-width="130" />
        <el-table-column prop="device_name" label="关联设备" width="120">
          <template #default="{ row }">{{ row.device_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="风险评分" min-width="160">
          <template #default="{ row }">
            <span v-if="row.scan_status !== 'completed'" class="risk-wait">—</span>
            <el-progress v-else :percentage="row.risk_score" :stroke-width="8" :color="riskColor(row.risk_score)" />
          </template>
        </el-table-column>
        <el-table-column prop="summary" label="摘要" min-width="260" show-overflow-tooltip />
        <el-table-column label="扫描状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="scanStatusTag(row.scan_status)">{{ scanStatusText(row.scan_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTag(row.status)">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="report_type" label="类型" width="90">
          <template #default="{ row }">{{ typeText(row.report_type) }}</template>
        </el-table-column>
        <el-table-column prop="generated_by_name" label="生成人" width="100" />
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ fmt(row.generated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="viewDetail(row)">详情</el-button>
            <template v-if="row.status === 'pending_review' && isReviewer">
              <el-button link type="success" @click="review(row, true)">通过</el-button>
              <el-button link type="danger" @click="review(row, false)">驳回</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        class="pager" background layout="total, prev, pager, next" :total="total"
        :page-size="query.size" v-model:current-page="query.page" @current-change="load"
      />
    </el-card>

    <el-dialog v-model="authDialog" title="登记扫描授权" width="460px">
      <el-form :model="authForm" label-width="90px">
        <el-form-item label="授权网段" required>
          <el-input v-model="authForm.network" placeholder="如 10.0.30.0/24（仅内网）" />
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="authForm.name" placeholder="如 研发网段" maxlength="100" />
        </el-form-item>
        <el-form-item label="到期时间">
          <el-date-picker v-model="authForm.end_date" type="datetime" placeholder="留空则长期有效" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="authForm.note" placeholder="授权用途说明" maxlength="200" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="authDialog = false">取消</el-button>
        <el-button type="primary" :loading="authSaving" @click="submitAuth">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="扫描报告详情" width="640px">
      <div v-if="detail" v-loading="detailLoading">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="目标 IP">{{ detail.target_ip }}</el-descriptions-item>
          <el-descriptions-item label="风险评分">{{ detail.risk_score ?? '—' }} / 100</el-descriptions-item>
          <el-descriptions-item label="报告类型">{{ typeText(detail.report_type) }}</el-descriptions-item>
          <el-descriptions-item label="扫描状态">
            <el-tag size="small" :type="scanStatusTag(detail.scan_status)">{{ scanStatusText(detail.scan_status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag size="small" :type="statusTag(detail.status)">{{ statusText(detail.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="生成人">{{ detail.generated_by_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="审核人">{{ detail.approved_by_name || '—' }}</el-descriptions-item>
        </el-descriptions>

        <div v-if="detail.error" class="err-box">
          <el-alert type="error" :closable="false" :title="detail.error" />
        </div>

        <h4 class="sec">开放端口</h4>
        <el-space wrap>
          <el-tag v-for="p in detail.scan_data?.open_ports || []" :key="typeof p === 'number' ? p : p.port" type="info">
            {{ typeof p === 'number' ? p : `${p.port}/${p.protocol} ${p.service || ''}${p.version ? ' ' + p.version : ''}` }}
          </el-tag>
        </el-space>

        <h4 class="sec">发现漏洞</h4>
        <el-empty v-if="!(detail.scan_data?.vulnerabilities || []).length" description="未发现漏洞" :image-size="60" />
        <div v-else class="vuln-list">
          <div v-for="(v, i) in detail.scan_data.vulnerabilities" :key="i" class="vuln-row">
            <el-tag size="small" :type="sevTag(v.severity)">{{ sevText(v.severity) }}</el-tag>
            <span class="vuln-name">{{ v.name }}</span>
            <span v-if="v.cve" class="vuln-cve">{{ v.cve }}</span>
          </div>
        </div>

        <h4 class="sec">摘要</h4>
        <p class="summary">{{ detail.summary }}</p>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { monitorApi } from '@/api/monitor'
import { useUserStore } from '@/stores/user'

const fmt = (s) => (s ? new Date(s).toLocaleString('zh-CN') : '—')
const typeText = (t) => ({ daily: '日报', weekly: '周报', monthly: '月报', on_demand: '按需' }[t] || t)
const statusText = (s) => ({ pending_review: '待审核', approved: '已通过', rejected: '已驳回' }[s] || s)
const statusTag = (s) => ({ pending_review: 'warning', approved: 'success', rejected: 'danger' }[s] || 'info')
const scanStatusText = (s) => ({ pending: '排队中', running: '扫描中', completed: '已完成', failed: '失败' }[s] || s)
const scanStatusTag = (s) => ({ pending: 'info', running: 'warning', completed: 'success', failed: 'danger' }[s] || 'info')
const sevText = (v) => ({ critical: '严重', high: '高危', medium: '中危', low: '低危', info: '提示' }[v] || v)
const sevTag = (v) => ({ critical: 'danger', high: 'danger', medium: 'warning', low: 'info', info: 'info' }[v] || 'info')
const riskColor = (score) => (score >= 70 ? '#f56c6c' : score >= 40 ? '#e6a23c' : '#67c23a')

const userStore = useUserStore()
const isReviewer = computed(() => ['manager', 'admin'].includes(userStore.role))

const loading = ref(false)
const scanning = ref(false)
const items = ref([])
const total = ref(0)
const query = reactive({ page: 1, size: 10, status: '' })
const devices = ref([])
const scanForm = reactive({ target_ip: '', report_type: 'on_demand', device_id: null, ports: null })

let pollTimer = null
let pollReportId = null
let pollTries = 0

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  pollReportId = null
}

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref(null)

// 扫描授权名单
const auths = ref([])
const authDialog = ref(false)
const authSaving = ref(false)
const authForm = reactive({ network: '', name: '', end_date: null, note: '' })

async function loadAuths() {
  try { auths.value = await monitorApi.scanAuths() } catch { /* 拦截器已提示 */ }
}

function openAuthDialog() {
  authForm.network = ''; authForm.name = ''; authForm.end_date = null; authForm.note = ''
  authDialog.value = true
}

async function submitAuth() {
  if (!authForm.network.trim() || !authForm.name.trim()) {
    ElMessage.warning('请填写授权网段与名称')
    return
  }
  authSaving.value = true
  try {
    await monitorApi.createScanAuth({
      network: authForm.network.trim(),
      name: authForm.name.trim(),
      end_date: authForm.end_date ? new Date(authForm.end_date).toISOString() : undefined,
      note: authForm.note.trim() || undefined
    })
    ElMessage.success('授权已登记')
    authDialog.value = false
    loadAuths()
  } catch { /* 拦截器已提示 */ } finally { authSaving.value = false }
}

async function revokeAuth(row) {
  try {
    await ElMessageBox.confirm(`确认吊销「${row.network}」的扫描授权？吊销后立即失效。`, '吊销授权', { type: 'warning' })
    await monitorApi.revokeScanAuth(row.id)
    ElMessage.success('授权已吊销')
    loadAuths()
  } catch { /* 取消或失败 */ }
}

async function load() {
  loading.value = true
  try {
    const data = await monitorApi.scanReports({ page: query.page, size: query.size, status: query.status || undefined })
    items.value = data.items
    total.value = data.total
  } finally { loading.value = false }
}

async function loadDevices() {
  try { devices.value = (await monitorApi.devices({ size: 500 })).items } catch { /* 忽略 */ }
}

async function runScan() {
  if (!scanForm.target_ip.trim()) {
    ElMessage.warning('请输入目标 IP')
    return
  }
  if (scanning.value) return  // 扫描中防重复提交
  scanning.value = true
  try {
    const data = await monitorApi.createScan({
      target_ip: scanForm.target_ip.trim(),
      report_type: scanForm.report_type,
      device_id: scanForm.device_id || undefined,
      ports: scanForm.ports || undefined
    })
    stopPolling()
    pollReportId = data.report_id
    pollTries = 0
    ElMessage.info('扫描已提交，后台执行中…')
    pollTimer = setInterval(pollScan, 2000)
  } catch { /* 拦截器已提示 */ }
}

async function pollScan() {
  if (!pollReportId) return
  pollTries += 1
  let d
  try { d = await monitorApi.scanReport(pollReportId) } catch { /* 单次失败忽略，继续轮询 */ }
  if (d?.scan_status === 'completed') {
    stopPolling()
    scanning.value = false
    ElMessage.success(`扫描完成：开放端口 ${d.scan_data?.open_ports?.length ?? 0} 个、风险 ${d.scan_data?.vulnerabilities?.length ?? 0} 项，评分 ${d.risk_score}`)
    scanForm.target_ip = ''
    load()
  } else if (d?.scan_status === 'failed') {
    stopPolling()
    scanning.value = false
    ElMessage.error(`扫描失败：${d.error || '未知错误'}`)
    load()
  } else if (pollTries >= 75) {  // 2s × 75 ≈ 2.5 分钟
    stopPolling()
    scanning.value = false
    ElMessage.warning('等待超时，请到报告列表查看状态')
    load()
  }
}

async function viewDetail(row) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try { detail.value = await monitorApi.scanReport(row.id) } finally { detailLoading.value = false }
}

async function review(row, approve) {
  try {
    await ElMessageBox.confirm(
      approve ? `确认通过报告「${row.target_ip}」的审核？` : `确认驳回报告「${row.target_ip}」？`,
      approve ? '审核通过' : '审核驳回', { type: 'warning' }
    )
    await monitorApi.reviewScanReport(row.id, approve)
    ElMessage.success(approve ? '报告已通过' : '报告已驳回')
    load()
  } catch { /* 取消或失败 */ }
}

onMounted(() => { load(); loadDevices(); loadAuths() })
onBeforeUnmount(stopPolling)
</script>

<style scoped>
.auth-card { margin-bottom: 14px; }
.auth-card .head { margin-bottom: 10px; }
.scan-card .head { margin-bottom: 8px; }
.head { display: flex; justify-content: space-between; align-items: center; }
.head h3 { margin: 0 0 4px; }
.sub { margin: 0 0 10px; color: #909399; font-size: 13px; }
.report-card { margin-top: 14px; }
.reports-title { margin: 0; font-size: 16px; }
.ops { display: flex; gap: 8px; align-items: center; }
.pager { margin-top: 14px; justify-content: flex-end; }
.sec { margin: 16px 0 8px; }
.vuln-list { display: flex; flex-direction: column; gap: 8px; }
.vuln-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border: 1px solid #f0f2f5; border-radius: 6px; }
.vuln-name { font-size: 13px; flex: 1; }
.vuln-cve { color: #909399; font-size: 12px; }
.summary { color: #606266; font-size: 13px; margin: 0; }
.risk-wait { color: #c0c4cc; }
.err-box { margin-top: 12px; }
</style>
