<template>
  <el-card>
    <el-result icon="info" title="模块开发中" :sub-title="`${route.meta.module || ''} 将在对应阶段实现（详见执行计划）`">
      <template #extra>
        <el-button type="primary" @click="$router.push('/')">返回首页</el-button>
      </template>
    </el-result>
  </el-card>
</template>

<script setup>
import { useRoute } from 'vue-router'
const route = useRoute()
</script>
