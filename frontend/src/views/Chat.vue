<template>
  <div class="chat-container">
    <div class="chat-messages" ref="msgContainer">
      <div v-if="messages.length === 0" class="empty-state">
        <h2>金融投研智能 Copilot</h2>
        <p>输入股票代码或公司名称，快速获取财务分析、舆情解读或投研报告。</p>
        <div class="examples">
          <button v-for="q in quickQuestions" :key="q" @click="sendMessage(q)">{{ q }}</button>
        </div>
      </div>

      <div v-for="(msg, i) in messages" :key="i" :class="['message', msg.role]">
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

    <div class="upload-area" v-if="uploading || uploadStatus">
      <span v-if="uploading" class="upload-status">📄 正在上传解析...</span>
      <span v-else-if="uploadStatus" :class="['upload-status', uploadStatus.type]">
        {{ uploadStatus.text }}
      </span>
    </div>

    <div class="chat-input">
      <label class="upload-btn" title="上传投研报告 PDF">
        📎
        <input type="file" accept=".pdf" @change="onFileSelected" hidden ref="fileInput" />
      </label>
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
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { marked } from 'marked'
import { postChat, uploadReport } from '@/api/chat'

interface Message {
  role: 'user' | 'assistant'
  content: string
  intent?: string
  streaming?: boolean
  sources?: string[]
  taskId?: string
}

const input = ref('')
const loading = ref(false)
const messages = ref<Message[]>([])
const fileInput = ref<HTMLInputElement>()
const uploading = ref(false)
const uploadStatus = ref<{ text: string; type: string } | null>(null)
const msgContainer = ref<HTMLElement>()

const quickQuestions = [
  '分析茅台2024Q3的盈利能力',
  '宁德时代最近有什么新闻',
  '全面分析比亚迪并出份报告',
]

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

  input.value = ''
  loading.value = true

  messages.value.push({ role: 'user', content: trimmed })
  const aiMsg: Message = { role: 'assistant', content: '', streaming: true, intent: '' }
  messages.value.push(aiMsg)
  await scrollBottom()

  await postChat(
    trimmed,
    (intent) => { aiMsg.intent = intent },
    (text) => { aiMsg.content += text; scrollBottom() },
    (taskId) => {
      aiMsg.streaming = false
      loading.value = false
    },
    (error) => {
      aiMsg.streaming = false
      aiMsg.content += `\n\n错误: ${error}`
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

async function onFileSelected(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  uploading.value = true
  uploadStatus.value = null

  try {
    const result = await uploadReport(file, '', file.name.replace('.pdf', ''))
    uploadStatus.value = {
      text: `✅ "${result.doc_title}" 上传成功，${result.chunks} 个切片已入库`,
      type: 'success',
    }
    // 自动发送消息告知 AI
    const msg = `我刚上传了一份研报：${result.doc_title}，请基于这份报告帮我分析`
    input.value = msg
  } catch (e: any) {
    uploadStatus.value = {
      text: `❌ 上传失败: ${e.message}`,
      type: 'error',
    }
  } finally {
    uploading.value = false
    if (target) target.value = '' // 允许重复上传同一文件
  }
}
</script>

<style scoped>
.chat-container { display: flex; flex-direction: column; height: calc(100vh - 48px); max-width: 900px; margin: 0 auto; }
.chat-messages { flex: 1; overflow-y: auto; padding: 20px 0; }
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

.upload-area { padding: 8px 0; text-align: center; }
.upload-status { font-size: 13px; padding: 6px 12px; border-radius: 6px; }
.upload-status.success { background: #e8f5e9; color: #2e7d32; }
.upload-status.error { background: #fdecea; color: #c62828; }

.chat-input { display: flex; gap: 8px; padding: 16px 0; border-top: 1px solid #eee; background: #f5f7fa; align-items: flex-end; }
.chat-input textarea { flex: 1; padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; resize: none; outline: none; font-family: inherit; }
.chat-input textarea:focus { border-color: #4a90d9; }
.chat-input button { width: 44px; height: 44px; border: none; border-radius: 8px; background: #4a90d9; color: #fff; font-size: 18px; cursor: pointer; flex-shrink: 0; }
.chat-input button:disabled { background: #ccc; cursor: not-allowed; }

.upload-btn { display: flex; align-items: center; justify-content: center; width: 44px; height: 44px; border: 1px dashed #ccc; border-radius: 8px; font-size: 18px; cursor: pointer; flex-shrink: 0; transition: 0.2s; background: #fff; }
.upload-btn:hover { border-color: #4a90d9; background: #e8f0fe; }
.upload-btn input { display: none; }
</style>
