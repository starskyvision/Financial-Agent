const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'
const API_KEY = import.meta.env.VITE_API_KEY || ''

export async function getReport(taskId: string) {
  const headers: Record<string, string> = {}
  if (API_KEY) headers['X-API-Key'] = API_KEY
  const response = await fetch(`${API_BASE}/reports/${taskId}`, { headers })
  if (!response.ok) {
    throw new Error('报告未就绪或任务不存在')
  }
  return response.json()
}
