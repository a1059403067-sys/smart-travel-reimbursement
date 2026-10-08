import client from './client'
import type { DashboardData, TravelRequest, TravelRequestListResponse, TravelStats } from '@/types'

export interface TravelRequestQuery {
  mine?: boolean
  to_review?: boolean
  status?: string
  page?: number
  page_size?: number
}

export const travelApi = {
  // REQ-1 GET /api/travel/dashboard（契约已就绪）
  dashboard() {
    return client.get<DashboardData>('/travel/dashboard')
  },

  // REQ-4 GET /api/travel/stats（契约已就绪）
  stats(params?: { trip_type?: string }) {
    return client.get<TravelStats>('/travel/stats', { params })
  },

  // REQ-6 差旅申请（契约已就绪）：mine=true 我的申请 / to_review=true 待审批列表
  requests(params: TravelRequestQuery) {
    return client.get<TravelRequestListResponse>('/travel/requests', { params })
  },

  requestDetail(id: number | string) {
    return client.get<TravelRequest>(`/travel/requests/${id}`)
  },

  requestApprove(id: number | string) {
    return client.post<TravelRequest>(`/travel/requests/${id}/approve`)
  },

  requestReject(id: number | string, reason: string) {
    return client.post<TravelRequest>(`/travel/requests/${id}/reject`, { reason })
  },
}
