import client from './client'
import type { Reimbursement, ReimbursementListResponse } from '@/types'

// REQ-8 报销单管理（契约已就绪）
export const reimbursementApi = {
  // mine=true 我的报销单；to_review=true 待审批列表（按 current_step 匹配角色）
  list(params: { mine?: boolean; to_review?: boolean }) {
    return client.get<ReimbursementListResponse>('/reimbursements', { params })
  },

  detail(id: number | string) {
    return client.get<Reimbursement>(`/reimbursements/${id}`)
  },

  create(data: { title: string; total_amount?: number; travel_request_id?: number }) {
    return client.post<Reimbursement>('/reimbursements', data)
  },

  submit(id: number | string) {
    return client.post<Reimbursement>(`/reimbursements/${id}/submit`)
  },

  approve(id: number | string) {
    return client.post<Reimbursement>(`/reimbursements/${id}/approve`)
  },

  reject(id: number | string, reason: string) {
    return client.post<Reimbursement>(`/reimbursements/${id}/reject`, { reason })
  },
}
