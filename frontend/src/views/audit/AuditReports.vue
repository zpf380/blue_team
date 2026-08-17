<template>
  <div class="page">
    <el-card v-loading="statsLoading">
      <div class="head">
        <div>
          <h3>📋 合规审计报告</h3>
          <p class="sub">基于操作日志的合规统计与报告快照，供审计员与管理员追溯。统计数据默认近 14 天，可指定周期生成快照。</p>
        </div>
        <div class="ops">
          <el-date-picker
            v-model="range" type="daterange" range-separator="至"
            start-placeholder="开始日期" end-placeholder="结束日期"
            value-format="YYYY-MM-DD" style="width: 240px"
          />
          <el-button :icon="'Refresh'" @click="loadStats">刷新</el-button>
        </div>
      </div>

      <el-row :gutter="14" class="cards">
        <el-col v-for="c in cards" :key="c.title" :span="6">
          <div class="stat-card">
            <div class="stat-value" :style="{ color: c.color }">{{ c.value }}</div>
            <div class="stat-title">{{ c.title }}</div>
          </div>
        </el-col>
      </el-row>

      <el-row :gutter="14" class="charts">
        <el-col :span="14">
          <div ref="trendRef" style="height: 260px"></div>
        </el-col>
        <el-col :span="10">
          <div ref="actionRef" style="height: 260px"></div>
        </el-col>
      </el-row>
    </el-card>

    <el-row :gutter="14" class="mt14">
      <el-col :span="10">
        <el-card v-loading="statsLoading">
          <template #header>用户活跃排行</template>
          <div ref="userRef" style="height: 280px"></div>
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card v-loading="statsLoading">
          <template #header>近期敏感操作（<span class="red">需关注</span>）</template>
          <el-table :data="sensitiveRows" size="small" max-height="280">
            <el-table-column prop="username" label="操作人" width="90" />
            <el-table-column prop="action" label="动作" min-width="130" />
            <el-table-column prop="target_type" label="对象" width="90" />
            <el-table-column prop="target_id" label="对象ID" width="70" />
            <el-table-column prop="ip_address" label="IP" width="120" />
            <el-table-column label="时间" min-width="150">
              <template #default="{ row }">{{ row.created_at ? new Date(row.created_at).toLocaleString('zh-CN') : '—' }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!sensitiveRows.length" :image-size="60" description="统计周期内无敏感操作" />
        </el-card>
      </el-col>
    </el-row>

    <el-card class="mt14 report-card" v-loading="reportLoading">
      <div class="head">
        <h3 class="rpt-title">报告快照</h3>
        <div class="ops">
          <el-select v-model="reportType" placeholder="周期" clearable style="width: 110px" @change="loadReports">
            <el-option label="日报" value="daily" />
            <el-option label="周报" value="weekly" />
            <el-option label="月报" value="monthly" />
            <el-option label="按需" value="on_demand" />
          </el-select>
          <el-button type="primary" @click="generate">生成报告</el-button>
        </div>
      </div>
      <el-table :data="reports" stripe>
        <el-table-column prop="title" label="报告标题" min-width="280" show-overflow-tooltip />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">{{ typeText(row.report_type) }}</template>
        </el-table-column>
        <el-table-column prop="generated_by_name" label="生成人" width="100" />
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ row.created_at ? new Date(row.created_at).toLocaleString('zh-CN') : '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="viewReport(row)">详情</el-button>
            <el-button link type="success" @click="exportReport(row)">导出 CSV</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        class="pager" background layout="total, prev, pager, next" :total="reportTotal"
        :page-size="reportQuery.size" v-model:current-page="reportQuery.page" @current-change="loadReports"
      />
    </el-card>

    <el-dialog v-model="detailVisible" title="报告详情" width="680px">
      <div v-if="detail" v-loading="detailLoading">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="标题">{{ detail.title }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ typeText(detail.report_type) }}</el-descriptions-item>
          <el-descriptions-item label="统计周期">{{ detail.date_from }} ~ {{ detail.date_to }}</el-descriptions-item>
          <el-descriptions-item label="生成人">{{ detail.generated_by_name }}</el-descriptions-item>
        </el-descriptions>
        <p class="summary">{{ detail.summary }}</p>

        <el-row :gutter="12">
          <el-col :span="14"><div ref="detailTrendRef" style="height: 200px"></div></el-col>
          <el-col :span="10"><div ref="detailActionRef" style="height: 200px"></div></el-col>
        </el-row>

        <h4 class="sec">敏感操作明细</h4>
        <el-table :data="detail.report_data?.sensitive || []" size="small" max-height="220">
          <el-table-column prop="username" label="操作人" width="90" />
          <el-table-column prop="action" label="动作" min-width="130" />
          <el-table-column prop="ip_address" label="IP" width="120" />
          <el-table-column label="时间" min-width="150">
            <template #default="{ row }">{{ row.created_at ? new Date(row.created_at).toLocaleString('zh-CN') : '—' }}</template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { auditApi } from '@/api/audit'
import { downloadWithAuth } from '@/utils/download'

echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const typeText = (t) => ({ daily: '日报', weekly: '周报', monthly: '月报', on_demand: '按需' }[t] || t)

const statsLoading = ref(false)
const reportLoading = ref(false)
const range = ref([])
const cards = ref([
  { title: '总操作数', value: '—', color: '#409EFF' },
  { title: '活跃用户', value: '—', color: '#67C23A' },
  { title: '敏感操作', value: '—', color: '#F56C6C' },
  { title: '登录次数', value: '—', color: '#E6A23C' }
])
const sensitiveRows = ref([])

const trendRef = ref(null)
const actionRef = ref(null)
const userRef = ref(null)
const charts = []

function render(dom, option) {
  if (!dom) return
  const chart = echarts.init(dom)
  chart.setOption(option)
  charts.push(chart)
}

function renderStats(s) {
  cards.value[0].value = s.total_ops
  cards.value[1].value = s.active_users
  cards.value[2].value = s.sensitive_ops
  cards.value[3].value = s.logins
  sensitiveRows.value = s.sensitive || []

  render(trendRef.value, {
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 20, top: 30, bottom: 30 },
    xAxis: { type: 'category', data: (s.trend || []).map((d) => d.date.slice(5)), boundaryGap: false },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{
      name: '操作量', type: 'line', smooth: true, symbolSize: 6,
      data: (s.trend || []).map((d) => d.count),
      areaStyle: { opacity: 0.15 },
      itemStyle: { color: '#409EFF' }
    }]
  })
  render(actionRef.value, {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, type: 'scroll' },
    series: [{
      name: '操作分布', type: 'pie', radius: ['38%', '64%'], center: ['50%', '44%'],
      data: (s.actions || []).map((a) => ({ name: a.action, value: a.count }))
    }]
  })
  const top = (s.users || []).slice(0, 6).reverse()
  render(userRef.value, {
    tooltip: { trigger: 'axis' },
    grid: { left: 80, right: 30, top: 10, bottom: 30 },
    xAxis: { type: 'value', minInterval: 1 },
    yAxis: { type: 'category', data: top.map((u) => u.username) },
    series: [{
      type: 'bar', barWidth: 14,
      data: top.map((u) => u.count),
      itemStyle: { color: '#67C23A', borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: 'right' }
    }]
  })
}

function disposeCharts() {
  charts.forEach((c) => c?.dispose())
  charts.length = 0
}

async function loadStats() {
  statsLoading.value = true
  try {
    const params = {}
    if (range.value?.length === 2) { params.date_from = range.value[0]; params.date_to = range.value[1] }
    const s = await auditApi.reportStats(params)
    await nextTick()
    disposeCharts()
    renderStats(s)
  } finally { statsLoading.value = false }
}

const reports = ref([])
const reportTotal = ref(0)
const reportType = ref('')
const reportQuery = reactive({ page: 1, size: 10 })

async function loadReports() {
  reportLoading.value = true
  try {
    const data = await auditApi.reports({ page: reportQuery.page, size: reportQuery.size, report_type: reportType.value || undefined })
    reports.value = data.items
    reportTotal.value = data.total
  } finally { reportLoading.value = false }
}

async function generate() {
  try {
    const data = await auditApi.createReport({ report_type: 'on_demand' })
    ElMessage.success(`已生成报告：${data.title}`)
    loadReports()
  } catch { /* 拦截器已提示 */ }
}

function exportReport(row) {
  downloadWithAuth(`/api/v1/audit/reports/${row.id}/export`, `audit_report_${row.id}.csv`)
}

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref(null)
const detailTrendRef = ref(null)
const detailActionRef = ref(null)

async function viewReport(row) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await auditApi.report(row.id)
    await nextTick()
    const d = detail.value.report_data || {}
    render(detailTrendRef.value, {
      tooltip: { trigger: 'axis' },
      grid: { left: 40, right: 20, top: 20, bottom: 30 },
      xAxis: { type: 'category', data: (d.trend || []).map((x) => x.date.slice(5)), boundaryGap: false },
      yAxis: { type: 'value', minInterval: 1 },
      series: [{ type: 'line', smooth: true, data: (d.trend || []).map((x) => x.count), areaStyle: { opacity: 0.15 }, itemStyle: { color: '#409EFF' } }]
    })
    render(detailActionRef.value, {
      tooltip: { trigger: 'item' },
      series: [{ type: 'pie', radius: ['35%', '62%'], data: (d.actions || []).map((a) => ({ name: a.action, value: a.count })) }]
    })
  } finally { detailLoading.value = false }
}

function handleResize() { charts.forEach((c) => c?.resize()) }

onMounted(() => { loadStats(); loadReports(); window.addEventListener('resize', handleResize) })
onBeforeUnmount(() => { window.removeEventListener('resize', handleResize); disposeCharts() })
</script>

<style scoped>
.head { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 12px; }
.head h3 { margin: 0 0 4px; }
.sub { margin: 0; color: #909399; font-size: 13px; }
.ops { display: flex; gap: 8px; align-items: center; }
.cards { margin-top: 14px; }
.stat-card { text-align: center; padding: 12px 0; }
.stat-value { font-size: 30px; font-weight: 700; }
.stat-title { color: #999; margin-top: 6px; font-size: 13px; }
.charts { margin-top: 8px; }
.mt14 { margin-top: 14px; }
.red { color: #f56c6c; }
.report-card .head { margin-bottom: 12px; }
.rpt-title { margin: 0; font-size: 16px; }
.pager { margin-top: 14px; justify-content: flex-end; }
.summary { color: #606266; font-size: 13px; margin: 12px 0; }
.sec { margin: 14px 0 8px; }
</style>
