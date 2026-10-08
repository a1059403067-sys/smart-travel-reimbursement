import client from './client'
import type { LoginResponse, RegisterResponse } from '@/types'

export const authApi = {
  login(data: { username: string; password: string }) {
    return client.post<LoginResponse>('/auth/login', data)
  },

  me() {
    return client.get<{ user_id: string; role: string; tenant_id: string }>('/auth/me')
  },

  // REQ-9 POST /api/auth/register（⏳ 后端 A-16 实现中，前端已按契约对接）
  register(data: { real_name: string; department: string; password: string }) {
    return client.post<RegisterResponse>('/auth/register', data)
  },

  // REQ-10 GET /api/departments（⏳ 后端 A-16 实现中）
  departments() {
    return client.get<{ items: string[] }>('/departments')
  },
}
