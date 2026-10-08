import client from './client'
import type { LoginResponse } from '@/types'

export const authApi = {
  login(data: { username: string; password: string }) {
    return client.post<LoginResponse>('/auth/login', data)
  },

  me() {
    return client.get<{ user_id: string; role: string; tenant_id: string }>('/auth/me')
  },
}
