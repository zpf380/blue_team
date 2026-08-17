import { defineStore } from 'pinia'
import { ref } from 'vue'
import { usePermissionStore } from '@/stores/permission'
import { useUserStore } from '@/stores/user'

const ALL_MENUS = [
  {
    key: 'dashboard', title: '首页', icon: 'HomeFilled', alwaysShow: true,
    children: [
      { title: '总览仪表盘', path: '/dashboard/admin', permission: 'dashboard:admin', role: 'admin' },
      { title: '安全总览', path: '/dashboard/manager', permission: 'dashboard:security', role: 'manager' },
      { title: '聊天工作台', path: '/dashboard/analyst', permission: 'dashboard:chat', role: 'analyst' },
      { title: '训练中心', path: '/dashboard/trainee', permission: 'dashboard:training', role: 'trainee' },
      { title: '审计总览', path: '/dashboard/auditor', permission: 'dashboard:audit', role: 'auditor' }
    ]
  },
  {
    key: 'chat', title: '聊天系统', icon: 'ChatDotRound', permission: 'chat:view',
    children: [
      { title: '群组列表', path: '/chat/channels', permission: 'chat:channel' },
      { title: '私聊消息', path: '/chat/dm', permission: 'chat:dm' },
      { title: 'AI 助手', path: '/chat/ai', permission: 'chat:ai' }
    ]
  },
  {
    key: 'training', title: '训练中心', icon: 'Reading', permission: 'training:view',
    children: [
      { title: '智能体实训', path: '/training/agents', permission: 'training:agent:view' },
      { title: '课程管理', path: '/training/manage', permission: 'training:course:manage' },
      { title: '我的沙箱', path: '/training/sandbox', permission: 'training:sandbox' },
      { title: '团队排行', path: '/training/ranking', permission: 'training:ranking' },
      { title: '训练统计', path: '/training/stats', permission: 'training:stats' }
    ]
  },
  {
    key: 'monitor', title: '监控中心', icon: 'Monitor', permission: 'monitor:view',
    children: [
      { title: '设备监控', path: '/monitor/devices', permission: 'monitor:device:view' },
      { title: 'IP 地址管理', path: '/monitor/ipam', permission: 'ipam:manage' },
      { title: '告警管理', path: '/monitor/alerts', permission: 'monitor:alert:view' },
      { title: '漏洞扫描', path: '/monitor/scan', permission: 'monitor:scan' }
    ]
  },
  {
    key: 'attendance', title: '考勤管理', icon: 'Calendar', permission: 'leave:apply',
    children: [
      { title: '我的申请', path: '/leave/mine', permission: 'leave:apply' },
      { title: '审批中心', path: '/leave/review', permission: 'leave:approve' }
    ]
  },
  {
    key: 'user', title: '用户管理', icon: 'UserFilled', path: '/users', permission: 'user:manage', roles: ['admin']
  },
  {
    key: 'dept', title: '部门管理', icon: 'OfficeBuilding', path: '/departments', permission: 'department:manage', roles: ['admin', 'manager']
  },
  {
    key: 'audit', title: '审计中心', icon: 'DocumentChecked', permission: 'audit:log', roles: ['admin', 'auditor'],
    children: [
      { title: '操作日志', path: '/audit/logs', permission: 'audit:log' },
      { title: '合规报告', path: '/audit/reports', permission: 'audit:report' }
    ]
  }
]

export const useMenuStore = defineStore('menu', () => {
  const menus = ref([])

  function generateMenus() {
    const userStore = useUserStore()
    const permStore = usePermissionStore()
    const role = userStore.role

    menus.value = ALL_MENUS
      .map((menu) => {
        // 注意：必须浅拷贝菜单对象（children 重新 filter 成新数组），
        // 否则会改写全局 ALL_MENUS 的 children —— 首次在权限为空时调用会把
        // 全部子菜单永久清空，后续任何权限下菜单都只剩无 children 的项。
        const copy = { ...menu }
        if (menu.children) {
          copy.children = menu.children.filter((child) => {
            if (child.role && child.role !== role) return false
            if (child.permission && !permStore.hasPermission(child.permission)) return false
            return true
          })
        }
        return copy
      })
      .filter((menu) => {
        if (menu.roles && !menu.roles.includes(role)) return false
        if (menu.permission && !permStore.hasPermission(menu.permission)) return false
        // 有 children 但过滤后为空 → 隐藏整个菜单
        if (menu.children && menu.children.length === 0) return false
        return true
      })
  }

  return { menus, generateMenus }
})
