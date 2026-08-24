<template>
  <el-card v-loading="loading">
    <div class="head">
      <h3>🏆 团队积分排行</h3>
      <span class="sub">按累计训练积分排序，前 50 名</span>
    </div>
    <el-empty v-if="rows.length === 0 && !loading" description="暂无排行数据，先去完成几个训练场景吧" />
    <el-table v-else :data="rows" stripe>
      <el-table-column label="排名" width="80" align="center">
        <template #default="{ row }">
          <span class="rank" :class="medal(row.rank)">{{ row.rank }}</span>
        </template>
      </el-table-column>
      <el-table-column label="姓名" min-width="120">
        <template #default="{ row }">{{ row.real_name || row.username }}</template>
      </el-table-column>
      <el-table-column prop="username" label="用户名" min-width="110" />
      <el-table-column prop="department_name" label="部门" min-width="120">
        <template #default="{ row }">{{ row.department_name || '—' }}</template>
      </el-table-column>
      <el-table-column prop="total_points" label="累计积分" width="120" sortable>
        <template #default="{ row }">
          <b class="pts">{{ row.total_points }}</b>
        </template>
      </el-table-column>
      <el-table-column prop="completed_scenarios" label="完成场景" width="100" />
      <el-table-column prop="records" label="积分记录" width="100" />
    </el-table>
  </el-card>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { trainingApi } from '@/api/training'

const rows = ref([])
const loading = ref(false)

function medal(r) {
  if (r === 1) return 'gold'
  if (r === 2) return 'silver'
  if (r === 3) return 'bronze'
  return ''
}

onMounted(async () => {
  loading.value = true
  try {
    rows.value = await trainingApi.ranking()
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 14px; }
.head h3 { margin: 0; }
.sub { font-size: 12px; color: #909399; }
.rank {
  display: inline-block; width: 24px; height: 24px; line-height: 24px; text-align: center;
  border-radius: 50%; font-weight: 700; background: #f2f3f5; color: #606266;
}
.rank.gold { background: #f7d455; color: #7a5a00; }
.rank.silver { background: #d8dde4; color: #4a5568; }
.rank.bronze { background: #e0a078; color: #6b3b1f; }
.pts { color: var(--el-color-primary); }
</style>
