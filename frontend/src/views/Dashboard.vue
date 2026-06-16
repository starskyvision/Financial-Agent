<template>
  <div class="dashboard-container">
    <h1>系统仪表盘</h1>

    <section class="card">
      <h2>服务状态</h2>
      <div class="status-grid">
        <div class="status-item">
          <span class="dot" :class="health.redis === 'connected' ? 'green' : 'red'"></span>
          <span class="label">Redis</span>
          <span class="value">{{ health.redis }}</span>
        </div>
        <div class="status-item">
          <span class="dot" :class="health.milvus === 'connected' ? 'green' : 'red'"></span>
          <span class="label">Milvus</span>
          <span class="value">{{ health.milvus || 'not_configured' }}</span>
        </div>
        <div class="status-item">
          <span class="dot" :class="health.mysql === 'connected' ? 'green' : 'red'"></span>
          <span class="label">MySQL</span>
          <span class="value">{{ health.mysql || 'unknown' }}</span>
        </div>
        <div class="status-item">
          <span class="dot green"></span>
          <span class="label">FastAPI</span>
          <span class="value">healthy</span>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>API 端点</h2>
      <table class="endpoint-table">
        <thead>
          <tr><th>方法</th><th>路径</th><th>说明</th></tr>
        </thead>
        <tbody>
          <tr v-for="ep in endpoints" :key="ep.path">
            <td><span class="method" :class="ep.method">{{ ep.method }}</span></td>
            <td>{{ ep.path }}</td>
            <td>{{ ep.desc }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="card">
      <h2>Agent 节点</h2>
      <div class="agent-grid">
        <div v-for="agent in agents" :key="agent.name" class="agent-card">
          <div class="agent-name">{{ agent.icon }} {{ agent.name }}</div>
          <div class="agent-desc">{{ agent.desc }}</div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>技术栈</h2>
      <div class="tech-list">
        <span v-for="tech in techStack" :key="tech" class="tech-tag">{{ tech }}</span>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { getHealth } from '@/api/dashboard'

const health = ref({ status: 'loading', redis: '...' })
let timer: ReturnType<typeof setInterval> | null = null

const endpoints = [
  { method: 'POST', path: '/api/v1/chat', desc: '对话入口 (SSE 流式)' },
  { method: 'POST', path: '/api/v1/tasks', desc: '提交异步分析任务' },
  { method: 'GET', path: '/api/v1/tasks/{id}', desc: '查询任务状态' },
  { method: 'GET', path: '/api/v1/tasks/{id}/stream', desc: 'SSE 订阅任务进度' },
  { method: 'GET', path: '/api/v1/reports/{id}', desc: '获取报告详情' },
  { method: 'GET', path: '/api/v1/health', desc: '系统健康检查' },
]

const agents = [
  { icon: '🔍', name: '意图分类器', desc: '分析用户意图，驱动条件路由' },
  { icon: '📡', name: '数据收集', desc: 'AKShare / Wind 多源数据拉取' },
  { icon: '📊', name: '财务分析', desc: '杜邦分解 + 异动检测' },
  { icon: '📰', name: '舆情解读', desc: '新闻情感三分类 + 主题聚合' },
  { icon: '✅', name: '校验总结', desc: '事实核对 + 反思循环 + 报告生成' },
]

const techStack = [
  'FastAPI', 'LangGraph 1.2+', 'LangChain 1.3+', 'DeepSeek-V3',
  'Celery 5.6', 'Redis', 'MySQL 8.0', 'Milvus 2.4',
  'Vue3', 'Vite', 'TypeScript', 'AKShare',
]

onMounted(async () => {
  await refresh()
  timer = setInterval(refresh, 10000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})

async function refresh() {
  try {
    health.value = await getHealth()
  } catch {
    health.value = { status: 'error', redis: 'unreachable' }
  }
}
</script>

<style scoped>
.dashboard-container { max-width: 960px; margin: 0 auto; }
h1 { font-size: 22px; margin-bottom: 24px; }

.card { background: #fff; border-radius: 8px; padding: 20px 24px; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.05); }
.card h2 { font-size: 16px; margin-bottom: 16px; color: #333; }

.status-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.status-item { display: flex; align-items: center; gap: 8px; }
.dot { width: 10px; height: 10px; border-radius: 50%; }
.dot.green { background: #27ae60; }
.dot.red { background: #e74c3c; }
.label { font-size: 13px; color: #666; }
.value { font-size: 12px; color: #999; margin-left: auto; }

.endpoint-table { width: 100%; border-collapse: collapse; }
.endpoint-table th, .endpoint-table td { padding: 6px 12px; font-size: 13px; text-align: left; border-bottom: 1px solid #f0f0f0; }
.endpoint-table th { color: #999; font-weight: 500; }
.method { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; color: #fff; }
.method.POST { background: #27ae60; }
.method.GET { background: #4a90d9; }

.agent-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }
.agent-card { padding: 14px; border: 1px solid #eee; border-radius: 6px; }
.agent-name { font-weight: 600; font-size: 14px; margin-bottom: 6px; }
.agent-desc { font-size: 12px; color: #777; line-height: 1.5; }

.tech-list { display: flex; flex-wrap: wrap; gap: 8px; }
.tech-tag { padding: 4px 12px; background: #f0f4ff; color: #4a90d9; border-radius: 14px; font-size: 12px; }
</style>
