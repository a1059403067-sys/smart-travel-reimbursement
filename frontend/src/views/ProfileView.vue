<template>
  <div class="profile">
    <el-card shadow="never" class="info-card">
      <template #header>个人信息</template>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="用户 ID">{{ auth.user?.user_id }}</el-descriptions-item>
        <el-descriptions-item label="用户名">{{ auth.user?.username ?? '-' }}</el-descriptions-item>
        <el-descriptions-item label="姓名">{{ auth.user?.real_name }}</el-descriptions-item>
        <el-descriptions-item label="角色">
          <el-tag>{{ roleLabel }}</el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()

const roleLabel = computed(() => {
  const map: Record<string, string> = {
    employee: '员工',
    approver: '审批人',
    finance: '财务',
    admin: '管理员',
  }
  return map[auth.user?.role ?? ''] ?? auth.user?.role ?? '-'
})
</script>

<style scoped>
.profile {
  max-width: 600px;
}
</style>
