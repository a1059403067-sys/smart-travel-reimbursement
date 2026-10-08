import client from './client'
import type { DashboardData, TravelStats } from '@/types'

export const travelApi = {
  // REQ-1 GET /api/travel/dashboard（契约已就绪）
  dashboard() {
    return client.get<DashboardData>('/travel/dashboard')
  },

  // REQ-4 GET /api/travel/stats（契约已就绪）
  stats(params?: { trip_type?: string }) {
    return client.get<TravelStats>('/travel/stats', { params })
  },
}
