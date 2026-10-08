<template>
  <div class="chat-view">
    <!-- 消息列表 -->
    <div ref="scrollRef" class="chat-scroll">
      <template v-for="(msg, i) in messages" :key="i">
        <ChatBubble :role="msg.role">
          <MarkdownRenderer v-if="msg.role === 'assistant'" :content="msg.content" />
          <span v-else>{{ msg.content }}</span>
          <!-- R-24：引导卡片（发票报销 / 数据分析等） -->
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

      <!-- 流式输出中的气泡 -->
      <ChatBubble v-if="isStreaming || streamingContent" role="assistant">
        <div v-if="routingLabel" class="routing-tag">
          <el-tag size="small" type="info">意图：{{ routingLabel }}</el-tag>
        </div>
        <div v-if="progressText" class="progress-text">⏳ {{ progressText }}</div>
        <MarkdownRenderer :content="streamingContent || '…'" />
      </ChatBubble>

      <el-empty
        v-if="!messages.length && !isStreaming"
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
import { nextTick, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { v4 as uuidv4 } from 'uuid'
import ChatBubble from '@/components/chat/ChatBubble.vue'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import { useSSEChat, type GuidanceCard } from '@/composables/useSSEChat'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  guidance?: GuidanceCard[]
}

const router = useRouter()
const messages = ref<ChatMessage[]>([])
const draft = ref('')
const scrollRef = ref<HTMLElement>()
const sessionId = uuidv4() // 简单处理：每页面一个会话；后续可接入会话管理

const {
  streamingContent, isStreaming, routingLabel, progressText,
  guidanceCards, error, sendStream, abort,
} = useSSEChat()

// 离开页面时中止进行中的流式请求（审核遗留微瑕）
onBeforeUnmount(abort)

async function scrollToBottom() {
  await nextTick()
  scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior: 'smooth' })
}

async function handleSend() {
  const text = draft.value.trim()
  if (!text || isStreaming.value) return

  messages.value.push({ role: 'user', content: text })
  draft.value = ''
  await scrollToBottom()

  await sendStream(sessionId, text, scrollToBottom)
  if (streamingContent.value) {
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
