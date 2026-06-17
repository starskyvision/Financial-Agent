export interface ChatEvent {
  intent?: string
  text?: string
  task_id?: string
  message?: string
  agent?: string
  status?: string
  latency_ms?: number
}

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'
const API_KEY = import.meta.env.VITE_API_KEY || ''

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (API_KEY) headers['X-API-Key'] = API_KEY
  return headers
}

export async function postChat(
  message: string,
  onIntent: (intent: string) => void,
  onChunk: (text: string) => void,
  onDone: (taskId: string) => void,
  onError: (error: string) => void,
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ message }),
  })

  // 如果是 comprehensive 降级为异步任务
  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    const data = await response.json()
    if (data.status === 'accepted') {
      onDone(data.task_id)
      return
    }
  }

  // SSE 流式读取
  const reader = response.body?.getReader()
  if (!reader) {
    onError('无法读取响应流')
    return
  }

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          // 事件类型行暂存，等待 data 行
          continue
        }
        if (line.startsWith('data: ')) {
          try {
            const json = JSON.parse(line.slice(6))
            if (json.intent) onIntent(json.intent)
            if (json.text) onChunk(json.text)
            if (json.task_id && json.intent === undefined) onDone(json.task_id)
            if (json.message) onError(json.message)
          } catch {
            // 非 JSON data 跳过
          }
        }
      }
    }
  } catch (e: any) {
    onError(e.message || '连接中断')
  }
}

export async function postTask(companyCode: string, reportDate: string = '') {
  const response = await fetch(`${API_BASE}/tasks`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ company_code: companyCode, report_date: reportDate }),
  })
  return response.json()
}

export async function getTaskStatus(taskId: string) {
  const headers: Record<string, string> = {}
  if (API_KEY) headers['X-API-Key'] = API_KEY
  const response = await fetch(`${API_BASE}/tasks/${taskId}`, { headers })
  return response.json()
}

export interface UploadResult {
  doc_id: number
  chunks: number
  doc_title: string
  company_code: string
}

export async function uploadReport(
  file: File,
  companyCode: string = '',
  docTitle: string = '',
): Promise<UploadResult> {
  const formData = new FormData()
  formData.append('file', file)
  if (companyCode) formData.append('company_code', companyCode)
  if (docTitle) formData.append('doc_title', docTitle)

  const headers: Record<string, string> = {}
  if (API_KEY) headers['X-API-Key'] = API_KEY

  const response = await fetch(`${API_BASE}/rag/upload`, {
    method: 'POST',
    headers,
    body: formData,
  })
  if (!response.ok) {
    const err = await response.json()
    throw new Error(err.detail || '上传失败')
  }
  return response.json()
}
