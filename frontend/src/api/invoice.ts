import client from './client'
import type { InvoiceParseResult } from '@/types'

export const invoiceApi = {
  // POST /api/invoice/upload（契约 ⏳ 规划中，勿对接；UI 已按草案响应结构占位）
  upload(file: File) {
    const form = new FormData()
    form.append('file', file)
    return client.post<InvoiceParseResult>('/invoice/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60_000,
    })
  },
}
