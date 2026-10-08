// 全局类型定义（以接口契约.md 为准；字段待各接口就绪后与契约核对）

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

// ── 报销单（契约待 A 补充；字段来自设计图 前端2/3.png）──
export type ReimbursementStatus = 'draft' | 'pending' | 'approved' | 'rejected'

export interface ExpenseItem {
  id?: string
  expense_type: string // 交通费/住宿费/餐饮费/其他
  amount: number
  expense_date: string
  remark?: string
  invoice_attachment?: string | null // 发票附件路径
}

export interface Reimbursement {
  id: string
  code: string // 报销单号，如 BX202606001
  reason: string // 出差事由
  destination: string
  start_date: string
  end_date: string
  amount: number
  applicant: string
  department: string
  status: ReimbursementStatus
  submitted_at: string
  items?: ExpenseItem[]
  approval?: {
    approver: string
    approved_at: string
    status: 'approved' | 'rejected'
    comment: string
  }
}

// ── 统计（GET /api/travel/stats，契约已就绪）──
export interface TravelStats {
  summary: {
    total_trips: number
    total_amount: number
  }
  department_expense: Array<{ name: string; value: number; percentage: number }>
}

// ── 发票解析（POST /api/invoice/upload，契约草案）──
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
