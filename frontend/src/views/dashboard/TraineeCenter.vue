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
      <template #header>训练中心</template>
      <p>学员视图：后续接入能力雷达、推荐路径、徽章成就、沙箱实训入口。</p>
    </el-card>
  </div>
</template>

<script setup>
const cards = [
  { title: '能力综合分', value: '—', color: '#409EFF' },
  { title: '已获徽章', value: '—', color: '#E6A23C' },
  { title: '完成场景', value: '—', color: '#67C23A' },
  { title: '连续学习', value: '—', color: '#F56C6C' }
]
</script>

<style scoped>
.stat-card { text-align: center; }
.stat-value { font-size: 32px; font-weight: 700; }
.stat-title { color: #999; margin-top: 6px; }
.mt16 { margin-top: 16px; }
</style>
