<template>
  <div class="chat-layout">
    <!-- 会话列表侧边栏 -->
    <aside class="conv-sidebar">
      <button class="new-conv-btn" @click="newConversation">＋ 新对话</button>
      <div class="conv-list">
        <div
          v-for="conv in conversations"
          :key="conv.id"
          :class="['conv-item', { active: conv.id === activeId }]"
          @click="switchConversation(conv.id)"
        >
          <div class="conv-title">{{ conv.title || '新对话' }}</div>
          <div class="conv-time">{{ conv.time }}</div>
        </div>
      </div>
      <div v-if="conversations.length === 0" class="no-convs">暂无历史对话</div>
    </aside>

    <!-- 对话区域 -->
    <div class="chat-main">
      <div class="chat-messages" ref="msgContainer">
        <div v-if="activeMessages.length === 0" class="empty-state">
          <h2>金融投研智能 Copilot</h2>
          <p>输入股票代码或公司名称，快速获取财务分析、舆情解读或投研报告。</p>
          <div class="examples">
            <button v-for="q in quickQuestions" :key="q" @click="sendMessage(q)">{{ q }}</button>
          </div>
        </div>

        <div v-for="(msg, i) in activeMessages" :key="i" :class="['message', msg.role]">
          <div class="avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
          <div class="bubble">
            <div v-if="msg.intent" class="intent-tag">{{ intentLabel(msg.intent) }}</div>
            <div class="content" v-html="renderMarkdown(msg.content)" />
            <div v-if="msg.streaming" class="typing-indicator">
              <span></span><span></span><span></span>
            </div>
            <div v-if="msg.sources?.length" class="sources">
              来源: {{ msg.sources.join(', ') }}
            </div>
          </div>
        </div>
      </div>

      <div class="chat-input">
        <textarea
          v-model="input"
          @keydown.enter.exact.prevent="sendMessage(input)"
          @keydown.shift.enter="input += '\n'"
          placeholder="输入问题，如：分析茅台2024Q3的盈利能力..."
          rows="2"
          :disabled="loading"
        />
        <button @click="sendMessage(input)" :disabled="loading || !input.trim()">
          {{ loading ? '⏳' : '➤' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { marked } from 'marked'
import { postChat, subscribeTaskStream } from '@/api/chat'

interface Message {
  role: 'user' | 'assistant'
  content: string
  intent?: string
  streaming?: boolean
  sources?: string[]
  taskId?: string
}

interface Conversation {
  id: number
  title: string
  time: string
  messages: Message[]
}

let nextId = 1
const conversations = ref<Conversation[]>([])
const activeId = ref(0)
const input = ref('')
const loading = ref(false)
const msgContainer = ref<HTMLElement>()

const quickQuestions = [
  '分析茅台2024Q3的盈利能力',
  '宁德时代最近有什么新闻',
  '全面分析比亚迪并出份报告',
]

const activeMessages = computed(() => {
  const conv = conversations.value.find(c => c.id === activeId.value)
  return conv ? conv.messages : []
})

function newConversation() {
  // 如果当前会话为空，不创建新的
  if (activeMessages.value.length === 0 && conversations.value.length > 0) {
    return
  }
  const id = nextId++
  const now = new Date()
  conversations.value.unshift({
    id,
    title: '',
    time: `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`,
    messages: [],
  })
  activeId.value = id
}

function switchConversation(id: number) {
  activeId.value = id
}

function ensureActiveConv() {
  if (conversations.value.length === 0) {
    newConversation()
  }
}

function renderMarkdown(text: string): string {
  return marked.parse(text, { breaks: true }) as string
}

function intentLabel(intent: string): string {
  const map: Record<string, string> = {
    simple_query: '数据查询',
    financial_analysis: '财务分析',
    sentiment_analysis: '舆情分析',
    comprehensive: '综合分析',
  }
  return map[intent] || intent
}

async function sendMessage(text: string) {
  const trimmed = text.trim()
  if (!trimmed || loading.value) return

  ensureActiveConv()
  const conv = conversations.value.find(c => c.id === activeId.value)!

  // 自动标题：第一句用户消息的前 20 字
  if (!conv.title) {
    conv.title = trimmed.slice(0, 20) + (trimmed.length > 20 ? '…' : '')
  }

  input.value = ''
  loading.value = true

  conv.messages.push({ role: 'user', content: trimmed })
  const aiMsg: Message = { role: 'assistant', content: '', streaming: true, intent: '' }
  conv.messages.push(aiMsg)
  await scrollBottom()

  await postChat(
    trimmed,
    (intent) => { aiMsg.intent = intent },
    (text) => { aiMsg.content += text; scrollBottom() },
    (taskId) => {
      // 仅综合报告异步任务走这里：订阅进度流
      aiMsg.intent = 'comprehensive'
      aiMsg.taskId = taskId
      aiMsg.content = '⏳ 任务已提交，正在生成报告...\n\n'
      subscribeTaskStream(
        taskId,
        (msg) => { aiMsg.content += `> ${msg}\n\n`; scrollBottom() },
        (report) => {
          aiMsg.streaming = false
          aiMsg.content = report || '报告生成完成，但内容为空。'
          loading.value = false
          scrollBottom()
        },
        (err) => {
          aiMsg.streaming = false
          aiMsg.content += `\n\n❌ ${err}`
          loading.value = false
        },
      )
    },
    (error) => {
      aiMsg.streaming = false
      aiMsg.content += `\n\n错误: ${error}`
      loading.value = false
    },
    () => {
      // 快通道 SSE 流正常结束
      aiMsg.streaming = false
      loading.value = false
    },
  )
}

async function scrollBottom() {
  await nextTick()
  if (msgContainer.value) {
    msgContainer.value.scrollTop = msgContainer.value.scrollHeight
  }
}
</script>

<style scoped>
.chat-layout { display: flex; height: calc(100vh - 48px); max-width: 1100px; margin: 0 auto; }

/* --- 侧边栏 --- */
.conv-sidebar {
  width: 220px; flex-shrink: 0; border-right: 1px solid #eee; padding: 16px 12px;
  display: flex; flex-direction: column; overflow-y: auto; background: #fafbfc;
}
.new-conv-btn {
  width: 100%; padding: 10px; border: 1px dashed #4a90d9; border-radius: 8px;
  background: #fff; color: #4a90d9; font-size: 14px; cursor: pointer;
  transition: 0.2s; margin-bottom: 12px;
}
.new-conv-btn:hover { background: #e8f0fe; }

.conv-list { flex: 1; overflow-y: auto; }
.conv-item {
  padding: 10px 12px; border-radius: 6px; cursor: pointer;
  margin-bottom: 4px; transition: 0.15s;
}
.conv-item:hover { background: #e8e8e8; }
.conv-item.active { background: #e8f0fe; }

.conv-title { font-size: 13px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #333; }
.conv-time { font-size: 11px; color: #999; margin-top: 2px; }
.no-convs { font-size: 13px; color: #999; text-align: center; margin-top: 40px; }

/* --- 对话区 --- */
.chat-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.chat-messages { flex: 1; overflow-y: auto; padding: 20px 24px; }
.empty-state { text-align: center; padding: 80px 20px 0; }
.empty-state h2 { font-size: 24px; margin-bottom: 12px; }
.empty-state p { color: #666; margin-bottom: 24px; }
.examples { display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; }
.examples button { padding: 8px 16px; border: 1px solid #ddd; border-radius: 20px; background: #fff; cursor: pointer; font-size: 13px; transition: 0.2s; }
.examples button:hover { border-color: #4a90d9; color: #4a90d9; }

.message { display: flex; gap: 12px; margin-bottom: 20px; }
.message.user { flex-direction: row-reverse; }
.avatar { width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; }
.message.user .avatar { background: #4a90d9; }
.message.assistant .avatar { background: #f0f0f0; }
.bubble { max-width: 75%; padding: 12px 16px; border-radius: 12px; font-size: 14px; line-height: 1.6; }
.message.user .bubble { background: #4a90d9; color: #fff; border-bottom-right-radius: 4px; }
.message.assistant .bubble { background: #fff; border: 1px solid #e8e8e8; border-bottom-left-radius: 4px; }

.intent-tag { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 10px; background: #e8f0fe; color: #4a90d9; margin-bottom: 8px; }

.content :deep(p) { margin: 4px 0; }
.content :deep(strong) { font-weight: 600; }
.content :deep(table) { border-collapse: collapse; margin: 8px 0; }
.content :deep(th), .content :deep(td) { border: 1px solid #ddd; padding: 6px 10px; font-size: 13px; text-align: left; }
.content :deep(th) { background: #f5f7fa; }
.content :deep(blockquote) { border-left: 3px solid #ddd; padding-left: 12px; color: #666; margin: 8px 0; }

.typing-indicator { display: flex; gap: 4px; padding: 4px 0; }
.typing-indicator span { width: 6px; height: 6px; border-radius: 50%; background: #ccc; animation: bounce 1.4s infinite; }
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }
@keyframes bounce { 0%, 60%, 100% { transform: translateY(0); } 30% { transform: translateY(-4px); } }

.sources { font-size: 11px; color: #999; margin-top: 8px; border-top: 1px solid #eee; padding-top: 6px; }

.chat-input { display: flex; gap: 8px; padding: 16px 24px; border-top: 1px solid #eee; background: #f5f7fa; }
.chat-input textarea { flex: 1; padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; resize: none; outline: none; font-family: inherit; }
.chat-input textarea:focus { border-color: #4a90d9; }
.chat-input button { width: 44px; height: 44px; border: none; border-radius: 8px; background: #4a90d9; color: #fff; font-size: 18px; cursor: pointer; flex-shrink: 0; }
.chat-input button:disabled { background: #ccc; cursor: not-allowed; }
</style>
