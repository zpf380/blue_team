import { defineStore } from 'pinia'
import { authApi } from '@/api/auth'

// 会话令牌由后端写入 HttpOnly Cookie，前端状态仅缓存用户信息
export const useUserStore = defineStore('user', {
  state: () => ({
    userInfo: null,
    role: '',
    roleName: '',
    permissions: []
  }),
  getters: {
    isLoggedIn: (s) => !!s.userInfo
  },
  actions: {
    // 返回登录响应：可能为 MFA 两段式（mfa_required），由登录页继续处理
    async login(username, password, captcha = {}) {
      const data = await authApi.login({ username, password, ...captcha })
      if (!data.mfa_required) this.setUser(data.user)
      return data
    },
    setUser(user) {
      this.userInfo = user
      this.role = user?.role || ''
      this.roleName = user?.role_name || ''
      this.permissions = user?.permissions || []
    },
    async fetchMe() {
      const user = await authApi.me()
      this.setUser(user)
      return user
    },
    async logout() {
      try {
        await authApi.logout()
      } catch { /* 忽略 */ }
      this.setUser(null)
    }
  }
})
