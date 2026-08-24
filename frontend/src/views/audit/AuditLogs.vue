<template>
  <el-card>
    <div class="toolbar">
      <el-input v-model="query.keyword" placeholder="搜索用户名" clearable style="width: 200px" @keyup.enter="load" />
      <el-select v-model="query.action" placeholder="操作类型" clearable style="width: 190px">
        <el-option v-for="a in actionOptions" :key="a.value" :label="a.label" :value="a.value" />
      </el-select>
      <el-date-picker
        v-model="dateRange"
        type="daterange"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        value-format="YYYY-MM-DD"
        style="width: 260px"
      />
      <el-button type="primary" @click="load">查询</el-button>
      <div style="flex: 1"></div>
      <el-button @click="exportCsv">导出日志</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" border stripe size="small">
      <el-table-column type="expand">
        <template #default="{ row }">
          <pre class="detail">{{ row.detail ? JSON.stringify(row.detail, null, 2) : '（无详情）' }}</pre>
        </template>
      </el-table-column>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="username" label="操作人" width="100" />
      <el-table-column prop="role_code" label="角色" width="95" />
      <el-table-column prop="action" label="操作" width="150">
        <template #default="{ row }">{{ actionLabel(row.action) }}</template>
      </el-table-column>
      <el-table-column prop="target_type" label="对象类型" width="100" />
      <el-table-column prop="target_id" label="对象 ID" width="90" />
      <el-table-column prop="ip_address" label="IP" width="130" />
      <el-table-column prop="created_at" label="时间" min-width="170">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="query.page"
        v-model:page-size="query.size"
        :total="total"
        layout="total, prev, pager, next"
        @change="load"
      />
    </div>
  </el-card>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { auditApi } from '@/api/audit'
import { downloadWithAuth } from '@/utils/download'
import { formatDateTime } from '@/utils/format'

const rows = ref([])
const total = ref(0)
const loading = ref(false)
const dateRange = ref([])
const query = reactive({ keyword: '', action: '', page: 1, size: 20 })

const actionOptions = [
  { value: 'auth:login', label: '登录' },
  { value: 'auth:change_password', label: '修改密码' },
  { value: 'user:create', label: '创建用户' },
  { value: 'user:update', label: '更新用户' },
  { value: 'user:delete', label: '删除用户' },
  { value: 'user:import', label: '导入用户' },
  { value: 'user:export', label: '导出用户' },
  { value: 'audit:log:view', label: '查看审计' },
  { value: 'ipam:subnet:create', label: '创建子网' },
  { value: 'ipam:subnet:update', label: '编辑子网' },
  { value: 'ipam:subnet:delete', label: '删除子网' },
  { value: 'ipam:alloc:create', label: '分配地址' },
  { value: 'ipam:alloc:update', label: '编辑分配' },
  { value: 'ipam:alloc:release', label: '释放地址' },
  { value: 'monitor:device:create', label: '创建设备' },
  { value: 'monitor:device:update', label: '编辑设备' },
  { value: 'monitor:device:delete', label: '删除设备' },
  { value: 'monitor:scan:create', label: '发起扫描' },
  { value: 'training:course:publish', label: '发布课程' },
  { value: 'leave:create', label: '提交休假' },
  { value: 'leave:review', label: '审批休假' }
]

function actionLabel(action) {
  const m = actionOptions.find((a) => a.value === action)
  return m ? m.label : '其他'
}

async function load() {
  loading.value = true
  try {
    const params = { ...query }
    if (dateRange.value?.length === 2) {
      params.date_from = dateRange.value[0]
      params.date_to = dateRange.value[1]
    }
    const data = await auditApi.logs(params)
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function exportCsv() {
  downloadWithAuth('/api/v1/audit/logs/export', 'audit_logs.csv')
}

onMounted(load)
</script>

<style scoped>
.toolbar { display: flex; gap: 8px; margin-bottom: 14px; }
.pager { display: flex; justify-content: flex-end; margin-top: 14px; }
.detail { margin: 0; padding: 8px 16px; background: #f5f7fa; font-size: 12px; border-radius: 4px; }
</style>
