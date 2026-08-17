import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { usePermissionStore } from '@/stores/permission'
import { useMenuStore } from '@/stores/menu'

const routes = [
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'Home',
        redirect: () => {
          const map = {
            admin: '/dashboard/admin',
            manager: '/dashboard/manager',
            analyst: '/dashboard/analyst',
            trainee: '/dashboard/trainee',
            auditor: '/dashboard/auditor'
          }
          const role = useUserStore().role
          // 未登录或角色未知 → 去登录页（否则会落到 /403，且 403 点“返回首页”又回到 /403 造成“无反应”）
          if (role && map[role]) return map[role]
          return '/login'
        }
      },
      { path: '/dashboard/admin', component: () => import('@/views/dashboard/AdminOverview.vue'), meta: { permission: 'dashboard:admin', title: '总览仪表盘' } },
      { path: '/dashboard/manager', component: () => import('@/views/dashboard/ManagerOverview.vue'), meta: { permission: 'dashboard:security', title: '安全总览' } },
      { path: '/dashboard/analyst', component: () => import('@/views/dashboard/AnalystWorkplace.vue'), meta: { permission: 'dashboard:chat', title: '聊天工作台' } },
      { path: '/dashboard/trainee', component: () => import('@/views/dashboard/TraineeCenter.vue'), meta: { permission: 'dashboard:training', title: '训练中心' } },
      { path: '/dashboard/auditor', component: () => import('@/views/dashboard/AuditOverview.vue'), meta: { permission: 'dashboard:audit', title: '审计总览' } },

      // 聊天系统（P2/P3）
      { path: '/chat/channels', component: () => import('@/views/chat/Channels.vue'), meta: { permission: 'chat:channel', title: '群组列表' } },
      { path: '/chat/channels/:id', component: () => import('@/views/chat/ChannelRoom.vue'), meta: { permission: 'chat:view', title: '频道消息' } },
      { path: '/chat/dm', component: () => import('@/views/chat/DM.vue'), meta: { permission: 'chat:dm', title: '私聊消息' } },
      { path: '/chat/ai', component: () => import('@/views/chat/AIAssistant.vue'), meta: { permission: 'chat:ai', title: 'AI 助手' } },

      // 训练中心（P4）
      { path: '/training/agents', component: () => import('@/views/training/Agents.vue'), meta: { permission: 'training:agent:view', title: '智能体实训' } },
      { path: '/training/manage', component: () => import('@/views/training/CourseManage.vue'), meta: { permission: 'training:course:manage', title: '课程管理' } },
      { path: '/training/sandbox', component: () => import('@/views/training/Sandbox.vue'), meta: { permission: 'training:sandbox', title: '我的沙箱' } },
      { path: '/training/sandbox/:sessionId', component: () => import('@/views/training/Sandbox.vue'), meta: { permission: 'training:sandbox', title: '沙箱实训' } },
      { path: '/training/ranking', component: () => import('@/views/training/Ranking.vue'), meta: { permission: 'training:ranking', title: '团队排行' } },
      { path: '/training/stats', component: () => import('@/views/training/TrainingStats.vue'), meta: { permission: 'training:stats', title: '训练统计' } },

      // 监控中心（P5）
      { path: '/monitor/devices', component: () => import('@/views/monitor/Devices.vue'), meta: { permission: 'monitor:device:view', title: '设备监控' } },
      { path: '/monitor/ipam', component: () => import('@/views/monitor/IPAM.vue'), meta: { permission: 'ipam:manage', title: 'IP 地址管理' } },
      { path: '/monitor/alerts', component: () => import('@/views/monitor/Alerts.vue'), meta: { permission: 'monitor:alert:view', title: '告警管理' } },
      { path: '/monitor/scan', component: () => import('@/views/monitor/Scan.vue'), meta: { permission: 'monitor:scan', title: '漏洞扫描' } },

      // 考勤管理（休假/外勤）
      { path: '/leave/mine', component: () => import('@/views/leave/MyLeaves.vue'), meta: { permission: 'leave:apply', title: '我的申请' } },
      { path: '/leave/review', component: () => import('@/views/leave/LeaveReview.vue'), meta: { permission: 'leave:approve', title: '审批中心' } },

      // 用户/部门管理（admin + manager）
      { path: '/users', component: () => import('@/views/user/UserManage.vue'), meta: { permission: 'user:manage', roles: ['admin'], title: '用户管理' } },
      { path: '/departments', component: () => import('@/views/user/DepartmentManage.vue'), meta: { permission: 'department:manage', roles: ['admin', 'manager'], title: '部门管理' } },

      // 个人安全设置（MFA + 会话管理，登录即可访问）
      { path: '/profile/security', component: () => import('@/views/user/ProfileSecurity.vue'), meta: { requiresAuth: true, title: '安全设置' } },

      // 审计中心（管理员 + 审计员）
      { path: '/audit/logs', component: () => import('@/views/audit/AuditLogs.vue'), meta: { permission: 'audit:log', roles: ['admin', 'auditor'], title: '操作日志' } },
      { path: '/audit/reports', component: () => import('@/views/audit/AuditReports.vue'), meta: { permission: 'audit:report', roles: ['admin', 'auditor'], title: '合规报告' } }
    ]
  },
  { path: '/login', component: () => import('@/views/login/Login.vue'), meta: { public: true } },
  { path: '/403', component: () => import('@/views/error/Forbidden.vue'), meta: { public: true } },
  // 未知路径 → 404「页面不存在」（而不是误报为 403 无权限）
  { path: '/:pathMatch(.*)*', component: () => import('@/views/error/NotFound.vue'), meta: { public: true } }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach(async (to) => {
  if (to.meta?.public) return true

  const userStore = useUserStore()
  const permissionStore = usePermissionStore()
  const menuStore = useMenuStore()

  // 会话令牌在 HttpOnly Cookie 中：无本地用户信息时尝试拉取（Cookie 自动携带），失败即未登录
  if (!userStore.userInfo) {
    try {
      await userStore.fetchMe()
    } catch {
      return { path: '/login' }
    }
  }

  // 每次导航都从 userStore 同步权限到 permissionStore 并生成菜单：
  // 登录时 setUser 只填了 userStore.permissions，此前只在 fetchMe 分支同步，
  // 导致登录后 permissionStore 为空 → hasPermission 恒 false → 被守卫丢到 /403。
  permissionStore.setPermissions(userStore.permissions)
  menuStore.generateMenus()

  if (to.meta?.roles && !to.meta.roles.includes(userStore.role)) {
    return { path: '/403' }
  }
  if (to.meta?.permission && !permissionStore.hasPermission(to.meta.permission)) {
    return { path: '/403' }
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta?.title ? `${to.meta.title} · 蓝队业务管理系统` : '蓝队业务管理系统'
})

export default router
