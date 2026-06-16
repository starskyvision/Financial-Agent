# Phase 8 — FastAPI + LangGraph 编排

**优先级**: P0　|　**前置**: Phase 2, 3, 4, 5, 6, 7　|　**预计工时**: 2 天

## 目标

将 5 个 Agent 节点组装为 LangGraph StateGraph，配置 4 个条件边，通过 FastAPI 暴露 `/chat` 和 `/tasks` 双路由。这是系统的"脊柱"——所有子 Agent 在此处衔接。

## 子任务

### 8.1 构建 LangGraph StateGraph

📁 `backend/graph.py`

- [ ] 使用 `from langgraph.graph import StateGraph` 创建图
- [ ] 注册 6 个节点：
  ```python
  graph.add_node("intent_classifier", intent_classifier_node)   # Phase 2
  graph.add_node("data_collector", data_collector_node)          # Phase 3
  graph.add_node("financial_analyzer", financial_analyzer_node)  # Phase 4
  graph.add_node("sentiment_analyzer", sentiment_analyzer_node)  # Phase 5
  graph.add_node("report_generator", report_generator_node)      # Phase 6.2
  graph.add_node("rewriter", rewriter_node)                      # Phase 6.4
  graph.add_node("output", output_node)                          # 输出节点（下面定义）
  ```

- [ ] 设置入口：`graph.set_entry_point("intent_classifier")`
- [ ] 配置 **4 个条件边**：

  **边 1 — 入口→数据收集（无条件）**：
  ```python
  graph.add_edge("intent_classifier", "data_collector")
  ```

  **边 2 — 数据收集→分发**（调用 `route_after_collect`）：
  ```python
  graph.add_conditional_edges("data_collector", route_after_collect, {
      "output": "output",
      "financial_analyzer": "financial_analyzer",
      "sentiment_analyzer": "sentiment_analyzer",
  })
  ```

  **边 3 — 财务分析→分发**（调用 `route_after_financial`）：
  ```python
  graph.add_conditional_edges("financial_analyzer", route_after_financial, {
      "output": "output",
      "sentiment_analyzer": "sentiment_analyzer",
  })
  ```

  **边 4 — 舆情→校验 / 反思循环**：
  ```python
  graph.add_edge("sentiment_analyzer", "report_generator")
  graph.add_conditional_edges("report_generator", route_after_review, {
      "rewriter": "rewriter",
      "output": "output",
  })
  graph.add_edge("rewriter", "report_generator")
  ```

- [ ] 编译图：`graph.compile()`

**验收**: `graph.get_graph().draw_mermaid()` 输出结构正确的 Mermaid 图

### 8.2 实现输出节点 + LLM 服务

📁 `backend/agents/output_node.py`
📁 `backend/services/llm_service.py`

**输出节点**：
- [ ] 实现 `async def output_node(state: AgentState) -> AgentState`
- [ ] 简单查询/快速通道：将 `state["raw_data"]` 格式化为自然语言回复，写入 `state["chat_reply"]`
- [ ] Comprehensive：将 `state["draft_report"]` 写入 `state["chat_reply"]`（报告即回复）
- [ ] 更新 `state["status"] = "done"`

**LLM 服务**：
- [ ] 实现 `LLMService` 单例类，封装 `openai.AsyncOpenAI` 客户端
- [ ] 支持多模型路由：`invoke(agent_name, ...)` → 按 Agent 名取配置（temperature, max_tokens）
- [ ] 主模型 DeepSeek-V3，备选 Qwen
- [ ] 内置 token bucket 限流器（可配置 RPM）
- [ ] 统一的重试策略：429/503/超时 → 指数退避（1s, 2s, 4s）
- [ ] 所有调用记录 `structlog` 日志（model, tokens_used, latency_ms）

**验收**: output_node 生成 `chat_reply` 或 `draft_report` 非空

### 8.3 实现 FastAPI 双路由

📁 `backend/main.py`

- [ ] 实现 `POST /api/v1/chat` — 快速对话通道：

  ```python
  @router.post("/api/v1/chat")
  async def chat(request: ChatRequest):
      # 1. 初始化 State（intent 待分类填入）
      # 2. 运行 LangGraph 图（非 comprehensive 同步执行）
      # 3. comprehensive → 302 重定向到 /tasks
      # 4. 返回 SSE StreamingResponse
  ```

  - SSE 事件顺序：`intent → progress(各agent) → chunk → done`

- [ ] 实现 `POST /api/v1/tasks` — 异步分析通道：
  ```python
  @router.post("/api/v1/tasks")
  async def submit_task(request: TaskRequest):
      task_id = str(uuid4())
      state = AgentState(task_id=task_id, intent="comprehensive", ...)
      run_comprehensive_analysis.delay(state)  # Celery 异步
      return {"task_id": task_id, "status": "pending"}
  ```

- [ ] 实现 `GET /api/v1/tasks/{task_id}` — 任务状态查询
- [ ] 实现 `GET /api/v1/tasks/{task_id}/stream` — SSE 进度订阅
- [ ] 实现 `GET /api/v1/reports/{task_id}` — 获取已完成报告
- [ ] 实现 `GET /api/v1/health` — 健康检查（含 Milvus/Redis/MySQL 连接状态）
- [ ] 添加 IP 频率限制中间件（`/chat` 30次/分钟，`/tasks` 5次/分钟）

**验收**: Swagger UI 中 6 个接口均可调用，`/health` 返回正常

### 8.4 集成测试 — 端到端链路

📁 `backend/tests/test_e2e.py`

- [ ] 测试 `/chat` simple_query 全链路：用户输入 → 意图分类 → 数据收集 → 输出
- [ ] 测试 `/chat` financial_analysis 链路 → 返回 SSE 流并包含杜邦分析
- [ ] 测试 `/chat` comprehensive 自动降级为异步 → 返回 task_id
- [ ] 测试 `/tasks` 提交 → 轮询 status → 最终 done
- [ ] 测试 SSE 进度流包含完整的 agent_start/agent_done/chunk/done 事件
- [ ] 测试所有条件边路由正确（4 种 intent 各走各的路径）

**验收**: `pytest tests/test_e2e.py` 全部通过

### 8.5 路由函数实现（条件边逻辑）

📁 `backend/graph_routes.py`

- [ ] 提取三个条件边函数为独立模块（从 Phase 2、6.5 整合）：
  ```python
  def route_after_collect(state: AgentState) -> str
  def route_after_financial(state: AgentState) -> str
  def route_after_review(state: AgentState) -> str
  ```
- [ ] 添加路由决策日志（`INFO` 级别，记录从哪个意图路由到哪个节点）

**验收**: 路由函数在集成测试中验证正确

---

## 产出物

- [ ] `backend/graph.py` — StateGraph 构建 + 编译
- [ ] `backend/graph_routes.py` — 条件边路由函数
- [ ] `backend/agents/output_node.py` — 输出节点
- [ ] `backend/services/llm_service.py` — LLM 调用服务
- [ ] `backend/main.py` — FastAPI 应用（含 6 个路由 + 限流中间件）
- [ ] `backend/tests/test_e2e.py` — 端到端集成测试

*关联文档: [设计规格 §2 系统架构](../superpowers/specs/2026-06-16-financial-agent-mvp-design.md#二系统架构), [设计规格 §7 条件边规则](../superpowers/specs/2026-06-16-financial-agent-mvp-design.md#七langgraph-条件边规则)*
