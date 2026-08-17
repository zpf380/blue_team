<template>
  <el-card>
    <div class="toolbar">
      <el-input v-model="query.keyword" placeholder="搜索用户名/姓名/工号" clearable style="width: 220px" @keyup.enter="load" />
      <el-tree-select
        v-model="query.department_id"
        :data="deptTree"
        :props="{ value: 'id', label: 'name', children: 'children' }"
        placeholder="部门"
        check-strictly
        clearable
        style="width: 160px"
      />
      <el-select v-model="query.status" placeholder="状态" clearable style="width: 120px">
        <el-option label="在职" value="active" />
        <el-option label="休假" value="on_leave" />
        <el-option label="外勤" value="business_trip" />
        <el-option label="禁用" value="disabled" />
        <el-option label="离职归档" value="archived" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
      <div style="flex: 1"></div>
      <el-button link @click="downloadTemplate">下载导入模板</el-button>
      <el-upload :show-file-list="false" :before-upload="beforeImport" accept=".csv,.xlsx" style="display: inline-block">
        <el-button v-permission="'user:manage'" type="warning">导入用户</el-button>
      </el-upload>
      <el-button v-permission="'user:manage'" type="success" @click="openDialog()">新增用户</el-button>
      <el-button @click="exportCsv">导出 CSV</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" border stripe>
      <el-table-column prop="username" label="用户名" min-width="110" />
      <el-table-column prop="real_name" label="姓名" min-width="90" />
      <el-table-column prop="employee_no" label="工号" width="90" />
      <el-table-column prop="role_name" label="角色" width="110">
        <template #default="{ row }">
          <el-tag size="small">{{ row.role_name || '—' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="department_name" label="部门" min-width="120" />
      <el-table-column prop="position" label="职位" min-width="100" />
      <el-table-column prop="status" label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="last_login_at" label="最近登录" width="170">
        <template #default="{ row }">{{ row.last_login_at ? new Date(row.last_login_at).toLocaleString() : '—' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button v-permission="'user:manage'" link type="primary" @click="openDialog(row)">编辑</el-button>
          <el-popconfirm title="确认删除该用户？（有审计记录将归档保留）" @confirm="remove(row)">
            <template #reference>
              <el-button v-permission="'user:manage'" link type="danger">删除</el-button>
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

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑用户' : '新增用户'" width="520px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="用户名"><el-input v-model="form.username" :disabled="!!form.id" /></el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password :placeholder="form.id ? '留空则不修改' : '至少 6 位'" />
        </el-form-item>
        <el-form-item label="姓名"><el-input v-model="form.real_name" /></el-form-item>
        <el-form-item label="工号"><el-input v-model="form.employee_no" /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role_id" style="width: 100%">
            <el-option v-for="r in roles" :key="r.id" :label="r.name" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="部门">
          <el-tree-select v-model="form.department_id" :data="deptTree" :props="{ value: 'id', label: 'name', children: 'children' }" check-strictly clearable style="width: 100%" />
        </el-form-item>
        <el-form-item label="职位"><el-input v-model="form.position" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="form.email" /></el-form-item>
        <el-form-item label="手机号"><el-input v-model="form.phone" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { userApi } from '@/api/users'
import { downloadWithAuth } from '@/utils/download'

const rows = ref([])
const total = ref(0)
const loading = ref(false)
const query = reactive({ keyword: '', department_id: null, status: '', page: 1, size: 20 })

const dialogVisible = ref(false)
const saving = ref(false)
const deptTree = ref([])
const roles = ref([])

const emptyForm = () => ({ id: null, username: '', password: '', real_name: '', employee_no: '', role_id: null, department_id: null, position: '', email: '', phone: '' })
const form = reactive(emptyForm())

async function load() {
  loading.value = true
  try {
    const data = await userApi.list({ ...query })
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function openDialog(row) {
  Object.assign(form, row ? { ...row, password: '' } : emptyForm())
  dialogVisible.value = true
}

async function save() {
  if (!form.id && !form.password) {
    ElMessage.warning('请填写密码（至少 6 位）')
    return
  }
  saving.value = true
  try {
    // 空字符串 → null：未填的邮箱/电话等若提交 '' 会被后端 EmailStr 校验拒绝（参数校验失败）
    const payload = Object.fromEntries(Object.entries({ ...form }).map(([k, v]) => [k, v === '' ? null : v]))
    if (form.id) {
      const { username, ...patch } = payload
      await userApi.update(form.id, patch)
      ElMessage.success('已更新')
    } else {
      await userApi.create(payload)
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  const res = await userApi.remove(row.id)
  if (res?.action === 'archived') {
    ElMessage.success('该用户存在审计记录，已归档（离职归档），登录失效')
  } else {
    ElMessage.success('已删除')
  }
  load()
}

function exportCsv() {
  const params = new URLSearchParams({ ...query })
  downloadWithAuth(`/api/v1/users/export?${params}`, 'users.csv')
}

function downloadTemplate() {
  const header = 'username,real_name,email,phone,employee_no,department,role,position,password'
  const row = 'zhangsan,张三,zhangsan@example.com,13800000000,E001,安全运营部,analyst,安全分析师,Bt@123456'
  const blob = new Blob([`﻿${header}\n${row}\n`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'user_import_template.csv'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

async function beforeImport(file) {
  const fd = new FormData()
  fd.append('file', file)
  try {
    const res = await userApi.import(fd)
    ElMessage.success(`导入完成：成功 ${res.created} 条`)
    if (res.failed?.length) {
      const brief = res.failed.slice(0, 3).map((f) => `第${f.row}行 ${f.error}`).join('；')
      ElMessage.warning(`失败 ${res.failed.length} 条：${brief}${res.failed.length > 3 ? '…' : ''}`)
    }
    load()
  } catch { /* 错误提示已由拦截器处理 */ }
  return false
}

function statusText(s) {
  return { active: '在职', on_leave: '休假', business_trip: '外勤', disabled: '禁用', archived: '离职归档' }[s] || s
}
function statusType(s) {
  return { active: 'success', on_leave: 'warning', business_trip: 'primary', disabled: 'danger', archived: 'info' }[s] || 'info'
}

onMounted(async () => {
  load()
  const [tree, roleList] = await Promise.all([userApi.tree(), userApi.roles()])
  deptTree.value = tree
  roles.value = roleList
})
</script>

<style scoped>
.toolbar { display: flex; gap: 8px; margin-bottom: 14px; }
.pager { display: flex; justify-content: flex-end; margin-top: 14px; }
</style>
