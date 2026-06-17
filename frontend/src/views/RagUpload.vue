<template>
  <div class="rag-page">
    <h1>📚 知识库管理</h1>
    <p class="subtitle">上传投研报告 PDF，系统自动提取文本、向量化后存入知识库，AI 对话时自动检索引用。</p>

    <!-- 上传区域 -->
    <div
      class="drop-zone"
      :class="{ dragging, uploading }"
      @dragover.prevent="dragging = true"
      @dragleave="dragging = false"
      @drop.prevent="onDrop"
    >
      <div v-if="!uploading" class="drop-content">
        <div class="drop-icon">📄</div>
        <p>拖拽 PDF 文件到此处，或点击选择</p>
        <p class="hint">支持 PDF 格式，单个文件最大 50MB</p>
        <div class="upload-meta">
          <input
            v-model="companyCode"
            placeholder="股票代码（如600519）"
            class="code-input"
          />
          <button class="select-btn" @click="$refs.fileInput.click()">选择文件</button>
          <input
            type="file"
            accept=".pdf"
            ref="fileInput"
            hidden
            @change="onFileSelected"
          />
        </div>
      </div>

      <div v-else class="progress-area">
        <div class="progress-label">
          <span>{{ currentFile?.name }}</span>
          <span>{{ progress }}%</span>
        </div>
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: progress + '%' }"></div>
        </div>
        <p class="progress-step">{{ progressStep }}</p>
      </div>
    </div>

    <div v-if="uploadResult" :class="['result-msg', uploadResult.ok ? 'success' : 'error']">
      {{ uploadResult.ok ? `✅ "${uploadResult.title}" 上传成功 — ${uploadResult.chunks} 个切片已入库` : `❌ ${uploadResult.error}` }}
    </div>

    <!-- 已入库文档 -->
    <div class="doc-header">
      <h2>已入库文档（{{ totalCount }}）</h2>
      <div class="doc-toolbar">
        <input
          v-model="searchQuery"
          placeholder="搜索文档标题或股票代码..."
          class="search-input"
          @input="onSearch"
        />
        <button class="refresh-btn" @click="fetchDocuments">🔄 刷新</button>
      </div>
    </div>

    <div class="doc-list" v-if="filteredDocs.length">
      <div class="doc-card" v-for="doc in filteredDocs" :key="doc.id">
        <div class="doc-icon">📑</div>
        <div class="doc-info">
          <div class="doc-title">{{ doc.doc_title }}</div>
          <div class="doc-meta">
            <span v-if="doc.company_code" class="tag">{{ doc.company_code }}</span>
            <span class="tag">{{ doc.doc_type }}</span>
            <span>{{ doc.chunks }} 个切片</span>
            <span class="time">{{ formatTime(doc.created_at) }}</span>
          </div>
        </div>
        <div class="doc-status" :class="doc.chunks > 0 ? 'ok' : 'fail'">
          {{ doc.chunks > 0 ? '✅ 已解析' : '⚠ 解析失败' }}
        </div>
        <button class="delete-btn" @click="deleteDoc(doc.id)" title="删除">🗑</button>
      </div>
    </div>
    <div v-else class="empty-docs">
      {{ searchQuery ? '没有匹配的文档' : '暂无文档，上传一份 PDF 试试。' }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

interface DocItem {
  id: number
  doc_title: string
  company_code: string
  doc_type: string
  chunks: number
  created_at: string
}

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'
const API_KEY = import.meta.env.VITE_API_KEY || ''

const dragging = ref(false)
const uploading = ref(false)
const progress = ref(0)
const progressStep = ref('')
const currentFile = ref<File | null>(null)
const companyCode = ref('')
const uploadResult = ref<{ ok: boolean; title?: string; chunks?: number; error?: string } | null>(null)
const allDocuments = ref<DocItem[]>([])
const searchQuery = ref('')
const totalCount = ref(0)

onMounted(() => fetchDocuments())

function authHeaders(): Record<string, string> {
  const h: Record<string, string> = {}
  if (API_KEY) h['X-API-Key'] = API_KEY
  return h
}

async function fetchDocuments() {
  try {
    const resp = await fetch(`${API_BASE}/rag/documents?limit=100`, { headers: authHeaders() })
    if (resp.ok) {
      const data = await resp.json()
      allDocuments.value = data.documents || []
      totalCount.value = data.total || allDocuments.value.length
    }
  } catch (e) { /* ignore */ }
}

// 最多显示 10 条，支持搜索过滤
const filteredDocs = computed(() => {
  let docs = allDocuments.value
  const q = searchQuery.value.trim().toLowerCase()
  if (q) {
    docs = docs.filter(d =>
      d.doc_title.toLowerCase().includes(q) ||
      d.company_code.toLowerCase().includes(q)
    )
  }
  return docs.slice(0, 10)
})

function onSearch() { /* computed reacts automatically */ }

async function deleteDoc(id: number) {
  try {
    await fetch(`${API_BASE}/rag/documents/${id}`, { method: 'DELETE', headers: authHeaders() })
    allDocuments.value = allDocuments.value.filter(d => d.id !== id)
    totalCount.value = Math.max(0, totalCount.value - 1)
  } catch (e) { alert('删除失败') }
}

function formatTime(t: string): string {
  if (!t) return ''
  return t.replace('T', ' ').substring(0, 19)
}

function simulateProgress() {
  progress.value = 0
  progressStep.value = '读取文件...'
  const steps = [
    { p: 20, text: '上传中...' },
    { p: 40, text: '提取 PDF 文本...' },
    { p: 60, text: '切分段落...' },
    { p: 80, text: '向量化中（BGE-M3）...' },
    { p: 95, text: '写入数据库...' },
  ]
  let i = 0
  const timer = setInterval(() => {
    if (i < steps.length) { progress.value = steps[i].p; progressStep.value = steps[i].text; i++ }
  }, 600)
  return timer
}

async function onFileSelected(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (file) await uploadFile(file)
}

async function onDrop(event: DragEvent) {
  dragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) await uploadFile(file)
}

async function uploadFile(file: File) {
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    uploadResult.value = { ok: false, error: '仅支持 PDF 文件' }
    return
  }
  currentFile.value = file
  uploading.value = true
  uploadResult.value = null
  const timer = simulateProgress()

  try {
    const formData = new FormData()
    formData.append('file', file)
    if (companyCode.value) formData.append('company_code', companyCode.value)
    formData.append('doc_title', file.name.replace('.pdf', ''))

    const headers: Record<string, string> = {}
    if (API_KEY) headers['X-API-Key'] = API_KEY

    const resp = await fetch(`${API_BASE}/rag/upload`, { method: 'POST', headers, body: formData })
    const data = await resp.json()
    clearInterval(timer)
    progress.value = 100
    progressStep.value = '完成！'

    if (resp.ok) {
      uploadResult.value = { ok: true, title: data.doc_title, chunks: data.chunks }
      companyCode.value = ''
      await fetchDocuments()
    } else {
      uploadResult.value = { ok: false, error: data.detail || '上传失败' }
    }
  } catch (e: any) {
    clearInterval(timer)
    uploadResult.value = { ok: false, error: e.message || '网络错误' }
  } finally {
    setTimeout(() => { uploading.value = false; progress.value = 0 }, 1500)
  }
}
</script>

<style scoped>
.rag-page { max-width: 900px; margin: 0 auto; }
h1 { font-size: 22px; margin-bottom: 4px; }
.subtitle { color: #666; font-size: 13px; margin-bottom: 24px; }

.drop-zone {
  border: 2px dashed #ccc; border-radius: 12px; padding: 50px 20px;
  text-align: center; transition: 0.3s; background: #fafbfc;
  min-height: 180px; display: flex; align-items: center; justify-content: center;
}
.drop-zone.dragging { border-color: #4a90d9; background: #e8f0fe; }
.drop-zone.uploading { border-color: #4a90d9; background: #f0f4ff; }

.drop-icon { font-size: 48px; margin-bottom: 12px; }
.drop-content p { color: #666; margin: 4px 0; }
.hint { font-size: 12px; color: #999; }

.upload-meta { display: flex; gap: 8px; margin-top: 16px; justify-content: center; }
.code-input {
  padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px;
  font-size: 13px; width: 200px; outline: none;
}
.code-input:focus { border-color: #4a90d9; }
.select-btn {
  padding: 8px 20px; background: #4a90d9; color: #fff; border: none;
  border-radius: 6px; cursor: pointer; font-size: 13px;
}
.select-btn:hover { background: #3a7bc8; }

.progress-area { width: 100%; max-width: 500px; }
.progress-label { display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 8px; color: #333; }
.progress-bar { height: 8px; background: #e0e0e0; border-radius: 4px; overflow: hidden; }
.progress-fill { height: 100%; background: linear-gradient(90deg, #4a90d9, #6ab0f3); border-radius: 4px; transition: width 0.5s; }
.progress-step { font-size: 12px; color: #888; margin-top: 8px; }

.result-msg { padding: 10px 16px; border-radius: 8px; font-size: 13px; margin-top: 12px; }
.result-msg.success { background: #e8f5e9; color: #2e7d32; }
.result-msg.error { background: #fdecea; color: #c62828; }

.doc-header { display: flex; align-items: center; justify-content: space-between; margin-top: 32px; margin-bottom: 12px; flex-wrap: wrap; gap: 8px; }
.doc-header h2 { font-size: 18px; margin: 0; }
.doc-toolbar { display: flex; gap: 8px; align-items: center; }
.search-input {
  padding: 6px 12px; border: 1px solid #ddd; border-radius: 6px;
  font-size: 13px; width: 220px; outline: none;
}
.search-input:focus { border-color: #4a90d9; }

.doc-list { display: flex; flex-direction: column; gap: 8px; }
.doc-card {
  display: flex; align-items: center; gap: 12px; padding: 12px 16px;
  background: #fff; border: 1px solid #eee; border-radius: 8px; transition: 0.15s;
}
.doc-card:hover { border-color: #d0d0d0; }
.doc-icon { font-size: 24px; }
.doc-info { flex: 1; min-width: 0; }
.doc-title { font-size: 14px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.doc-meta { display: flex; gap: 8px; font-size: 12px; color: #888; margin-top: 4px; flex-wrap: wrap; }
.tag { background: #e8f0fe; color: #4a90d9; padding: 1px 6px; border-radius: 4px; font-size: 11px; }
.time { color: #aaa; }
.doc-status { font-size: 12px; padding: 4px 8px; border-radius: 4px; white-space: nowrap; }
.doc-status.ok { background: #e8f5e9; color: #2e7d32; }
.doc-status.fail { background: #fdecea; color: #c62828; }
.delete-btn { background: none; border: none; cursor: pointer; font-size: 16px; opacity: 0.5; transition: 0.2s; }
.delete-btn:hover { opacity: 1; }

.empty-docs { text-align: center; padding: 40px; color: #999; font-size: 14px; }
.refresh-btn { padding: 6px 12px; border: 1px solid #ddd; border-radius: 6px; background: #fff; cursor: pointer; font-size: 13px; transition: 0.2s; }
.refresh-btn:hover { border-color: #4a90d9; color: #4a90d9; }
</style>
