import client from './client'
import type { ChatHistoryResponse } from '@/types'

export const chatApi = {
  // REQ-11 GET /api/chat/history（⏳ 后端 A-17 实现中，前端已按契约对接）
  // limit 默认 3；before_id 游标（缺省取最新，传最早一条的 id 继续向前翻页）
  history(params: { limit?: number; before_id?: number }) {
    return client.get<ChatHistoryResponse>('/chat/history', { params })
  },
}
