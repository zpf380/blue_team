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
          <template #header>团队训练排行 Top5</template>
          <el-table :data="stats.training_top || []" size="small" :loading="loading" border>
            <el-table-column type="index" label="#" width="50" />
            <el-table-column prop="name" label="学员" />
            <el-table-column prop="score" label="累计积分" width="120" align="right" />
          </el-table>
          <el-empty v-if="!(stats.training_top || []).length && !loading" :image-size="60" description="暂无训练积分记录" />
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card>
          <template #header>快捷操作</template>
          <div class="quick-actions">
            <el-button type="primary" plain @click="$router.push('/security/scan')">发起漏洞扫描</el-button>
            <el-button type="warning" plain @click="$router.push('/security/alerts')">告警中心</el-button>
            <el-button type="success" plain @click="$router.push('/attendance/review')">审批休假</el-button>
            <el-button plain @click="$router.push('/audit/logs')">审计日志</el-button>
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
const stats = reactive({ training_top: [] })

const cards = computed(() => {
  const defs = [
    { key: 'pending_reports', title: '待审扫描报告', color: '#F56C6C', format: (v) => (v ?? '—') },
    { key: 'unresolved_alerts', title: '高危未解决告警', color: '#E6A23C', format: (v) => (v ?? '—') },
    { key: 'pending_leaves', title: '待审休假申请', color: '#409EFF', format: (v) => (v ?? '—') },
    { key: 'compliance', title: '报告合规率', color: '#67C23A', format: (v) => (v == null ? '—' : `${v}%`) }
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
.quick-actions { display: flex; flex-direction: column; gap: 12px; align-items: flex-start; }
</style>
