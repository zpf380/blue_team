<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">🛡️ 蓝队业务管理系统</div>
      <el-menu :default-active="activeMenu" router class="side-menu">
        <template v-for="menu in menuStore.menus" :key="menu.key">
          <el-sub-menu v-if="menu.children && menu.children.length" :index="menu.key">
            <template #title>
              <el-icon><component :is="menu.icon" /></el-icon>
              <span>{{ menu.title }}</span>
            </template>
            <el-menu-item v-for="child in menu.children" :key="child.path" :index="child.path">
              {{ child.title }}
            </el-menu-item>
          </el-sub-menu>
          <el-menu-item v-else :index="menu.path">
            <el-icon><component :is="menu.icon" /></el-icon>
            <span>{{ menu.title }}</span>
          </el-menu-item>
        </template>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="page-title">{{ route.meta?.title || '' }}</div>
        <el-dropdown @command="onCommand">
          <span class="user-info">
            {{ userStore.userInfo?.real_name || userStore.userInfo?.username }}
            <el-tag size="small" type="info" class="role-tag">{{ userStore.roleName || userStore.role }}</el-tag>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="security">安全设置</el-dropdown-item>
              <el-dropdown-item command="password">修改密码</el-dropdown-item>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>

    <el-dialog v-model="pwdVisible" title="修改密码" width="400px">
      <el-form label-width="80px">
        <el-form-item label="原密码"><el-input v-model="pwdForm.old_password" type="password" show-password /></el-form-item>
        <el-form-item label="新密码"><el-input v-model="pwdForm.new_password" type="password" show-password placeholder="至少 6 位" /></el-form-item>
        <el-form-item label="确认新密码"><el-input v-model="pwdForm.confirm" type="password" show-password /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" :loading="pwdSaving" @click="submitPassword">确认修改</el-button>
      </template>
    </el-dialog>
  </el-container>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { useMenuStore } from '@/stores/menu'
import { usePermissionStore } from '@/stores/permission'
import { useNotificationsStore } from '@/stores/notifications'
import { authApi } from '@/api/auth'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const menuStore = useMenuStore()
const permissionStore = usePermissionStore()
const notifyStore = useNotificationsStore()

// 全局通知连接：仅学员/分析师（training:agent:view）连接，manager 无此权限会收到 4403，
// 若不判断权限将导致无限重连。
onMounted(() => {
  if (permissionStore.hasPermission('training:agent:view')) {
    notifyStore.connect()
  }
})
onBeforeUnmount(() => {
  notifyStore.dispose()
})

const activeMenu = computed(() => route.path)

const pwdVisible = ref(false)
const pwdSaving = ref(false)
const pwdForm = reactive({ old_password: '', new_password: '', confirm: '' })

async function onCommand(cmd) {
  if (cmd === 'password') {
    pwdForm.old_password = ''
    pwdForm.new_password = ''
    pwdForm.confirm = ''
    pwdVisible.value = true
  } else if (cmd === 'security') {
    router.push('/profile/security')
  } else if (cmd === 'logout') {
    await userStore.logout()
    router.push('/login')
  }
}

async function submitPassword() {
  if (!pwdForm.old_password || !pwdForm.new_password) {
    ElMessage.warning('请填写完整')
    return
  }
  if (pwdForm.new_password.length < 6) {
    ElMessage.warning('新密码至少 6 位')
    return
  }
  if (pwdForm.new_password !== pwdForm.confirm) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  pwdSaving.value = true
  try {
    await authApi.changePassword({ old_password: pwdForm.old_password, new_password: pwdForm.new_password })
    ElMessage.success('密码已修改，请重新登录')
    pwdVisible.value = false
    userStore.logout()
    router.push('/login')
  } catch { /* 错误提示已由拦截器处理 */ } finally {
    pwdSaving.value = false
  }
}
</script>

<style scoped>
.layout { height: 100vh; }
.aside { background: #001529; }
.logo { color: #fff; font-weight: 600; padding: 18px 16px; font-size: 15px; }
.side-menu { border-right: none; }
:deep(.side-menu) { background: #001529; --el-menu-text-color: #c0c4cc; --el-menu-hover-bg-color: #123; }
:deep(.side-menu .el-menu-item.is-active) { background: #1f3b4d; color: #fff; }
.header { display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #eee; background: #fff; }
.page-title { font-size: 16px; font-weight: 600; }
.user-info { cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
.role-tag { margin-left: 2px; }
.main { background: #f5f7fa; }
</style>
