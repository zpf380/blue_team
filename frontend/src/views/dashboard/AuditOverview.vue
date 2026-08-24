<template>
  <div>
    <el-row :gutter="16">
      <el-col v-for="card in cards" :key="card.key" :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value" :style="{ color: card.color }">{{ card.value }}</div>
          <div class="stat-title">{{ card.title }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="mt16">
      <el-col :span="14">
        <el-card>
          <template #header>审计总览</template>
          <p class="muted">只读模式：审计员实时掌握平台操作流与安全事件。近 7 天异常事件来自登录暴力破解锁定（auth:lock）；报告合规率按已审核扫描报告统计。</p>
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card>
          <template #header>快捷入口</template>
          <div class="quick-actions">
            <el-button type="primary" @click="$router.push('/audit/logs')">查看操作日志</el-button>
            <el-button type="success" plain @click="$router.push('/audit/reports')">合规报告</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { statsApi } from '@/api/stats'

const loading = ref(false)
const stats = reactive({})

const cards = computed(() => {
  const defs = [
    { key: 'today_ops', title: '今日操作数', color: '#409EFF', format: (v) => (v ?? '—') },
    { key: 'anomalies', title: '近7天异常事件', color: '#F56C6C', format: (v) => (v ?? '—') },
    { key: 'compliance', title: '报告合规率', color: '#67C23A', format: (v) => (v == null ? '—' : `${v}%`) },
    { key: 'pending_reviews', title: '待核查报告', color: '#E6A23C', format: (v) => (v ?? '—') }
  ]
  return defs.map((d) => ({ ...d, value: d.format(stats[d.key]) }))
})

onMounted(async () => {
  loading.value = true
  try {
    const data = await statsApi.workspace()
    Object.assign(stats, data.stats || {})
  } catch (e) {
    ElMessage.error(e?.message || '工作台数据加载失败')
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.stat-card { text-align: center; }
.stat-value { font-size: 32px; font-weight: 700; }
.stat-title { color: #999; margin-top: 6px; }
.mt16 { margin-top: 16px; }
.muted { color: #666; }
.quick-actions { display: flex; flex-direction: column; gap: 12px; align-items: flex-start; }
</style>
