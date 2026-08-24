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
          <template #header>今日工作台</template>
          <p class="muted">跟踪本部门告警与设备动态，在告警中心确认、处置安全事件；设备台账管理归属资产。</p>
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card>
          <template #header>快捷操作</template>
          <div class="quick-actions">
            <el-button type="danger" plain @click="$router.push('/monitor/alerts')">告警中心</el-button>
            <el-button type="primary" plain @click="$router.push('/monitor/devices')">设备监控</el-button>
            <el-button type="success" plain @click="$router.push('/chat/ai')">AI 助手</el-button>
            <el-button plain @click="$router.push('/chat/channels')">频道聊天</el-button>
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
    { key: 'open_alerts', title: '待处理告警', color: '#F56C6C', format: (v) => (v ?? '—') },
    { key: 'dept_alerts', title: '本部门未解决告警', color: '#E6A23C', format: (v) => (v ?? '—') },
    { key: 'my_devices', title: '负责设备', color: '#409EFF', format: (v) => (v ?? '—') },
    { key: 'ai_conversations', title: 'AI 会话', color: '#67C23A', format: (v) => (v ?? '—') }
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
