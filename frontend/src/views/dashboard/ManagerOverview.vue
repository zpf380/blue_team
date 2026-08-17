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
      <template #header>安全总览</template>
      <p>主管视图：后续接入高危漏洞、未修复告警、团队训练排名等数据。</p>
    </el-card>
  </div>
</template>

<script setup>
const cards = [
  { title: '高危漏洞', value: '—', color: '#F56C6C' },
  { title: '未修复告警', value: '—', color: '#E6A23C' },
  { title: '团队训练排名', value: '—', color: '#409EFF' },
  { title: '待审批报告', value: '—', color: '#67C23A' }
]
</script>

<style scoped>
.stat-card { text-align: center; }
.stat-value { font-size: 32px; font-weight: 700; }
.stat-title { color: #999; margin-top: 6px; }
.mt16 { margin-top: 16px; }
</style>
