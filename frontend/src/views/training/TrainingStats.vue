<template>
  <div v-loading="loading">
    <el-card class="stat-card">
      <h3>📊 我的训练统计</h3>
      <div class="stat-grid">
        <div class="stat-item">
          <div class="stat-num primary">{{ stats.personal.total_points }}</div>
          <div class="stat-label">累计积分</div>
        </div>
        <div class="stat-item">
          <div class="stat-num success">{{ stats.personal.completed_scenarios }}</div>
          <div class="stat-label">完成场景</div>
        </div>
        <div class="stat-item">
          <div class="stat-num warning">{{ stats.personal.in_progress }}</div>
          <div class="stat-label">进行中</div>
        </div>
        <div class="stat-item">
          <div class="stat-num danger">{{ stats.personal.failed }}</div>
          <div class="stat-label">未达标</div>
        </div>
        <div class="stat-item">
          <div class="stat-num">{{ stats.personal.badges_count }}</div>
          <div class="stat-label">已获徽章</div>
        </div>
        <div class="stat-item">
          <div class="stat-num">{{ stats.personal.avg_score }}</div>
          <div class="stat-label">平均分</div>
        </div>
      </div>
    </el-card>

    <el-card class="stat-card">
      <h3>🏢 部门训练积分</h3>
      <el-empty v-if="stats.departments.length === 0" description="暂无部门积分数据" />
      <div v-for="d in stats.departments" :key="d.name" class="dept-row">
        <span class="dept-name">{{ d.name }}</span>
        <el-progress
          :percentage="deptPct(d.points)"
          :stroke-width="12"
          color="#409eff"
        />
        <span class="dept-pts">{{ d.points }} 分</span>
        <span class="dept-members">{{ d.members }} 人</span>
      </div>
    </el-card>

    <el-card class="stat-card">
      <h3>🎖️ 徽章墙</h3>
      <div class="badge-grid">
        <div
          v-for="b in badges"
          :key="b.id"
          class="badge-item"
          :class="{ locked: !mine.includes(b.id) }"
        >
          <div class="badge-icon">{{ earned(b.id) ? '🏅' : '🔒' }}</div>
          <div class="badge-name">{{ b.name }}</div>
          <div class="badge-desc">{{ b.description }}</div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { trainingApi } from '@/api/training'

const loading = ref(false)
const stats = ref({ personal: { total_points: 0, completed_scenarios: 0, in_progress: 0, failed: 0, badges_count: 0, avg_score: 0 }, departments: [] })
const badges = ref([])
const mine = ref([])

function deptPct(points) {
  const max = Math.max(1, ...stats.value.departments.map((d) => d.points))
  return Math.round((points / max) * 100)
}
function earned(id) {
  return mine.value.includes(id)
}

onMounted(async () => {
  loading.value = true
  try {
    const [s, b] = await Promise.all([trainingApi.stats(), trainingApi.badges()])
    stats.value = s
    badges.value = b.badges
    mine.value = b.mine
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.stat-card { margin-bottom: 14px; }
.stat-card h3 { margin: 0 0 14px; }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 14px; }
.stat-item { text-align: center; padding: 14px; border-radius: 8px; background: #f8fafc; }
.stat-num { font-size: 26px; font-weight: 700; }
.stat-num.primary { color: var(--el-color-primary); }
.stat-num.success { color: var(--el-color-success); }
.stat-num.warning { color: var(--el-color-warning); }
.stat-num.danger { color: var(--el-color-danger); }
.stat-label { font-size: 13px; color: #909399; margin-top: 4px; }

.dept-row { display: flex; align-items: center; gap: 12px; padding: 8px 0; }
.dept-name { width: 110px; font-weight: 600; }
.dept-row .el-progress { flex: 1; }
.dept-pts { width: 70px; text-align: right; font-weight: 600; color: var(--el-color-primary); }
.dept-members { width: 60px; font-size: 12px; color: #909399; }

.badge-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }
.badge-item { text-align: center; padding: 14px; border-radius: 8px; background: #fffbea; border: 1px solid #f5e6b8; }
.badge-item.locked { background: #f5f7fa; border-color: #ebeef5; opacity: 0.6; }
.badge-icon { font-size: 30px; }
.badge-name { font-weight: 600; margin: 6px 0 2px; }
.badge-desc { font-size: 12px; color: #909399; line-height: 1.5; }
</style>
