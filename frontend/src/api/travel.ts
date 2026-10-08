import client from './client'
import type { TravelStats } from '@/types'

export const travelApi = {
  // GET /api/travel/stats（契约已就绪）
  stats(params?: { trip_type?: string }) {
    return client.get<TravelStats>('/travel/stats', { params })
  },
}
