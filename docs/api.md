# API 文档

## 基础地址

- 开发环境：`http://localhost:8000`
- Swagger UI：`http://localhost:8000/docs`

## 接口列表

### 任务管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/tasks` | 提交分析任务 |
| GET | `/api/v1/tasks/{task_id}` | 查询任务状态 |
| DELETE | `/api/v1/tasks/{task_id}` | 中断任务 |
| GET | `/api/v1/tasks` | 任务列表（分页） |

### 报告

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/reports/{task_id}` | 获取报告详情 |
| GET | `/api/v1/reports/{task_id}/export` | 导出报告 PDF/Markdown |

### 流式推送

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/stream/{task_id}` | SSE 流式订阅任务进度 |

### 数据查询

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/companies/{code}/metrics` | 查询公司财务指标 |
| GET | `/api/v1/companies/{code}/sentiment` | 查询舆情时间序列 |

### 健康检查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 系统健康状态 |
