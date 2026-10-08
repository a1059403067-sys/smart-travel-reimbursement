import client from './client'
import type { InvoiceParseResult } from '@/types'

export const invoiceApi = {
  // REQ-7 POST /api/invoice/upload（契约已就绪）
  upload(file: File) {
    const form = new FormData()
    form.append('file', file)
    return client.post<InvoiceParseResult>('/invoice/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60_000,
    })
  },
}
