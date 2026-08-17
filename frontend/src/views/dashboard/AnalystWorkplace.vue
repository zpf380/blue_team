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
    <el-card class="mt16">
      <template #header>聊天工作台</template>
      <p>分析师视图：后续接入频道聊天 + AI 助手 + 设备监控 + 训练进度。</p>
    </el-card>
  </div>
</template>

<script setup>
const cards = [
  { title: '待处理告警', value: '—', color: '#F56C6C' },
  { title: '负责设备', value: '—', color: '#409EFF' },
  { title: '训练进度', value: '—', color: '#67C23A' },
  { title: 'AI 会话', value: '—', color: '#E6A23C' }
]
</script>

<style scoped>
.stat-card { text-align: center; }
.stat-value { font-size: 32px; font-weight: 700; }
.stat-title { color: #999; margin-top: 6px; }
.mt16 { margin-top: 16px; }
</style>
