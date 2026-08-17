import { defineStore } from 'pinia'
import { ref } from 'vue'

export const usePermissionStore = defineStore('permission', () => {
  const permissions = ref([])

  function setPermissions(perms) {
    permissions.value = Array.isArray(perms) ? perms : []
  }

  function hasPermission(required) {
    if (!required) return true
    const perms = permissions.value
    if (perms.includes('*')) return true
    return perms.some((p) => {
      if (p === required) return true
      if (p.endsWith('*')) return required.startsWith(p.slice(0, -1))
      return false
    })
  }

  return { permissions, setPermissions, hasPermission }
})
