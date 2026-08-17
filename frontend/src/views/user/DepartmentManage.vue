<template>
  <el-card>
    <div class="toolbar">
      <el-button type="primary" @click="load">刷新</el-button>
      <div style="flex: 1"></div>
      <el-button v-permission="'department:manage'" type="success" @click="openDialog()">新增部门</el-button>
    </div>

    <el-table :data="deptTree" v-loading="loading" row-key="id" border stripe default-expand-all>
      <el-table-column prop="name" label="部门名称" min-width="180" />
      <el-table-column label="上级部门" min-width="150">
        <template #default="{ row }">{{ parentName(row.parent_id) }}</template>
      </el-table-column>
      <el-table-column label="主管" min-width="120">
        <template #default="{ row }">{{ managerName(row.manager_id) }}</template>
      </el-table-column>
      <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button v-permission="'department:manage'" link type="primary" @click="openDialog(undefined, row.id)">新增子部门</el-button>
          <el-button v-permission="'department:manage'" link type="primary" @click="openDialog(row)">编辑</el-button>
          <el-popconfirm
            :title="`确认删除部门「${row.name}」？（有子部门/用户/设备/子网引用将被拒绝）`"
            width="320"
            @confirm="remove(row)"
          >
            <template #reference>
              <el-button v-permission="'department:manage'" link type="danger">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑部门' : '新增部门'" width="500px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="部门名称" required>
          <el-input v-model="form.name" maxlength="100" placeholder="必填" />
        </el-form-item>
        <el-form-item label="上级部门">
          <el-tree-select
            v-model="form.parent_id"
            :data="parentOptions"
            :props="{ value: 'id', label: 'name', children: 'children' }"
            check-strictly
            clearable
            style="width: 100%"
            placeholder="不选则为根部门"
          />
        </el-form-item>
        <el-form-item label="主管">
          <el-select v-model="form.manager_id" filterable clearable placeholder="选择主管用户" style="width: 100%">
            <el-option v-for="u in users" :key="u.id" :label="`${u.real_name || u.username}${u.department_name ? '（' + u.department_name + '）' : ''}`" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="部门职责说明" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { departmentApi } from '@/api/departments'
import { userApi } from '@/api/users'

const loading = ref(false)
const deptTree = ref([])
const users = ref([])
const dialogVisible = ref(false)
const saving = ref(false)
const editId = ref(null)

const emptyForm = () => ({ name: '', parent_id: null, manager_id: null, description: '' })
const form = reactive(emptyForm())

async function load() {
  loading.value = true
  try {
    deptTree.value = await departmentApi.tree()
  } finally {
    loading.value = false
  }
}

function flatten(nodes, acc = []) {
  for (const n of nodes || []) {
    acc.push(n)
    flatten(n.children, acc)
  }
  return acc
}

const flatDepts = computed(() => flatten(deptTree.value))

function parentName(id) {
  if (!id) return '—'
  const d = flatDepts.value.find((x) => x.id === id)
  return d ? d.name : '—'
}

function managerName(id) {
  if (!id) return '—'
  const u = users.value.find((x) => x.id === id)
  return u ? u.real_name || u.username : '—'
}

// 编辑时上级下拉排除自身及子孙（避免循环），新增子部门时自动填入父级
function openDialog(row, parentId) {
  Object.assign(form, emptyForm(), row ? { ...row } : {})
  editId.value = row?.id ?? null
  if (parentId) form.parent_id = parentId
  dialogVisible.value = true
}

const parentOptions = computed(() => {
  if (!editId.value) return deptTree.value
  const blocked = new Set()
  const collect = (node) => {
    blocked.add(node.id)
    for (const c of node.children || []) collect(c)
  }
  const self = flatDepts.value.find((x) => x.id === editId.value)
  if (self) collect(self)
  const filter = (nodes) =>
    (nodes || [])
      .filter((n) => !blocked.has(n.id))
      .map((n) => ({ ...n, children: filter(n.children) }))
  return filter(deptTree.value)
})

async function save() {
  if (!form.name?.trim()) {
    ElMessage.warning('请填写部门名称')
    return
  }
  saving.value = true
  try {
    const payload = Object.fromEntries(
      Object.entries({ ...form }).map(([k, v]) => [k, v === '' ? null : v])
    )
    if (editId.value) {
      await departmentApi.update(editId.value, payload)
      ElMessage.success('已更新')
    } else {
      await departmentApi.create(payload)
      ElMessage.success('已创建')
    }
    dialogVisible.value = false
    load()
  } catch { /* 错误提示已由拦截器处理 */ } finally {
    saving.value = false
  }
}

async function remove(row) {
  try {
    await departmentApi.remove(row.id)
    ElMessage.success('已删除')
    load()
  } catch { /* 409 冲突提示已由拦截器处理 */ }
}

onMounted(async () => {
  load()
  users.value = (await userApi.list({ size: 500 })).items
})
</script>

<style scoped>
.toolbar { display: flex; gap: 8px; margin-bottom: 14px; }
</style>
