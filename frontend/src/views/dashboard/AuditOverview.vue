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
      <template #header>审计总览</template>
      <p>审计员视图：只读模式。后续接入实时操作流、异常行为、合规评分。</p>
      <el-button type="primary" @click="$router.push('/audit/logs')">查看操作日志</el-button>
    </el-card>
  </div>
</template>

<script setup>
const cards = [
  { title: '今日操作数', value: '—', color: '#409EFF' },
  { title: '异常行为', value: '—', color: '#F56C6C' },
  { title: '合规评分', value: '—', color: '#67C23A' },
  { title: '待核查项', value: '—', color: '#E6A23C' }
]
</script>

<style scoped>
.stat-card { text-align: center; }
.stat-value { font-size: 32px; font-weight: 700; }
.stat-title { color: #999; margin-top: 6px; }
.mt16 { margin-top: 16px; }
</style>
