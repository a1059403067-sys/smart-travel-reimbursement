// 全局类型定义（以接口契约.md 为准）

export type Role = 'employee' | 'approver' | 'finance' | 'admin'

export interface UserInfo {
  user_id: string
  username?: string
  real_name: string
  role: Role
}

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  role: Role
  user_id: string
  real_name: string
}

// ── 统计 ──
// REQ-4 GET /api/travel/stats（契约已就绪）
export interface TravelStats {
  summary: {
    total_trips: number
    total_amount: number
  }
  department_expense: Array<{ name: string; value: number; percentage: number }>
}

// REQ-1 GET /api/travel/dashboard（契约已就绪）
export interface DashboardData extends TravelStats {
  summary: TravelStats['summary'] & {
    pending_approvals?: number
    month_new_trips?: number
  }
  monthly_trend: Array<{ month: string; trips: number; amount: number }>
  expense_by_type: Array<{ name: string; value: number; percentage: number }>
  // 报销单状态分布（五类补零：草稿/待审批/已通过/已驳回/已打款）
  reimbursement_status: Array<{ name: string; value: number }>
}

// ── 报销单（REQ-8，契约已就绪）──
// 状态机：draft → pending(一级待经理) → pending(二级待财务) → approved/rejected → paid
export type ReimbursementStatus = 'draft' | 'pending' | 'approved' | 'rejected' | 'paid'

export interface ApprovalRecord {
  step: number
  action: 'approve' | 'reject'
  comment: string
  approver_name: string
  created_at: string
}

export interface Reimbursement {
  id: number | string
  title: string
  status: ReimbursementStatus
  current_step: number // 1=待部门经理（approver），2=待财务（finance）
  total_amount: number
  user_name: string
  department: string
  created_at: string
  travel_request_title?: string | null // 关联差旅申请，可为 null
  reject_reason?: string | null
  approvals?: ApprovalRecord[]
  // 契约外字段（R-19 待契约补充声明，后端已返回）：owner 判断依赖
  user_id?: number
}

export interface ReimbursementListResponse {
  items: Reimbursement[]
  total: number
}

// ── 发票解析（REQ-7，契约草案）──
export interface InvoiceParseResult {
  invoice: {
    invoice_date: string
    amount: number
    invoice_code: string
    seller_name: string
  }
  needs_human_review: boolean
  problems: string[]
}
