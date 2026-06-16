# Phase 7 — 异步任务队列

**优先级**: P1　|　**前置**: Phase 0　|　**预计工时**: 1.5 天

## 目标

基于 Celery + Redis 实现异步任务队列，将 comprehensive 分析解耦为可查询、可中断的后台任务，支持 SSE 进度推送。

## 子任务

### 7.1 Celery 应用配置

📁 `backend/services/task_queue/celery_app.py`

- [ ] 创建 Celery 应用实例
- [ ] Broker 和 Result Backend 均使用 Redis（地址从 `.env` 读取）
- [ ] 配置项：
  ```python
  broker_connection_retry_on_startup = True
  task_serializer = "json"
  task_track_started = True
  task_acks_late = True              # 任务完成后才 ACK，防止丢失
  worker_prefetch_multiplier = 1     # 公平调度
  ```
- [ ] 定义 `analyze_task` Celery 任务：
  ```python
  @celery_app.task(bind=True, max_retries=2)
  def run_comprehensive_analysis(self, task_id: str, company_code: str, report_date: str):
      # 调用 LangGraph 全管道执行
      # 将 State 变化通过 Redis pub/sub 推送
      # 结果写入 MySQL tasks 表
  ```

**验收**: Celery worker 启动无报错，Redis 连接正常

### 7.2 任务状态管理

📁 `backend/services/task_queue/manager.py`

- [ ] 实现 `TaskManager` 类：
  - `async def submit(task_id, company_code, report_date) -> str` — 提交任务，返回 task_id
  - `async def get_status(task_id) -> dict` — 查询状态（pending/running/done/failed）
  - `async def cancel(task_id) -> bool` — 中断任务
  - `async def list_tasks(page, page_size) -> list[dict]` — 分页任务列表
- [ ] Status 查询优先级：Redis 缓存 → MySQL `tasks` 表
- [ ] 中断实现：设置 Redis `task:{task_id}:cancelled` 标志，Agent 节点执行前检查
- [ ] 任务完成后写入 MySQL `tasks` 表（result JSON + 状态更新）

**验收**: submit → get_status 能追踪 pending → running → done 全流程

### 7.3 SSE 进度推送

📁 `backend/services/task_queue/sse.py`

- [ ] 实现 `async def publish_progress(task_id: str, event: dict)`：发布进度事件到 Redis pub/sub
- [ ] 实现 `async def subscribe_progress(task_id: str) -> AsyncGenerator`：订阅进度事件，返回异步生成器
- [ ] 事件类型定义：
  ```python
  {"type": "agent_start", "agent": "data_collector", "timestamp": "..."}
  {"type": "agent_done", "agent": "data_collector", "latency_ms": 430, "timestamp": "..."}
  {"type": "progress", "percent": 25, "message": "财务分析中..."}
  {"type": "chunk", "text": "贵州茅台2024Q3..."}
  {"type": "done", "task_id": "...", "total_latency_ms": 3200}
  {"type": "error", "agent": "sentiment", "message": "舆情数据获取失败"}
  ```
- [ ] 每个 Agent 节点执行前后调用 `publish_progress()`
- [ ] 前端通过 SSE 订阅 `GET /api/v1/tasks/{task_id}/stream`

**验收**: 模拟 Agent 节点发布事件 → SSE 订阅端能收到对应事件

### 7.4 编写任务队列单元测试

📁 `backend/tests/services/test_task_queue.py`

- [ ] 测试 `TaskManager.submit` → Redis 中对应 key 存在
- [ ] 测试 `get_status` 四状态流转
- [ ] 测试 `cancel` 设置取消标志
- [ ] Mock Celery task，测试 SSE 事件发布/订阅链路
- [ ] 测试任务失败时重试和错误记录

**验收**: `pytest tests/services/test_task_queue.py` 全部通过

---

## 产出物

- [ ] `backend/services/task_queue/__init__.py`
- [ ] `backend/services/task_queue/celery_app.py` — Celery 配置 + 任务定义
- [ ] `backend/services/task_queue/manager.py` — 任务状态管理
- [ ] `backend/services/task_queue/sse.py` — SSE 进度推送
- [ ] `backend/tests/services/test_task_queue.py` — 单元测试

*关联文档: [设计规格 §5 数据流](../superpowers/specs/2026-06-16-financial-agent-mvp-design.md#五数据流), [Phase 8 路由集成](phase-8-api-graph.md)*
