import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { UserInfo } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('travel-token'))
  const user = ref<UserInfo | null>(parseStoredUser())

  const isLoggedIn = computed(() => !!token.value)
  // 契约：approve/reject 需 role=approver/admin
  const canApprove = computed(() =>
    user.value?.role === 'approver' || user.value?.role === 'admin'
  )
  const isAdmin = computed(() => user.value?.role === 'admin')

  function parseStoredUser(): UserInfo | null {
    try {
      return JSON.parse(localStorage.getItem('travel-user') ?? 'null')
    } catch {
      return null
    }
  }

  function login(accessToken: string, userInfo: UserInfo) {
    token.value = accessToken
    user.value = userInfo
    localStorage.setItem('travel-token', accessToken)
    localStorage.setItem('travel-user', JSON.stringify(userInfo))
  }

  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem('travel-token')
    localStorage.removeItem('travel-user')
  }

  return { token, user, isLoggedIn, canApprove, isAdmin, login, logout }
})
