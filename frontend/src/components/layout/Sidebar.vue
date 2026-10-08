<template>
  <div class="sidebar">
    <div class="logo">
      <span>✈️ 差旅报销</span>
    </div>
    <nav class="nav-list">
      <RouterLink to="/dashboard" class="nav-item" :class="{ 'nav-item--active': isActive('/dashboard') }">
        <el-icon><House /></el-icon>
        <span>首页</span>
      </RouterLink>

      <RouterLink to="/chat" class="nav-item" :class="{ 'nav-item--active': isActive('/chat') }">
        <el-icon><ChatDotRound /></el-icon>
        <span>差旅助手</span>
      </RouterLink>

      <RouterLink to="/reimbursements" class="nav-item" :class="{ 'nav-item--active': isActive('/reimbursements') }">
        <el-icon><Tickets /></el-icon>
        <span>报销单管理</span>
      </RouterLink>

      <RouterLink to="/invoice" class="nav-item" :class="{ 'nav-item--active': isActive('/invoice') }">
        <el-icon><UploadFilled /></el-icon>
        <span>发票解析</span>
      </RouterLink>

      <!-- 审批管理（仅 approver/admin 可见，契约角色枚举） -->
      <template v-if="auth.canApprove">
        <RouterLink to="/approvals" class="nav-item" :class="{ 'nav-item--active': isActive('/approvals') }">
          <el-icon><Stamp /></el-icon>
          <span>审批管理</span>
        </RouterLink>
      </template>

      <RouterLink to="/analytics" class="nav-item" :class="{ 'nav-item--active': isActive('/analytics') }">
        <el-icon><DataAnalysis /></el-icon>
        <span>数据分析</span>
      </RouterLink>

      <!-- 系统管理（仅 admin 可见） -->
      <template v-if="auth.isAdmin">
        <RouterLink to="/system" class="nav-item" :class="{ 'nav-item--active': isActive('/system') }">
          <el-icon><Setting /></el-icon>
          <span>系统管理</span>
        </RouterLink>
      </template>

      <div class="nav-spacer" />

      <RouterLink to="/profile" class="nav-item" :class="{ 'nav-item--active': isActive('/profile') }">
        <el-icon><User /></el-icon>
        <span>个人中心</span>
      </RouterLink>
    </nav>
  </div>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
import {
  House, ChatDotRound, Tickets, UploadFilled,
  Stamp, DataAnalysis, Setting, User,
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()

// 仅用于子路由高亮（纯视觉反馈，不参与导航逻辑）
function isActive(prefix: string) {
  return route.path === prefix || route.path.startsWith(prefix + '/')
}
</script>

<style scoped>
.sidebar {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.logo {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  border-bottom: 1px solid #ffffff1a;
  flex-shrink: 0;
}

.nav-list {
  display: flex;
  flex-direction: column;
  padding: 4px 0;
  flex: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 13px 20px;
  color: #ffffffa6;
  text-decoration: none;
  font-size: 14px;
  cursor: pointer;
  transition: background-color 0.2s, color 0.2s;
  user-select: none;
}

.nav-item:hover {
  background-color: #ffffff14;
  color: #fff;
}

.nav-item--active {
  background-color: #1677ff;
  color: #fff;
}

.nav-item .el-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.nav-spacer {
  flex: 1;
}
</style>
