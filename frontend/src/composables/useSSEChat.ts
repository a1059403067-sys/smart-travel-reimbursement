import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'

// 统一对话 SSE（POST /api/chat，契约 REQ-5 已就绪）
// 帧格式（实测）：`data: {"type": "...", ...字段}`，无 event 行（双格式兼容解析）
//   routing_decision: label/reason/routed_by/fallback_used/label_display（中文名）
//   progress: stage/text
//   token: content
//   guidance: message/action_label/action_url（引导卡片，R-24）
//   meta: structured_output/fallback_used
//   done: {}（正常路径末尾）；error: detail（终止帧，error 后不再推 done）
// VITE_API_BASE_URL 语义与 client.ts 一致：后端源地址（不带 /api 后缀）
const STREAM_TIMEOUT_MS = 120_000

// 意图中文兜底映射（契约已带 label_display，此表仅当后端未返回时兜底）
const LABEL_CN: Record<string, string> = {
  weather_ticket: '天气票务',
  travel_apply: '差旅申请',
  reimbursement: '发票报销',
  analysis: '数据分析',
  chitchat: '闲聊',
}

export interface GuidanceCard {
  message: string
  action_label: string
  action_url: string
}

export function useSSEChat() {
  const streamingContent = ref('')
  const isStreaming = ref(false)
  const routingLabel = ref<string | null>(null)
  const progressText = ref<string | null>(null)
  const guidanceCards = ref<GuidanceCard[]>([])
  const lastMeta = ref<Record<string, unknown> | null>(null)
  const error = ref<string | null>(null)

  let controller: AbortController | null = null

  async function sendStream(
    sessionId: string,
    message: string,
    onToken?: (token: string) => void,
  ) {
    isStreaming.value = true
    streamingContent.value = ''
    routingLabel.value = null
    progressText.value = null
    guidanceCards.value = []
    lastMeta.value = null
    error.value = null

    const auth = useAuthStore()
    const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? '') + '/api'

    // 超时兜底：AbortController 同时服务"超时中止"与"页面卸载中止"
    controller = new AbortController()
    const timer = window.setTimeout(() => controller?.abort(), STREAM_TIMEOUT_MS)

    try {
      const response = await fetch(`${baseUrl}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${auth.token}`,
        },
        body: JSON.stringify({ session_id: sessionId, message }),
        signal: controller.signal,
      })

      if (!response.ok) {
        // 读后端错误 detail（契约统一 {"detail": "中文提示"}）
        let detail = ''
        try {
          const body = await response.json()
          detail = (body as { detail?: string }).detail ?? ''
        } catch { /* body 非 JSON 时忽略 */ }
        throw new Error(detail || `HTTP ${response.status}`)
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let currentEvent = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim()
            continue
          }
          if (!line.startsWith('data:')) continue
          const raw = line.slice(5).trim()
          if (!raw) continue

          try {
            const payload = JSON.parse(raw)
            // 兼容两种帧：event: 行声明类型，或 data JSON 内带 type 字段
            const type: string = currentEvent || payload.type || ''
            switch (type) {
              case 'routing_decision':
                // R-28：优先展示契约 label_display 中文名，缺失时用本地映射兜底
                routingLabel.value =
                  payload.label_display ??
                  (payload.label ? LABEL_CN[payload.label] ?? payload.label : null)
                break
              case 'progress':
                progressText.value = payload.text ?? null
                break
              case 'guidance':
                // R-24：引导卡片（reimbursement→/reimbursement、analysis→/analytics）
                guidanceCards.value.push({
                  message: payload.message ?? '',
                  action_label: payload.action_label ?? '',
                  action_url: payload.action_url ?? '',
                })
                break
              case 'token':
                if (payload.content) {
                  streamingContent.value += payload.content
                  onToken?.(payload.content)
                }
                break
              case 'meta':
                lastMeta.value = payload
                break
              case 'done':
                isStreaming.value = false
                break
              case 'error':
                error.value = payload.detail ?? payload.message ?? '流式响应出错'
                isStreaming.value = false
                break
            }
          } catch {
            // 忽略非 JSON 行
          }
        }
      }
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        error.value = '响应超时，请稍后重试'
      } else {
        error.value = e instanceof Error ? e.message : '连接失败'
      }
    } finally {
      window.clearTimeout(timer)
      isStreaming.value = false
      controller = null
    }
  }

  function abort() {
    controller?.abort()
  }

  return { streamingContent, isStreaming, routingLabel, progressText, guidanceCards, lastMeta, error, sendStream, abort }
}
