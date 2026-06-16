<template>
  <div class="report-container">
    <div v-if="loading" class="loading-state">
      <div class="spinner"></div>
      <p>报告生成中... {{ pollingCount > 0 ? `(已轮询 ${pollingCount} 次)` : '' }}</p>
    </div>

    <div v-else-if="error" class="error-state">
      <p>{{ error }}</p>
      <button @click="$router.push('/')">返回对话</button>
    </div>

    <div v-else-if="report" class="report-content">
      <div class="report-header">
        <button class="back-btn" @click="$router.push('/')">返回</button>
        <span class="task-id">任务 ID: {{ taskId }}</span>
      </div>
      <div class="report-body" v-html="renderMarkdown(report)" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { marked } from 'marked'
import { getReport } from '@/api/reports'
import { getTaskStatus } from '@/api/chat'

const route = useRoute()
const taskId = route.params.taskId as string

const loading = ref(true)
const error = ref('')
const report = ref('')
const pollingCount = ref(0)
let pollTimer: ReturnType<typeof setInterval> | null = null

function renderMarkdown(text: string): string {
  return marked.parse(text, { breaks: true }) as string
}

onMounted(async () => {
  try {
    const data = await getReport(taskId)
    report.value = data.report
    loading.value = false
    return
  } catch {
    // 报告未就绪，开始轮询
  }

  pollTimer = setInterval(async () => {
    try {
      pollingCount.value++
      const status = await getTaskStatus(taskId)
      if (status.status === 'done') {
        if (pollTimer) clearInterval(pollTimer)
        report.value = status.result?.draft_report || ''
        loading.value = false
      } else if (status.status === 'failed') {
        if (pollTimer) clearInterval(pollTimer)
        error.value = '报告生成失败: ' + (status.error_log || '未知错误')
        loading.value = false
      }
    } catch {
      if (pollingCount.value > 20) {
        if (pollTimer) clearInterval(pollTimer)
        error.value = '轮询超时，请稍后重试'
        loading.value = false
      }
    }
  }, 3000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.report-container { max-width: 860px; margin: 0 auto; }
.loading-state { text-align: center; padding: 80px 0; }
.spinner { width: 36px; height: 36px; border: 3px solid #e0e0e0; border-top-color: #4a90d9; border-radius: 50%; animation: spin 0.8s linear infinite; margin: 0 auto 16px; }
@keyframes spin { to { transform: rotate(360deg); } }
.loading-state p { color: #666; }
.error-state { text-align: center; padding: 80px 0; color: #e74c3c; }
.error-state button { margin-top: 16px; padding: 8px 20px; border: 1px solid #ddd; border-radius: 6px; background: #fff; cursor: pointer; }

.report-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.back-btn { padding: 6px 14px; border: 1px solid #ddd; border-radius: 6px; background: #fff; cursor: pointer; font-size: 13px; }
.task-id { font-size: 12px; color: #999; }

.report-body { background: #fff; padding: 40px; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); line-height: 1.8; font-size: 15px; }
.report-body :deep(h1) { font-size: 22px; margin-bottom: 20px; text-align: center; }
.report-body :deep(h2) { font-size: 18px; margin: 28px 0 12px; padding-bottom: 8px; border-bottom: 1px solid #eee; }
.report-body :deep(p) { margin: 8px 0; }
.report-body :deep(table) { border-collapse: collapse; width: 100%; margin: 12px 0; }
.report-body :deep(th), .report-body :deep(td) { border: 1px solid #ddd; padding: 8px 12px; font-size: 14px; text-align: left; }
.report-body :deep(th) { background: #f5f7fa; font-weight: 600; }
.report-body :deep(blockquote) { border-left: 3px solid #4a90d9; padding: 8px 16px; margin: 12px 0; background: #f8f9fe; color: #555; font-size: 14px; }
</style>
