<template>
  <div class="system-manage">
    <el-card shadow="never">
      <template #header>系统管理</template>
      <el-tabs>
        <el-tab-pane label="用户管理">
          <!-- TODO: P1，后端用户管理接口就绪后实现 -->
          <el-empty description="用户管理功能规划中（P1）" />
        </el-tab-pane>
        <el-tab-pane label="部门管理">
          <el-empty description="部门管理功能规划中（P1）" />
        </el-tab-pane>
        <el-tab-pane label="报销政策">
          <el-empty description="报销政策配置规划中（P2）" />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
// 占位页：仅 admin 可访问（路由守卫 requiresAdmin）
</script>

<style scoped>
.system-manage {
  max-width: 1000px;
}
</style>
