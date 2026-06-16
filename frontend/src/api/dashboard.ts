const API_BASE = '/api/v1'

export interface HealthStatus {
  status: string
  redis: string
  milvus?: string
  mysql?: string
}

export async function getHealth(): Promise<HealthStatus> {
  const response = await fetch(`${API_BASE}/health`)
  return response.json()
}
