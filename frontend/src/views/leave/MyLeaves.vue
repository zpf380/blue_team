<template>
  <el-card>
    <div class="toolbar">
      <el-select v-model="query.leave_type" placeholder="类型" clearable style="width: 120px" @change="load">
        <el-option label="休假" value="on_leave" />
        <el-option label="外勤" value="business_trip" />
      </el-select>
      <el-select v-model="query.status" placeholder="状态" clearable style="width: 130px" @change="load">
        <el-option v-for="(t, s) in statusText" :key="s" :label="t" :value="s" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
      <div style="flex: 1"></div>
      <el-button type="success" @click="openDialog">发起申请</el-button>
    </div>

    <el-empty v-if="!rows.length && !loading" description="暂无休假申请" />
    <el-table v-else :data="rows" v-loading="loading" border stripe>
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
      <el-table-column label="审批人" width="110">
        <template #default="{ row }">{{ row.approver_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-popconfirm v-if="row.status === 'pending'" title="确认取消该申请？" @confirm="cancel(row)">
            <template #reference>
              <el-button link type="danger">取消</el-button>
            </template>
          </el-popconfirm>
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

    <el-dialog v-model="dialogVisible" title="发起休假/外勤申请" width="480px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="类型">
          <el-radio-group v-model="form.leave_type">
            <el-radio-button value="on_leave">休假</el-radio-button>
            <el-radio-button value="business_trip">外勤</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="开始时间">
          <el-date-picker
            v-model="form.start_at"
            type="datetime"
            placeholder="开始时间"
            style="width: 100%"
            :disabled-date="(d) => d.getTime() < Date.now() - 86400000"
          />
        </el-form-item>
        <el-form-item label="结束时间">
          <el-date-picker v-model="form.end_at" type="datetime" placeholder="结束时间" style="width: 100%" :disabled-date="endDisabled" />
        </el-form-item>
        <el-form-item label="事由">
          <el-input v-model="form.reason" type="textarea" :rows="3" maxlength="500" show-word-limit placeholder="请填写休假/外勤事由" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">提交</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { leaveApi } from '@/api/leaves'
import { formatDateTime } from '@/utils/format'

const rows = ref([])
const total = ref(0)
const loading = ref(false)
const query = reactive({ leave_type: '', status: '', page: 1, size: 20 })

const statusText = { pending: '待审批', approved: '已批准', in_progress: '生效中', completed: '已完成', rejected: '已驳回', cancelled: '已取消' }
const statusType = { pending: 'warning', approved: 'success', in_progress: 'primary', completed: 'info', rejected: 'danger', cancelled: 'info' }

const dialogVisible = ref(false)
const saving = ref(false)
const form = reactive({ leave_type: 'on_leave', start_at: null, end_at: null, reason: '' })

function fmt(v) {
  return formatDateTime(v)
}

// 结束时间不可早于开始时间（未选开始则以当前时间为界）
function endDisabled(d) {
  const base = form.start_at || new Date()
  return d.getTime() < base.getTime()
}

async function load() {
  loading.value = true
  try {
    const data = await leaveApi.mine({ ...query })
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function openDialog() {
  Object.assign(form, { leave_type: 'on_leave', start_at: null, end_at: null, reason: '' })
  dialogVisible.value = true
}

async function save() {
  if (!form.start_at || !form.end_at) {
    ElMessage.warning('请选择开始与结束时间')
    return
  }
  if (form.end_at <= form.start_at) {
    ElMessage.warning('结束时间必须晚于开始时间')
    return
  }
  if (form.start_at.getTime() < Date.now()) {
    ElMessage.warning('开始时间不能早于当前时间')
    return
  }
  saving.value = true
  try {
    await leaveApi.create({
      leave_type: form.leave_type,
      start_at: form.start_at.toISOString(),
      end_at: form.end_at.toISOString(),
      reason: form.reason || null
    })
    ElMessage.success('申请已提交，等待审批')
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function cancel(row) {
  await leaveApi.cancel(row.id)
  ElMessage.success('已取消')
  load()
}

onMounted(load)
</script>

<style scoped>
.toolbar { display: flex; gap: 8px; margin-bottom: 14px; }
.pager { display: flex; justify-content: flex-end; margin-top: 14px; }
</style>
