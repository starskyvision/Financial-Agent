const API_BASE = '/api/v1'

export async function getReport(taskId: string) {
  const response = await fetch(`${API_BASE}/reports/${taskId}`)
  if (!response.ok) {
    throw new Error('报告未就绪或任务不存在')
  }
  return response.json()
}
