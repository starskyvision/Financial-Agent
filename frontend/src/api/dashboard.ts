const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

export interface HealthStatus {
  status: string
  redis: string
  postgres: string
  version: string
  uptime_seconds?: number
}

export async function getHealth(): Promise<HealthStatus> {
  const response = await fetch(`${API_BASE}/health`)
  return response.json()
}
