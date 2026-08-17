<template>
  <div>
    <el-row :gutter="16">
      <el-col v-for="card in cards" :key="card.title" :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value" :style="{ color: card.color }">{{ card.value }}</div>
          <div class="stat-title">{{ card.title }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="mt16">
      <el-col :span="14">
        <el-card>
          <template #header>角色分布</template>
          <div ref="chartRef" style="height: 300px"></div>
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card>
          <template #header>用户状态</template>
          <el-table :data="statusRows" size="small" border>
            <el-table-column prop="label" label="状态" />
            <el-table-column prop="value" label="数量" width="80" align="right" />
          </el-table>
          <el-empty v-if="!statusRows.length" :image-size="60" description="暂无用户" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { statsApi } from '@/api/stats'

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

const cards = ref([
  { title: '用户总数', value: '—', color: '#409EFF' },
  { title: '部门数量', value: '—', color: '#67C23A' },
  { title: '今日登录', value: '—', color: '#E6A23C' },
  { title: '操作日志', value: '—', color: '#F56C6C' }
])

const chartRef = ref(null)
const statusRows = ref([])
let chart = null

function renderChart(roleDistribution) {
  chart = echarts.init(chartRef.value)
  chart.setOption({
    tooltip: {},
    grid: { left: 40, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: roleDistribution.map((r) => r.name) },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      {
        type: 'bar',
        barWidth: 36,
        data: roleDistribution.map((r) => r.count),
        itemStyle: { color: '#409EFF', borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: 'top' }
      }
    ]
  })
}

function handleResize() {
  chart?.resize()
}

onMounted(async () => {
  const stats = await statsApi.overview()
  cards.value[0].value = stats.users.total
  cards.value[1].value = stats.departments
  cards.value[2].value = stats.today_logins
  cards.value[3].value = stats.ops_logs
  statusRows.value = [
    { label: '在职', value: stats.users.active },
    { label: '休假', value: stats.users.on_leave },
    { label: '外勤', value: stats.users.business_trip },
    { label: '禁用', value: stats.users.disabled },
    { label: '离职归档', value: stats.users.archived }
  ].filter((r) => r.value > 0)
  renderChart(stats.role_distribution || [])
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
})
</script>

<style scoped>
.stat-card { text-align: center; }
.stat-value { font-size: 32px; font-weight: 700; }
.stat-title { color: #999; margin-top: 6px; }
.mt16 { margin-top: 16px; }
</style>
