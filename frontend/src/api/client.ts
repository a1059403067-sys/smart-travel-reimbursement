import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

const client = axios.create({
  baseURL: (import.meta.env.VITE_API_BASE_URL ?? '') + '/api',
  timeout: 30_000,
})

// 请求拦截器：注入 JWT（懒加载 store 避免循环依赖）
client.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem('travel-token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应拦截器：统一错误处理
client.interceptors.response.use(
  res => res,
  (error: AxiosError<{ detail: string }>) => {
    const status = error.response?.status
    const detail = error.response?.data?.detail
    // login 请求的 401/403 由 LoginView 展示契约文案，此处不重复处理
    const isLoginRequest = error.config?.url?.includes('/auth/login')

    if (status === 401 && !isLoginRequest) {
      // 同时清除 Pinia store（响应式 token）和 localStorage，
      // 否则 auth.isLoggedIn 仍为 true，router.push('/login') 会被导航守卫重定向回 /dashboard
      useAuthStore().logout()
      ElMessage.warning('登录已过期，请重新登录')
      router.push('/login').catch(() => {})
      return Promise.reject(error)
    }

    if (status === 403) {
      // 显示契约文案（如「账号已被禁用，请联系管理员」），无 detail 时兜底
      ElMessage.error(detail ?? '权限不足')
    } else if (status === 429) {
      ElMessage.warning('请求过于频繁，请稍后再试')
    } else if (status && status >= 500) {
      ElMessage.error(detail ?? '服务异常，请稍后重试')
    } else if (detail) {
      ElMessage.error(detail)
    }

    return Promise.reject(error)
  },
)

export default client
