<template>
  <div class="chat-view">
    <!-- 消息列表（历史消息 + 实时消息；向上滚动到顶加载更早历史） -->
    <div ref="scrollRef" class="chat-scroll" @scroll="handleScroll">
      <!-- 顶部加载提示 -->
      <div v-if="loadingMore" class="load-more-tip">正在加载更早的对话…</div>
      <div v-else-if="!hasMore && messages.length" class="load-more-tip muted-tip">已显示全部历史消息</div>

      <template v-for="(msg, i) in messages" :key="msg.id ?? `local-${i}`">
        <ChatBubble :role="msg.role">
          <MarkdownRenderer v-if="msg.role === 'assistant' && msg.content" :content="msg.content" />
          <span v-else-if="msg.role === 'user'">{{ msg.content }}</span>
          <!-- 引导卡片（历史消息的 guidance 同样渲染，可点击跳转） -->
          <div v-if="msg.guidance?.length" class="guidance-cards">
            <el-card
              v-for="(g, gi) in msg.guidance"
              :key="gi"
              shadow="hover"
              class="guidance-card"
              @click="router.push(g.action_url)"
            >
              <div class="guidance-msg">{{ g.message }}</div>
              <el-button type="primary" size="small">{{ g.action_label || '前往' }}</el-button>
            </el-card>
          </div>
        </ChatBubble>
      </template>

      <!-- 流式输出中的气泡（guidance-only 意图如 reimbursement 也会在此展示引导卡片） -->
      <ChatBubble v-if="isStreaming || streamingContent || guidanceCards.length" role="assistant">
        <div v-if="routingLabel" class="routing-tag">
          <el-tag size="small" type="info">意图：{{ routingLabel }}</el-tag>
        </div>
        <div v-if="progressText" class="progress-text">⏳ {{ progressText }}</div>
        <MarkdownRenderer v-if="streamingContent" :content="streamingContent" />
        <div v-if="guidanceCards.length" class="guidance-cards">
          <el-card
            v-for="(g, gi) in guidanceCards"
            :key="gi"
            shadow="hover"
            class="guidance-card"
            @click="router.push(g.action_url)"
          >
            <div class="guidance-msg">{{ g.message }}</div>
            <el-button type="primary" size="small">{{ g.action_label || '前往' }}</el-button>
          </el-card>
        </div>
      </ChatBubble>

      <el-empty
        v-if="!messages.length && !isStreaming && !loadingMore"
        description="描述您的出差需求，例如：我下周一去杭州出差三天，帮我查高铁票"
      />
    </div>

    <!-- 输入区 -->
    <div class="chat-input">
      <el-input
        v-model="draft"
        type="textarea"
        :rows="3"
        resize="none"
        placeholder="描述差旅需求（查票 / 订酒店 / 导航 / 报销）"
        :disabled="isStreaming"
        @keydown.enter.exact.prevent="handleSend"
      />
      <div class="input-actions">
        <span class="hint">Enter 发送，Shift+Enter 换行</span>
        <el-button type="primary" :loading="isStreaming" @click="handleSend">发送</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { v4 as uuidv4 } from 'uuid'
import ChatBubble from '@/components/chat/ChatBubble.vue'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import { useSSEChat, type GuidanceCard } from '@/composables/useSSEChat'
import { chatApi } from '@/api/chat'
import type { ChatHistoryItem } from '@/types'

interface ChatMessage {
  id?: number // 后端历史消息有 id（游标基准）；本地新消息无 id
  role: 'user' | 'assistant'
  content: string
  guidance?: GuidanceCard[]
}

const router = useRouter()
const messages = ref<ChatMessage[]>([])
const draft = ref('')
const scrollRef = ref<HTMLElement>()

// REQ-11：会话固定（每用户一个），session_id 后端按 user 推导，前端仅用于流式请求
const sessionId = uuidv4()
const HISTORY_PAGE_SIZE = 3

// 历史翻页状态
const hasMore = ref(false)
const loadingMore = ref(false)
// 游标基准：已加载历史批次中的最小 id（本地新消息无 id，不影响翻页）
const lastLoadedMinId = ref<number | undefined>(undefined)

const {
  streamingContent, isStreaming, routingLabel, progressText,
  guidanceCards, error, sendStream, abort,
} = useSSEChat()

// 离开页面时中止进行中的流式请求
onBeforeUnmount(abort)

function fromHistoryItem(item: ChatHistoryItem): ChatMessage {
  return {
    id: item.id,
    role: item.role,
    content: item.content,
    guidance: item.guidance ?? undefined,
  }
}

// 首屏：拉最近 3 条；向前翻页：before_id 游标
async function loadHistory(beforeId?: number) {
  if (beforeId === undefined) {
    // 首屏加载（最近 3 条），直接替换并滚到底部
    try {
      const { data } = await chatApi.history({ limit: HISTORY_PAGE_SIZE })
      messages.value = (data.items ?? []).map(fromHistoryItem)
      hasMore.value = data.has_more
      const ids = data.items.map(i => i.id)
      lastLoadedMinId.value = ids.length ? Math.min(...ids) : undefined
      await scrollToBottom(false)
    } catch {
      // REQ-11 未就绪（404）时静默：空历史，不影响正常聊天
      hasMore.value = false
      lastLoadedMinId.value = undefined
    }
    return
  }

  // 向上滚动加载更早历史：prepend 并保持视口位置
  loadingMore.value = true
  try {
    const { data } = await chatApi.history({ limit: HISTORY_PAGE_SIZE, before_id: beforeId })
    const older = (data.items ?? []).map(fromHistoryItem)
    if (!older.length) {
      hasMore.value = false
      return
    }
    const el = scrollRef.value
    const prevScrollHeight = el?.scrollHeight ?? 0
    const prevScrollTop = el?.scrollTop ?? 0
    messages.value.unshift(...older)
    await nextTick()
    // 视口位置补偿：新内容高度全部加回 scrollTop，避免视口跳变
    if (el) el.scrollTop = prevScrollTop + (el.scrollHeight - prevScrollHeight)
    hasMore.value = data.has_more
    const ids = older.map(i => i.id).filter((v): v is number => v != null)
    lastLoadedMinId.value = ids.length ? Math.min(...ids) : undefined
  } catch {
    hasMore.value = false
  } finally {
    loadingMore.value = false
  }
}

function handleScroll() {
  const el = scrollRef.value
  if (!el || loadingMore.value || !hasMore.value) return
  if (el.scrollTop <= 30) {
    const before = lastLoadedMinId.value
    if (before != null) loadHistory(before)
  }
}

async function scrollToBottom(smooth = true) {
  await nextTick()
  scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
}

async function handleSend() {
  const text = draft.value.trim()
  if (!text || isStreaming.value) return

  messages.value.push({ role: 'user', content: text })
  draft.value = ''
  await scrollToBottom()

  await sendStream(sessionId, text, () => scrollToBottom(false))
  // 有文本或有引导卡片都算有效回复（reimbursement 等意图只推 guidance 无 token）
  if (streamingContent.value || guidanceCards.value.length) {
    messages.value.push({
      role: 'assistant',
      content: streamingContent.value,
      guidance: guidanceCards.value.length ? [...guidanceCards.value] : undefined,
    })
  }
  if (error.value) {
    ElMessage.error(error.value)
  }
  await scrollToBottom()
}

onMounted(() => loadHistory())
</script>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 56px - 3px - 48px - 24px);
  max-width: 900px;
  margin: 0 auto;
}
.chat-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 8px 4px 16px;
}
.load-more-tip {
  text-align: center;
  font-size: 12px;
  color: #1677ff;
  padding: 8px 0;
}
.muted-tip {
  color: #c0c4cc;
}
.chat-input {
  background: #fff;
  border: 1px solid #e5e6eb;
  border-radius: 8px;
  padding: 12px;
}
.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
}
.hint {
  font-size: 12px;
  color: #c0c4cc;
}
.routing-tag {
  margin-bottom: 6px;
}
.progress-text {
  font-size: 12px;
  color: #1677ff;
  margin-bottom: 6px;
}
.guidance-cards {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 10px;
}
.guidance-card {
  cursor: pointer;
  max-width: 240px;
}
.guidance-msg {
  font-size: 13px;
  color: #595959;
  margin-bottom: 8px;
  line-height: 1.5;
}
</style>
