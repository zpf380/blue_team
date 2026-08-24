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
          <template #header>训练计划</template>
          <p class="muted">进入智能体实训完成攻防场景获取积分；已获徽章与完成场景将累积到能力综合分与团队排行。</p>
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card>
          <template #header>快捷操作</template>
          <div class="quick-actions">
            <el-button type="primary" plain @click="$router.push('/training/agents')">智能体实训</el-button>
            <el-button type="success" plain @click="$router.push('/training/sandbox')">我的沙箱</el-button>
            <el-button type="warning" plain @click="$router.push('/training/ranking')">团队排行</el-button>
            <el-button plain @click="$router.push('/leave/mine')">我的请假申请</el-button>
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
    { key: 'total_score', title: '能力综合分', color: '#409EFF', format: (v) => (v ?? '—') },
    { key: 'badges', title: '已获徽章', color: '#E6A23C', format: (v) => (v ?? '—') },
    { key: 'completed_scenarios', title: '完成场景', color: '#67C23A', format: (v) => (v ?? '—') },
    { key: 'learning_days_30d', title: '近30天学习天数', color: '#F56C6C', format: (v) => (v ?? '—') }
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
