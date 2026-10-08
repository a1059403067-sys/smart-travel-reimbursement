<template>
  <div class="login-page">
    <el-card class="login-card">
      <div class="login-header">
        <div class="login-logo">✈️</div>
        <h2>智能差旅报销系统</h2>
        <p>AI 驱动的差旅管理与费用报销平台</p>
      </div>
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        @submit.prevent="handleLogin"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="form.username"
            placeholder="请输入用户名"
            size="large"
            :prefix-icon="User"
          />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            size="large"
            :prefix-icon="Lock"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          :loading="loading"
          style="width: 100%; margin-top: 8px"
          @click="handleLogin"
        >
          登录
        </el-button>
        <div class="login-footer">
          <span class="muted">还没有账号？</span>
          <el-button link type="primary" @click="router.push('/register')">注册账号</el-button>
        </div>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import type { AxiosError } from 'axios'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

// 注册成功后跳转回来时预填登录账号（query 携带）
onMounted(() => {
  const u = route.query.username
  if (typeof u === 'string' && u) form.username = u
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin() {
  // R-36：validate 失败时静默返回（表单项已展示错误提示），避免 unhandled rejection
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  loading.value = true
  try {
    const { data } = await authApi.login({
      username: form.username,
      password: form.password,
    })
    auth.login(data.access_token, {
      user_id: data.user_id,
      username: form.username,
      real_name: data.real_name,
      role: data.role,
    })
    router.push('/dashboard')
  } catch (err) {
    // 契约（REQ-2）：401=用户名或密码错误；403=账号已被禁用。
    // 401 拦截器不弹消息，这里展示 detail；403 拦截器已弹过契约文案；
    // 无 response = 网络错误/跨域拦截，单独提示
    const e = err as AxiosError<{ detail?: string }>
    if (e.response?.status === 401) {
      ElMessage.error(e.response.data?.detail ?? '用户名或密码错误')
    } else if (!e.response) {
      ElMessage.error('无法连接服务器，请确认后端已启动（http://localhost:8006）')
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 60%, #38bdf8 100%);
}
.login-card {
  width: 400px;
  border-radius: 12px;
}
.login-header {
  text-align: center;
  margin-bottom: 24px;
}
.login-logo {
  font-size: 48px;
  margin-bottom: 8px;
}
.login-header h2 {
  margin: 0 0 4px;
  font-size: 24px;
  color: #1a1a1a;
}
.login-header p {
  margin: 0;
  color: #8c8c8c;
  font-size: 14px;
}
.login-footer {
  margin-top: 12px;
  text-align: center;
  font-size: 13px;
}
.login-footer .muted {
  color: #8c8c8c;
}
</style>
