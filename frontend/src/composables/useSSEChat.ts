import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'

// 统一对话 SSE（POST /api/chat，契约 ⏳ 草案，帧格式以接口契约.md 为准）
// 草案帧：
//   event: routing_decision  data: {"label":"travel_apply","routed_by":"llm"}
//   event: progress          data: {"stage":"train_search","text":"正在查询车次..."}
//   event: token             data: {"content":"..."}
//   event: meta              data: {"structured_output":{...},"fallback_used":false}
//   event: done              data: {}
//   event: error             data: {"detail":"..."}
// VITE_API_BASE_URL 语义与 client.ts 一致：后端源地址（不带 /api 后缀）
const STREAM_TIMEOUT_MS = 120_000

export function useSSEChat() {
  const streamingContent = ref('')
  const isStreaming = ref(false)
  const routingLabel = ref<string | null>(null)
  const progressText = ref<string | null>(null)
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
                routingLabel.value = payload.label ?? null
                break
              case 'progress':
                progressText.value = payload.text ?? null
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

  return { streamingContent, isStreaming, routingLabel, progressText, lastMeta, error, sendStream, abort }
}
