import { usePermissionStore } from '@/stores/permission'

// 按钮级权限：无权限则从 DOM 移除元素
// 用法：<el-button v-permission="'user:delete'">删除</el-button>
export const permissionDirective = {
  mounted(el, binding) {
    const store = usePermissionStore()
    if (!store.hasPermission(binding.value)) {
      el.remove()
    }
  }
}
