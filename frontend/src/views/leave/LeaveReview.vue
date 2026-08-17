<template>
  <el-card>
    <div class="toolbar">
      <el-select v-model="query.status" placeholder="状态" clearable style="width: 130px" @change="load">
        <el-option v-for="(t, s) in statusText" :key="s" :label="t" :value="s" />
      </el-select>
      <el-select v-model="query.leave_type" placeholder="类型" clearable style="width: 120px" @change="load">
        <el-option label="休假" value="on_leave" />
        <el-option label="外勤" value="business_trip" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" border stripe>
      <el-table-column prop="user_name" label="申请人" width="100" />
      <el-table-column prop="department_name" label="部门" min-width="110">
        <template #default="{ row }">{{ row.department_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.leave_type === 'on_leave' ? 'warning' : 'primary'">
            {{ row.leave_type === 'on_leave' ? '休假' : '外勤' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="开始时间" width="165">
        <template #default="{ row }">{{ fmt(row.start_at) }}</template>
      </el-table-column>
      <el-table-column label="结束时间" width="165">
        <template #default="{ row }">{{ fmt(row.end_at) }}</template>
      </el-table-column>
      <el-table-column prop="reason" label="事由" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">{{ row.reason || '—' }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="statusType[row.status] || 'info'">{{ statusText[row.status] }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <template v-if="row.status === 'pending'">
            <el-button link type="success" @click="openReview(row, 'approve')">批准</el-button>
            <el-button link type="danger" @click="openReview(row, 'reject')">驳回</el-button>
          </template>
          <span v-else style="color: #999">—</span>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="query.page"
        v-model:page-size="query.size"
        :total="total"
        layout="total, prev, pager, next, sizes"
        :page-sizes="[10, 20, 50]"
        @change="load"
      />
    </div>

    <el-dialog v-model="dialogVisible" :title="action === 'approve' ? '批准申请' : '驳回申请'" width="440px">
      <el-form label-width="80px">
        <el-form-item label="备注">
          <el-input v-model="note" type="textarea" :rows="3" maxlength="255" show-word-limit placeholder="审批备注（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button :type="action === 'approve' ? 'success' : 'danger'" :loading="saving" @click="submit">
          {{ action === 'approve' ? '批准' : '驳回' }}
        </el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { leaveApi } from '@/api/leaves'

const rows = ref([])
const total = ref(0)
const loading = ref(false)
// 默认待审批，方便主管打开即处理；可选已批准/已驳回等历史
const query = reactive({ status: 'pending', leave_type: '', page: 1, size: 20 })

const statusText = { pending: '待审批', approved: '已批准', in_progress: '生效中', completed: '已完成', rejected: '已驳回', cancelled: '已取消' }
const statusType = { pending: 'warning', approved: 'success', in_progress: 'primary', completed: 'info', rejected: 'danger', cancelled: 'info' }

const dialogVisible = ref(false)
const saving = ref(false)
const current = ref(null)
const action = ref('approve')
const note = ref('')

function fmt(v) {
  return v ? new Date(v).toLocaleString() : '—'
}

async function load() {
  loading.value = true
  try {
    const data = await leaveApi.list({ ...query })
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function openReview(row, act) {
  current.value = row
  action.value = act
  note.value = ''
  dialogVisible.value = true
}

async function submit() {
  saving.value = true
  try {
    const payload = { note: note.value || null }
    if (action.value === 'approve') {
      await leaveApi.approve(current.value.id, payload)
      ElMessage.success('已批准')
    } else {
      await leaveApi.reject(current.value.id, payload)
      ElMessage.success('已驳回')
    }
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.toolbar { display: flex; gap: 8px; margin-bottom: 14px; }
.pager { display: flex; justify-content: flex-end; margin-top: 14px; }
</style>
