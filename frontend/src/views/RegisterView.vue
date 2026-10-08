<template>
  <div class="register-page">
    <el-card class="register-card">
      <div class="register-header">
        <div class="register-logo">✈️</div>
        <h2>注册账号</h2>
        <p>同一部门内姓名唯一，注册后即可登录</p>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        @submit.prevent="handleRegister"
      >
        <el-form-item label="姓名" prop="real_name">
          <el-input
            v-model="form.real_name"
            placeholder="请输入真实姓名"
            size="large"
            :prefix-icon="User"
          />
        </el-form-item>
        <el-form-item label="部门" prop="department">
          <el-select
            v-model="form.department"
            placeholder="请选择部门"
            size="large"
            style="width: 100%"
          >
            <el-option v-for="d in departments" :key="d" :label="d" :value="d" />
          </el-select>
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="至少 6 位"
            size="large"
            :prefix-icon="Lock"
            show-password
          />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirm_password">
          <el-input
            v-model="form.confirm_password"
            type="password"
            placeholder="再次输入密码"
            size="large"
            :prefix-icon="Lock"
            show-password
            @keyup.enter="handleRegister"
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          :loading="loading"
          style="width: 100%; margin-top: 8px"
          @click="handleRegister"
        >
          注册
        </el-button>
        <el-button
          text
          style="width: 100%; margin-top: 8px"
          @click="router.push('/login')"
        >
          已有账号？返回登录
        </el-button>
      </el-form>
    </el-card>

    <!-- 注册成功弹窗：展示自动生成的登录账号 -->
    <el-dialog v-model="successVisible" title="注册成功" width="440px" :close-on-click-modal="false">
      <el-result icon="success" title="账号创建成功">
        <template #sub-title>
          <div class="success-info">
            <p>您的登录账号是：<b>{{ registered?.username }}</b></p>
            <p class="muted">请使用此账号和您的密码登录系统</p>
          </div>
        </template>
      </el-result>
      <template #footer>
        <el-button type="primary" @click="goLogin">去登录</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { authApi } from '@/api/auth'
import type { RegisterResponse } from '@/types'

const router = useRouter()

// REQ-10 就绪后以后端返回为准；未就绪时使用契约列出的 5 个部门兜底
const FALLBACK_DEPARTMENTS = ['幕墙设计部', 'BIM部', '内装部', '城市更新部', '综合业务部']

const formRef = ref<FormInstance>()
const loading = ref(false)
const successVisible = ref(false)
const registered = ref<RegisterResponse | null>(null)
const departments = ref<string[]>([...FALLBACK_DEPARTMENTS])

const form = reactive({
  real_name: '',
  department: '',
  password: '',
  confirm_password: '',
})

const rules: FormRules = {
  real_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  department: [{ required: true, message: '请选择部门', trigger: 'change' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== form.password) callback(new Error('两次输入的密码不一致'))
        else callback()
      },
      trigger: 'blur',
    },
  ],
}

async function handleRegister() {
  await formRef.value?.validate()
  loading.value = true
  try {
    const { data } = await authApi.register({
      real_name: form.real_name.trim(),
      department: form.department,
      password: form.password,
    })
    registered.value = data
    successVisible.value = true
  } catch (e: unknown) {
    // 409 组合已注册/422 参数错误等由拦截器展示 detail（契约文案），此处不重复弹
    void e
  } finally {
    loading.value = false
  }
}

function goLogin() {
  successVisible.value = false
  router.push({ path: '/login', query: { username: registered.value?.username } })
}

onMounted(async () => {
  // REQ-10 就绪后刷新部门列表；失败时静默使用契约兜底列表
  try {
    const { data } = await authApi.departments()
    if (data.items?.length) departments.value = data.items
  } catch { /* 兜底列表已内置 */ }
})
</script>

<style scoped>
.register-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 60%, #38bdf8 100%);
}
.register-card {
  width: 420px;
  border-radius: 12px;
}
.register-header {
  text-align: center;
  margin-bottom: 24px;
}
.register-logo {
  font-size: 48px;
  margin-bottom: 8px;
}
.register-header h2 {
  margin: 0 0 4px;
  font-size: 24px;
  color: #1a1a1a;
}
.register-header p {
  margin: 0;
  color: #8c8c8c;
  font-size: 14px;
}
.success-info {
  text-align: center;
  font-size: 14px;
}
.success-info p {
  margin: 4px 0;
}
.success-info b {
  color: #1677ff;
  font-size: 16px;
}
.muted {
  color: #8c8c8c;
}
</style>
