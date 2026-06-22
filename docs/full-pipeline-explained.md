# 🔬 金融多智能体协作系统 — 全链路流程详解

> 从用户输入一条问题到系统返回最终结果，途经的每一个环节、每一个函数调用、每一个决策分支，本文档逐一拆解说明。

---

## 目录

1. [概览：两条通道，一个入口](#1-概览两条通道一个入口)
2. [第 0 层：HTTP 请求进入 FastAPI](#2-第-0-层http-请求进入-fastapi)
3. [第 1 层：中间件拦截](#3-第-1-层中间件拦截)
4. [第 2 层：路由分发 —— `/chat` vs `/tasks`](#4-第-2-层路由分发----chat-vs-tasks)
5. [快速通道完整链路](#5-快速通道完整链路)
   - [5.1 查询预处理 (Query Preprocessing)](#51-查询预处理-query-preprocessing)
   - [5.2 意图分类 (Intent Classification)](#52-意图分类-intent-classification)
   - [5.3 闲聊分支 (Chitchat Branch)](#53-闲聊分支-chitchat-branch)
   - [5.4 综合报告分支 (Comprehensive → Async)](#54-综合报告分支-comprehensive--async)
   - [5.5 LangGraph 图执行（核心链路）](#55-langgraph-图执行核心链路)
   - [5.6 SSE 流式输出与前端渲染](#56-sse-流式输出与前端渲染)
6. [异步通道完整链路](#6-异步通道完整链路)
7. [每一步的代码位置索引](#7-每一步的代码位置索引)

---

## 1. 概览：两条通道，一个入口

整个系统只有一个 HTTP 入口（FastAPI），所有请求先经过**认证中间件**和**限流中间件**，然后根据请求路径分发：

```
浏览器/客户端
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  FastAPI (main.py)                                           │
│                                                              │
│  Request → Auth Middleware → Rate Limit Middleware → Route   │
│                                                              │
│  POST /api/v1/chat ────────→ 快速通道 (SSE 流式)              │
│  POST /api/v1/tasks ───────→ 异步通道 (Celery 后台)           │
│  GET  /api/v1/tasks/{id} ──→ 查询任务状态                     │
│  GET  /api/v1/reports/{id} ─→ 获取完成报告                    │
│  GET  /api/v1/health ──────→ 健康检查                         │
└──────────────────────────────────────────────────────────────┘
```

**核心设计哲学**：简单问题（"茅台PE多少"）走快速通道秒级返回，复杂问题（"出一份茅台综合投研报告"）走异步通道后台执行，互不阻塞。

---

## 2. 第 0 层：HTTP 请求进入 FastAPI

**代码位置**：[`backend/main.py:120`](backend/main.py#L120)

当用户在前端输入框输入"分析茅台2024Q3的盈利能力"并按下回车时，前端 `Chat.vue` 的 `sendMessage()` 函数被触发，调用 `postChat()` 函数（[`frontend/src/api/chat.ts`](frontend/src/api/chat.ts)），向 `POST /api/v1/chat` 发送一个 JSON 请求：

```json
{
  "message": "分析茅台2024Q3的盈利能力",
  "conversation_id": null,
  "attachments": []
}
```

FastAPI 的 Pydantic 模型 `ChatRequest`（[`main.py:21`](backend/main.py#L21)）自动完成请求体校验：
- `message: str` — 必填
- `conversation_id: str | None` — 可选
- `attachments: list[str]` — 可选

同时，FastAPI 的 `lifespan` 管理器在应用启动时已完成两项准备工作：
1. **端口冲突检测**：尝试 bind `127.0.0.1:8000`，如果被占用则明确报错并给出杀进程命令（测试环境下跳过）
2. **BGE-M3 模型预热**：在后台线程池中调用 `_get_embedder()` 预加载 SentenceTransformer 模型（避免首个 RAG 请求等待 5-10 秒）

---

## 3. 第 1 层：中间件拦截

FastAPI 的中间件按注册顺序（`add_middleware` 的逆序）执行，即**先进入 Auth，再进入 Rate Limit**。

### 3.1 认证中间件 (`auth.py`)

**代码位置**：[`backend/middleware/auth.py`](backend/middleware/auth.py)

```python
async def auth_middleware(request: Request, call_next):
    # Step 1: IP 白名单检查（可选功能）
    if IP_WHITELIST:                    # 从 env "IP_WHITELIST" 读取，逗号分隔
        client_ip = request.client.host
        if client_ip not in IP_WHITELIST:
            return JSONResponse(403, {"error": "ip not allowed"})

    # Step 2: 公开路径跳过认证
    if request.url.path in PUBLIC_PATHS:  # {"/api/v1/health", "/", "/docs", "/openapi.json"}
        return await call_next(request)

    # Step 3: API Key 未配置时放行（开发环境）
    if not API_KEY:                      # 从 env "API_KEY" 读取
        return await call_next(request)

    # Step 4: 校验 X-API-Key 请求头
    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        return JSONResponse(401, {"error": "invalid api key"})

    return await call_next(request)
```

**设计考量**：
- 生产环境设置 `API_KEY` 即可启用认证
- 开发环境不设或设为空，跳过认证方便本地调试
- `IP_WHITELIST` 用于绑定特定出口 IP 的场景（如公司内网代理）

### 3.2 限流中间件 (`rate_limit.py`)

**代码位置**：[`backend/middleware/rate_limit.py`](backend/middleware/rate_limit.py)

```python
async def rate_limit_middleware(request: Request, call_next):
    # Step 1: 公开路径跳过
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    # Step 2: RATE_LIMIT <= 0 时禁用限流
    if RATE_LIMIT <= 0:                  # 从 env "RATE_LIMIT" 读取，默认 60
        return await call_next(request)

    # Step 3: 构造 Redis Key
    # 有 API Key → key:{api_key}；无 API Key → ip:{client_ip}
    if api_key := request.headers.get("X-API-Key"):
        client_key = f"key:{api_key}"
    else:
        client_key = f"ip:{request.client.host}"
    redis_key = f"rate_limit:{client_key}"

    # Step 4: Redis 滑动窗口计数
    r = await get_redis()
    current = await r.incr(redis_key)      # 原子递增
    if current == 1:
        await r.expire(redis_key, 60)      # 首次请求设 60s TTL
    if current > RATE_LIMIT:               # 超过限制 → 429
        raise HTTPException(429, "rate limit exceeded")
    # Redis 不可用时 → 降级放行（不阻断正常请求）
```

**算法本质**：固定窗口计数器（60 秒窗口），而非严格的滑动窗口。`INCR` + `EXPIRE` 是 Redis 最轻量的限流实现。

**降级策略**：Redis 不可用时 `except Exception: pass` 直接放行——宁可暂时不限流也不可阻断业务。

---

## 4. 第 2 层：路由分发 —— `/chat` vs `/tasks`

通过中间件后，请求到达 FastAPI 路由处理器。

### 4.1 `/api/v1/chat` — 快速对话通道

**代码位置**：[`backend/main.py:120`](backend/main.py#L120)

这是系统的主入口，处理**除 comprehensive 以外的所有意图**。流程：

```
接收 ChatRequest
  → 生成 task_id (uuid4[:8])
  → 调用 classify_intent(message)    ← 核心：意图分类
  → 根据 intent 分三种情况处理：
      ├─ chitchat → LLM 直接回复 (SSE)
      ├─ comprehensive → 提交 Celery 异步任务
      └─ 其他 → LangGraph StateGraph 同步执行 (SSE)
```

### 4.2 `/api/v1/tasks` — 异步深度报告

**代码位置**：[`backend/main.py:230`](backend/main.py#L230)

接收 `TaskRequest`（必须含 `company_code`），直接提交 Celery 任务，立即返回 `task_id`。

---

## 5. 快速通道完整链路

以用户输入 **"分析茅台2024Q3的盈利能力"** 为例，完整追踪每一步。

### 5.1 查询预处理 (Query Preprocessing)

**代码位置**：[`backend/services/query_preprocessor.py`](backend/services/query_preprocessor.py)

**调用链**：`classify_intent()` → `preprocess_with_rag()` → 两层管道

#### 5.1.1 同步规则管道 (`preprocess()`)

5 个纯规则函数按顺序执行，毫秒级完成：

| 步骤 | 函数 | 输入 → 输出示例 | 实现细节 |
|------|------|----------------|---------|
| ① 空白归一 | `_normalize_whitespace` | `"茅台   Q3  盈利"` → `"茅台 Q3 盈利"` | `re.sub(r"\s+", " ", text).strip()` |
| ② 日期解析 | `_resolve_relative_dates` | `"去年Q3"` → `"2025Q3"` | 19 条替换规则（去年/今年/上季度/本季度等），"X月份"动态匹配最近该月 |
| ③ 别名映射 | `_normalize_stock_names` | `"茅台"` → `"贵州茅台"` | 28 个硬编码映射（猪场→网易、鹅厂→腾讯等） |
| ④ 单位标准化 | `_normalize_units` | `"50个亿"` → `"50亿"` | 4 条正则替换 |
| ⑤ 标点统一 | `_normalize_punctuation` | `"茅台：如何？"` → `"茅台:如何?"` | 10 对全角→半角映射 |

**本例输出**：`"分析茅台2024Q3的盈利能力"` → `"分析贵州茅台 2024Q3 的盈利能力"`

#### 5.1.2 异步 RAG 增强管线 (`preprocess_with_rag()`)

规则预处理完成后，进入 RAG 增强管线（仅意图分类路径走此处，其他路径走 `preprocess()`）：

```
┌─ Step 1: 同步规则预处理（同上）  → "分析贵州茅台 2024Q3 的盈利能力"
│
├─ Step 2: RAG 检索
│   └─ _retrieve_context() → 调用 pgvector 检索
│       SQL: SELECT *, 1-(embedding <=> query_vec) AS score
│            FROM documents WHERE doc_type='report' LIMIT 3
│       结果: [{doc_title, content, score}, ...]
│
├─ Step 3: 实体注入
│   └─ _inject_retrieved_entities()
│       从检索结果中提取: 股票代码(600519) + 指标名(ROE,净利率) + 报告期(2024-09-30)
│       追加到 query 末尾: "（补充信息: 600519, ROE, 净利率, 2024-09-30）"
│
└─ Step 4: 置信度门控 → LLM 改写
    └─ _should_llm_rewrite() 判断:
        检索结果为空?   → 触发改写
        top-1 score < 0.5? → 触发改写
        否则 → 直接返回注入后的 query

    若触发改写 → _llm_rewrite_query():
      model="default" (temperature=0.2, max_tokens=2048)
      超时 3 秒 (LLM_REWRITE_TIMEOUT)
      失败 → 抛出 QueryRewriteError
        (在 classify_intent 中被 catch，向用户返回友好提示)
```

**本例**：如果知识库中有茅台的研报，检索后实体注入，返回增强版 query；如果相似度高则直接返回。

---

### 5.2 意图分类 (Intent Classification)

**代码位置**：[`backend/agents/intent_classifier/classifier.py:123`](backend/agents/intent_classifier/classifier.py#L123)

`classify_intent()` 是整个系统的"分诊台"，由四层策略级联构成：

#### 5.2.1 Layer 0：RAG 查询改写（入口处调用）

```
original_message = message  # 保存原始消息（用于后续公司名校验）
message = await preprocess_with_rag(message)
# 失败时→ log warning，继续使用原始 message
```

#### 5.2.2 Layer 1：LLM 结构化分类

```python
llm = get_llm_service()
messages = [
    {"role": "system", "content": get_intent_classifier_system()},  # 从 prompts/ 加载
    *history[-MAX_HISTORY_TURNS:],  # 最近 4 轮对话历史
    {"role": "user", "content": message},
]
result = await llm.invoke("intent_classifier", messages, response_format="json_object")
```

**LLM 配置**：`temperature=0.0, max_tokens=512`（分类任务需要确定性，禁止创造性）

**System Prompt 要点**（`prompts/intent_classifier.py`）：
- 6 种意图定义及示例（chitchat / simple_query / financial_analysis / sentiment_analysis / comprehensive）
- 冲突仲裁优先级：comprehensive > sentiment > financial > simple_query > chitchat
- 股票代码解析规则（A 股 6 位、港股 5 位 0 开头、美股 1-5 位字母）
- `company_name` 必须中文全称，`company_name_en` 必须英文学名
- 日期规范化（去年 / 上季度 / 25年Q1 等映射）
- `{__TODAY__}` 占位符在加载时替换为当前日期

**LLM 返回 JSON**（以本例为例）：
```json
{
  "intent": "financial_analysis",
  "company_code": "600519",
  "company_name": "贵州茅台",
  "company_name_en": "Kweichow Moutai",
  "report_date": "2024-09-30",
  "metric_names": ["roe", "net_margin", "revenue"],
  "query_type": "",
  "query_target": ""
}
```

**JSON 提取**：从 LLM 响应中查找 `{...}` 边界，`json.loads` 解析，失败则返回 `comprehensive` 兜底。

#### 5.2.3 Layer 2：规则兜底

```python
# 窄兜底：报告类表达强制重分类
_REPORT_PATTERNS = ["出报告", "出个报告", "出份报告", "写报告", ...]
if intent != "comprehensive" and any(p in message for p in _REPORT_PATTERNS):
    intent = "comprehensive"   # "给我一份茅台的报告" 强制转 comprehensive
```

#### 5.2.4 Layer 3：实体校验与搜索兜底

**公司名校验**：
```python
if name and not _name_in_message(name, original_message):
    # LLM 返回的"贵州茅台"不在原始消息"分析茅台的盈利能力"中？
    # 检查: "茅台" in "分析茅台的盈利能力"?  → "贵州"[:2]="贵州"? No
    #       "贵州"[:3]="贵州茅"? No
    #       "茅台" 本身不在 _KNOWN_COMPANIES 中
    # → 不通过校验
    # fallback = _extract_company_from_message("分析茅台的盈利能力")
    # → 遍历 46 家已知公司: "茅台" in message? 没有"贵州茅台"整体，但...
    #   检查前缀: "贵州茅台"[:2]="贵州" in message? Yes!
    # → fallback = "贵州茅台"
    name = fallback
    code = ""   # 清空旧 code，触发搜索兜底
```

**中概股 US→HK 映射**：
```python
_DUAL_LISTED_MAP = {"BIDU":"09888", "JD":"09618", "NTES":"09999",
                    "BABA":"09988", "BILI":"09626", "NIO":"09866"}
code = _DUAL_LISTED_MAP.get(code.upper(), code)
```

**AKShare 三级搜索兜底**（LLM 未返回股票代码时）：
```python
if not code and name:
    searched = _search_stock_code(name)
    # L1: 精确匹配 name == "贵州茅台"
    # L2: 包含匹配 "贵州茅台" in stock_name，唯一时采纳
    # L3: difflib.SequenceMatcher 模糊匹配，相似度 >= 0.6
    #     且领先第二名 > 0.15 时采纳
```

#### 5.2.5 返回 IntentResult

```python
IntentResult(
    intent="financial_analysis",
    company_code="600519",
    company_name="贵州茅台",
    company_name_en="Kweichow Moutai",
    report_date="2024-09-30",
    metric_names=["roe", "net_margin", "revenue"],
    query_type="",
    query_target="",
)
```

**总体延迟**：~200ms（不含 RAG 预处理），其中 LLM 推理约 150ms，规则处理约 50ms。

---

### 5.3 闲聊分支 (Chitchat Branch)

**代码位置**：[`backend/main.py:147-183`](backend/main.py#L147)

如果 `intent == "chitchat"`，走独立快速路径，**不进入 LangGraph 图**：

```python
if intent_result.intent == "chitchat":
    # LLM 直接对话
    result = await llm.invoke("default", [
        {"role": "system", "content": CHITCHAT_SYSTEM},  # "你是一个有帮助的金融助手..."
        {"role": "user", "content": request.message},
    ])
    # SSE 返回: intent 事件 → chunk 事件 (逐行) → done 事件
```

**设计考量**：闲聊不需要任何 Agent，LLM 直接回复。如果有 LLM 错误，返回硬编码的友好提示而非系统错误。

---

### 5.4 综合报告分支 (Comprehensive → Async)

**代码位置**：[`backend/main.py:191-202`](backend/main.py#L191)

如果 `intent == "comprehensive"` 且 `company_code` 可能为空（会走 LLM+新闻兜底）：

```python
async_task_id = await TaskManager.submit(
    company_code, report_date, company_name
)
return {"task_id": async_task_id, "status": "accepted"}
```

**这里返回的是 JSON 而非 SSE 流**！前端 `chat.ts` 检测到 `content-type: application/json` 且 `status == "accepted"`，自动切换到轮询模式（每 2 秒查一次 `GET /tasks/{id}`）。

> 详细流程见 [第 6 节：异步通道完整链路](#6-异步通道完整链路)

---

### 5.5 LangGraph 图执行（核心链路）

**代码位置**：[`backend/main.py:204-227`](backend/main.py#L204) → [`backend/graph.py`](backend/graph.py)

对于 `simple_query`、`financial_analysis`、`sentiment_analysis` 三种意图，走同步 LangGraph 执行：

```python
state = make_initial_state(task_id)
state["intent"] = intent_result.intent
state["company_code"] = intent_result.company_code
# ... 其余字段填充 ...

graph = build_graph()
final_state = await graph.ainvoke(state)   # 异步执行整个 StateGraph
chat_reply = final_state.get("chat_reply", "")
# SSE 流式返回
```

#### 5.5.1 `build_graph()` — 构建状态图

**代码位置**：[`backend/graph.py:18`](backend/graph.py#L18)

```python
def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # 注册 7 个节点
    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("data_collector", data_collector_node)
    graph.add_node("financial_analyzer", financial_analyzer_node)
    graph.add_node("sentiment_analyzer", sentiment_analyzer_node)
    graph.add_node("report_generator", report_generator_node)
    graph.add_node("rewriter", rewriter_node)
    graph.add_node("output", output_node)

    # 固定边：入口 → 意图分类 → 数据收集
    graph.set_entry_point("intent_classifier")
    graph.add_edge("intent_classifier", "data_collector")

    # 条件边：数据收集后根据 intent 分发
    graph.add_conditional_edges("data_collector", route_after_collect, {
        "output": "output",
        "financial_analyzer": "financial_analyzer",
        "sentiment_analyzer": "sentiment_analyzer",
    })

    # 条件边：财务分析后
    graph.add_conditional_edges("financial_analyzer", route_after_financial, {
        "output": "output",
        "sentiment_analyzer": "sentiment_analyzer",
    })

    # 条件边：舆情分析后
    graph.add_conditional_edges("sentiment_analyzer", route_after_sentiment, {
        "output": "output",
        "report_generator": "report_generator",
    })

    # 条件边：报告生成后（反思循环入口）
    graph.add_conditional_edges("report_generator", route_after_review, {
        "rewriter": "rewriter",
        "output": "output",
    })

    # 重写后回到报告生成（反思循环）
    graph.add_edge("rewriter", "report_generator")

    # 输出后结束
    graph.add_edge("output", END)

    return graph.compile()
```

**图的结构示意**（以 financial_analysis 意图的实际路径为例）：

```
intent_classifier ──→ data_collector ──→ financial_analyzer ──→ output ──→ END
                         (route)              (route)
```

**本例 "分析贵州茅台盈利能力"（intent=financial_analysis）的路径**：
`intent_classifier → data_collector → financial_analyzer → output`

---

#### 5.5.2 节点 1：`intent_classifier_node`

**代码位置**：[`backend/agents/intent_classifier/node.py`](backend/agents/intent_classifier/node.py)

```python
async def intent_classifier_node(state: AgentState) -> AgentState:
    # 情况 1：state 中已有 intent（来自 /chat 入口的预分类结果）
    if state.get("intent") and state["intent"] != "":
        state["status"] = "running"
        return state   # ← 直接跳过，不重复分类

    # 情况 2：无 company_code（异常情况）
    if not state.get("company_code"):
        state["intent"] = "comprehensive"  # 兜底
        state["status"] = "running"
        return state

    # 情况 3：正常流程（实际不会走到，因为 /chat 入口已经 set 了 intent）
    state["status"] = "running"
    return state
```

**注意**：通过 `/chat` 入口调用的请求，`intent_classifier_node` 只是一个**占位传递节点**。真正的分类逻辑已经在 `main.py` 的 `classify_intent()` 中完成，结果直接注入 `state`。这个设计保证了 `/tasks` 异步通道也能复用同一个图。

---

#### 5.5.3 节点 2：`data_collector_node`

**代码位置**：[`backend/agents/data_collector/node.py:111`](backend/agents/data_collector/node.py#L111)

这是数据获取的核心节点，根据 `intent` 类型分三种处理：

##### 路径 A：市场行情查询（`query_type` 为 gold_price / commodity_price / exchange_rate / stock_price / index_price）

```python
if query_type in ("gold_price", "commodity_price", "exchange_rate", "stock_price", "index_price"):
    market_data = await adapter.fetch_market_data(query_type, target)
    # AKShareAdapter 根据 query_type 调用不同 API:
    #   gold_price → ak.spot_golden_benchmark_sge()
    #   exchange_rate → ak.fx_spot_quote()
    #   commodity_price → ak.futures_global_spot_em()
    #   stock_price → ak.stock_us_daily() / ak.stock_hk_daily() / ak.stock_zh_a_spot_em()
    state["raw_data"] = {"market_data": market_data, ...}
    return state   # ← 直接返回，不走后续 Agent
```

##### 路径 B：公司财务数据查询（标准路径）

```python
# 1. 确定提取的指标列表
if intent == "simple_query":
    metrics = SIMPLE_QUERY_METRICS    # ["revenue", "net_profit"] — 最少指标
else:
    metrics = DEFAULT_METRICS_FETCH   # 8 个核心指标

# 2. 计算新闻回看天数
news_lookback_days = _compute_news_lookback(date)
# 动态计算：距报告期天数 + 30 天缓冲，最少 30 天

# 3. 并行拉取数据（关键性能优化）
if intent == "comprehensive":
    # 并行 3 个异步任务
    results = await asyncio.gather(
        adapter.fetch_financials(code, date, metrics),
        adapter.fetch_news(code, days=news_lookback_days),
        adapter.fetch_documents(code, "announcement", limit=5),
        return_exceptions=True   # 单个失败不影响其他
    )
else:
    # 只需 2 个（财务数据 + 新闻）
    results = await asyncio.gather(
        adapter.fetch_financials(code, date, metrics),
        adapter.fetch_news(code, days=news_lookback_days),
        return_exceptions=True,
    )
```

**`return_exceptions=True`** 是关键设计——单个数据源异常不会让整个 `gather` 抛异常，而是在结果列表中返回 Exception 对象。

```python
# 4. 异常解包
financials, news, docs = results[0], results[1], results[2] if len(results) > 2 else []

if isinstance(financials, Exception):
    errors.append(f"财务数据拉取失败: {str(financials)}")
    financials = {}
# news, docs 同理

# 5. 按用户指定日期过滤新闻
if _target_start and _target_end:
    filtered_news = [n for n in news
        if _news_in_range(n["published_at"], _target_start, _target_end)]

# 6. 组装 raw_data
state["raw_data"] = {
    "financial_metrics": financials,   # {"net_profit": 150.5, "roe": 0.125, ...}
    "news_headlines": news,            # [{"title": "...", "summary": "...", ...}, ...]
    "doc_snippets": docs,              # [{"title": "...", "content": "..."}, ...]
    "data_sources": ["akshare"],
    "fetched_at": "2026-06-22T10:30:00",
}
```

**并行性能**：3 个数据源串行约需 6 秒，并行降至约 2 秒（max(2s, 1.5s, 1s) = 2s）。

---

#### 5.5.4 第一个路由决策：`route_after_collect`

**代码位置**：[`backend/graph_routes.py:7`](backend/graph_routes.py#L7)

```python
def route_after_collect(state: AgentState) -> str:
    intent = state.get("intent", "comprehensive")

    # 数据为空但有 intent → comprehensive 仍走完整管道
    if state.get("raw_data") is None:
        if intent == "comprehensive":
            return "financial_analyzer"  # 让下游用 LLM 知识兜底
        return "output"

    match intent:
        case "simple_query":       return "output"
        case "financial_analysis":  return "financial_analyzer"
        case "sentiment_analysis":  return "sentiment_analyzer"
        case "comprehensive":       return "financial_analyzer"
        case _:                     return "financial_analyzer"
```

**本例**：`intent == "financial_analysis"` → 路由到 `financial_analyzer` 节点。

---

#### 5.5.5 节点 3：`financial_analyzer_node`

**代码位置**：[`backend/agents/financial_analyzer/node.py:48`](backend/agents/financial_analyzer/node.py#L48)

这是财务分析的核心，包含三个子步骤：

##### Step A：数据为空时的知识库兜底

```python
if not metrics:
    # 数据源挂了 → 用 LLM 训练知识 + RAG 知识库兜底
    rag_context = await _fetch_rag_context(state)  # pgvector 检索研报
    result = await llm.invoke("financial_analyzer", [
        {"role": "system", "content": FINANCIAL_ANALYSIS_SYSTEM},
        {"role": "user", "content": f"请基于训练知识分析 {company} 的盈利能力..."},
    ])
    state["financial_analysis"] = {
        "dupont_decomposition": {"is_valid": False, "missing_metrics": ["all"]},
        "anomaly_flags": [],
        "narrative": result["content"],
        "analyst_confidence": "low",
    }
    return state
```

##### Step B：杜邦分解（确定性计算）

**代码位置**：[`backend/agents/financial_analyzer/dupont.py`](backend/agents/financial_analyzer/dupont.py)

```python
def compute_dupont(metrics: dict) -> DupontResult:
    # 1. 净利率 = 净利润 / 营收
    net_margin = net_profit / revenue  # 如 150.5亿 / 500亿 = 0.301

    # 2. 资产周转率 = 营收 / 总资产
    if total_assets and revenue:
        asset_turnover = revenue / total_assets   # 可能因 total_assets 缺失而跳过

    # 3. 权益乘数（三级推导）
    #    优先: metrics["equity_multiplier"] 已有值
    #    其次: 1 + equity_ratio (产权比率)
    #    最后: total_assets / (total_assets - total_liabilities)

    # 4. ROE = 净利率 × 资产周转率 × 权益乘数
    computed_roe = net_margin * asset_turnover * equity_multiplier

    # 5. 公式闭合校验
    deviation = abs(roe - computed_roe) / roe
    if deviation > 0.05:   # ROE_DEVIATION_TOLERANCE
        missing.append(f"ROE 公式不闭合: 传入 {roe}, 计算 {computed_roe}, 偏差 {deviation:.1%}")

    return DupontResult(
        roe=roe, net_margin=net_margin,
        asset_turnover=asset_turnover, equity_multiplier=equity_multiplier,
        is_valid=has_basic and len(missing) == 0 and not formula_mismatch,
        missing_metrics=missing,
    )
```

**关键设计**：
- 支持**部分数据缺失**：`total_assets` 缺失时跳过资产周转率，公式变为 `ROE ≈ 净利率 × 权益乘数`
- **除零保护**：`asset_turnover` 为 0 时不推导 ROE
- **公式闭合校验**：`is_valid` 需要三个因子有效 + 无缺失指标 + 偏差 ≤ 5%

##### Step C：异动检测

**代码位置**：[`backend/agents/financial_analyzer/anomaly.py:38`](backend/agents/financial_analyzer/anomaly.py#L38)

```python
async def detect_anomalies(code, current_metrics, db_session=None):
    # Tier 1: 数据库同比（生产路径，需要 MySQL session）
    # Tier 2: AKShare 历史拉取（获取上期数据做 YoY 对比）
    # Tier 3: 硬编码规则阈值兜底
```

**三层策略**：
1. **DB 查询**：取 `financial_data` 表最近 2 期数据做同比
2. **AKShare 二次拉取**：获取该公司历史数据，对比当前值
3. **规则阈值**（无历史数据时）：
   ```
   ROE  < -10%  → critical | < 0%   → warning
   净利率 < -5% → critical  | < 0%   → warning
   毛利率 < 0% → critical   | < 5%   → warning
   资产负债率 > 85% → critical | > 70% → warning
   ```

**判定标准**：
- 同比变化 > 50% → `critical`
- 同比变化 > 30% → `warning`
- 异常数 > 3 → 置信度降为 `medium`

##### Step D：LLM 生成分析评述

```python
# 数据日期不匹配时的强硬约束
if user_date and actual_date and user_date != actual_date:
    prompt = (
        f"重要约束: 用户请求 {user_date}, 但数据源仅有 {actual_date} 的数据. "
        f"你必须基于 {actual_date} 进行分析, "
        f"严禁在分析中使用 {user_date} 或 Q1/Q2/Q3 等季度描述. "
    ) + prompt

# RAG 增强
rag_context = await _fetch_rag_context(state)   # 检索相关研报
if rag_context:
    prompt += f"\n\n参考研报:\n{rag_context}"

# LLM 调用: temperature=0.3, max_tokens=2048
result = await llm.invoke("financial_analyzer", [
    {"role": "system", "content": FINANCIAL_ANALYSIS_SYSTEM},  # 200-400字，禁止季度描述
    {"role": "user", "content": prompt},
])

state["financial_analysis"] = {
    "dupont_decomposition": dupont_dict,
    "anomaly_flags": anomaly_dicts,
    "narrative": result["content"],     # LLM 生成的财务分析文本
    "analyst_confidence": confidence,   # high / medium / low
}
```

---

#### 5.5.6 第二个路由决策：`route_after_financial`

**代码位置**：[`backend/graph_routes.py:30`](backend/graph_routes.py#L30)

```python
def route_after_financial(state: AgentState) -> str:
    if intent == "financial_analysis":
        return "output"                # 快速通道到此结束
    else:
        return "sentiment_analyzer"    # comprehensive 继续
```

**本例**：`intent == "financial_analysis"` → 直接跳到 `output` 节点。

---

#### 5.5.7 节点 4：`sentiment_analyzer_node`（仅 comprehensive 或 sentiment_analysis）

**代码位置**：[`backend/agents/sentiment_analyzer/node.py:96`](backend/agents/sentiment_analyzer/node.py#L96)

**本示例（financial_analysis）不会走到这里**，但为了完整性说明：

```python
async def sentiment_analyzer_node(state):
    news_list = state["raw_data"]["news_headlines"]

    # Step 1: 无新闻 → 返回中性
    if not news_list:
        state["sentiment_result"] = {"overall_sentiment": "neutral", ...}
        return state

    # Step 2: 相关新闻过滤
    # 用公司名/代码/前 2-3 字符做多模式匹配，排除大盘综述
    _parts = [company, code, company[:2], company[:3]]
    _filtered = [n for n in news_list
        if any(p in n["title"] for p in _parts)]

    # Step 3: 去重 — 归一化标题相似度
    news_list = _deduplicate_news(news_list)
    # 替换数字→#、日期→#DATE#、金额→#亿/#万
    # difflib.SequenceMatcher 相似度 > 0.70 → 去重

    # Step 4: LLM 批量情感分析
    news_texts = [f"- {n['title']} | {n['summary'][:100]}" for n in news_list[:30]]
    result = await llm.invoke("sentiment_analyzer", [
        {"role": "system", "content": SENTIMENT_ANALYSIS_SYSTEM},
        {"role": "user", "content": user_prompt},
    ], response_format="json_object")

    # Step 5: 情感排序（按极端度）
    details.sort(key=lambda d: abs(d["score"] - 0.5), reverse=True)
```

**情感打分标准**（System Prompt 定义）：
- 0.8-1.0 → 强利好/强利空
- 0.6-0.8 → 中等影响
- 0.4-0.6 → 轻微影响

---

#### 5.5.8 节点 5：`report_generator_node`（仅 comprehensive）

**代码位置**：[`backend/agents/reviewer/report_generator.py:10`](backend/agents/reviewer/report_generator.py#L10)

**本示例不会走到这里**，但这是 comprehensive 的核心：

```python
async def report_generator_node(state):
    # Step 1: 构建重试上下文（上一轮的错误提示）
    if errors and retry_count > 0:
        retry_context = "以下数据在上次报告中与源数据不匹配，请修正：\n" + ...

    # Step 2: 清除上一轮的事实核对错误
    # 只保留非事实类错误

    # Step 3: RAG 检索研报（财务分析 + 经营风险 + 行业展望 + 投资评级）
    results = await search_rag(query, company_code=code, top_k=5)

    # Step 4: LLM 生成报告
    result = await llm.invoke("reviewer", [
        {"role": "system", "content": REPORT_GENERATION_SYSTEM},
        {"role": "user", "content": build_report_prompt(state, retry_context)},
    ])
    # 配置: temperature=0.5, max_tokens=8192
    # 输出: 800-2000 字结构化 Markdown 报告

    # Step 5: 程序化事实核对
    if source_metrics:
        fact_errors = await verify_facts(draft_report, company_code,
                                          source_metrics=source_metrics)
        if fact_errors:
            state["errors"].extend(fact_errors)
```

**报告结构**（System Prompt 强制）：
```
# 标题
## 核心摘要 (50-100字)
## 财务分析 (杜邦分解解读)
## 异动预警 (异常指标列表)
## 舆情研判 (情感分析总结)
## 风险提示 (3-5条)
## 数据来源 (AKShare / 东方财富 / 知识库)
```

**来源标注强制规则**：财务数据 `[来源: AKShare]`、新闻 `[来源: 东方财富]`、研报 `[来源: 知识库]`。

---

#### 5.5.9 事实核对 `verify_facts()`（仅 comprehensive 的报告生成后触发）

**代码位置**：[`backend/agents/reviewer/fact_checker.py:22`](backend/agents/reviewer/fact_checker.py#L22)

```python
async def verify_facts(report, company_code, db_session=None, source_metrics=None):
    errors = []
    # 4 种正则模式逐行匹配：

    # Pattern 1: "ROE为12.3%" → normalize_100 → report_value = 0.123
    (r'(ROE|ROA|净利率|毛利率|资产负债率)\s*[为=：:]?\s*(\d+\.?\d*)\s*%', 'percent', 100)

    # Pattern 2: "净利润50亿元" → direct_match → report_value = 50.0
    (r'(净利润|营收|营业总收入)\s*[为=：:]?\s*(\d+\.?\d*)\s*亿', 'billions', 1)

    # Pattern 3: "经营现金流12.3亿元" → direct_match → report_value = 12.3
    (r'(经营现金流|现金流|每股经营现金流)\s*[为=：:]?\s*(\d+\.?\d*)...', 'cashflow', 1)

    # Pattern 4: "净利率 = 0.50" (小数格式) → direct_match
    (r'(净利率|毛利率)\s*[为=：:]?\s*(\d+\.\d{2,4})\b(?!\s*%)', 'ratio', 1)

    # 三层数据源查找
    # Tier 1: DB 查 financial_data 表
    # Tier 2: source_metrics dict (本次拉取的实时数据)
    # Tier 3: 都不可用则跳过

    # 偏差计算
    deviation = abs(report_value - source_value) / abs(source_value)
    if deviation > 0.01:   # 1% 容差
        errors.append(f"{metric_cn}: 报告值 {report_value}, 源数据 {source_value}, 偏差 {deviation:.1%}")

    # 特效检测: 源数据为 0 但报告非零 → 疑似编造
    if source_value == 0 and report_value != 0:
        errors.append(f"{metric_cn}: 报告值 {report_value}, 源数据为 0（疑似编造数据）")
```

---

#### 5.5.10 反思路由：`route_after_review()`（仅 comprehensive）

**代码位置**：[`backend/agents/reviewer/router.py:9`](backend/agents/reviewer/router.py#L9)

```python
def route_after_review(state):
    errors = state.get("errors", [])
    retry = state.get("retry_count", 0)
    prev = state.get("prev_fact_errors", [])

    # 过滤出"新"错误（与上一轮不重复的）
    new_errors = [e for e in errors if e not in prev]
    state["prev_fact_errors"] = errors   # 保存本轮错误供下轮比较

    if new_errors and retry < MAX_REWRITE_RETRIES:   # 默认 3
        return "rewriter"   # → 进入重写循环
    else:
        if errors and not new_errors:
            logger.info("route_to_output_stale_errors")  # 死胡同：相同错误重复
        elif errors and retry >= MAX_REWRITE_RETRIES:
            logger.warning("route_to_output_with_errors")  # 超过最大重试
        return "output"
```

**关键机制**：`prev_fact_errors` 比对实现了"不重复修正同类错误"。如果 LLM 反复生成同一个错误数字（如编造 ROE），系统识别到本轮错误的并集与上轮完全一致后，判定为 stale 并退出循环。

---

#### 5.5.11 节点 6：`rewriter_node`（仅 comprehensive + 有错误时）

**代码位置**：[`backend/agents/reviewer/rewriter.py:16`](backend/agents/reviewer/rewriter.py#L16)

```python
async def rewriter_node(state):
    state["retry_count"] += 1   # ← 重试计数递增

    # 清除上一轮重写产生的旧错误（防止 stale 触发）
    state["errors"] = [e for e in errors if not e.startswith("报告重写失败")]

    # LLM 重写: temperature=0.5, max_tokens=8192
    result = await llm.invoke("reviewer", [
        {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
        {"role": "user", "content": f"以下报告中有数据不匹配：\n{error_block}\n## 当前报告\n{draft}"},
    ])

    # 空响应防护: 重写后内容 < 50 字则抛弃（保留原报告）
    if rewritten and len(rewritten) > 50:
        state["draft_report"] = rewritten
```

**重写完成后**：图自动回到 `report_generator` 节点（`graph.add_edge("rewriter", "report_generator")`），构成反思循环。

---

#### 5.5.12 节点 7：`output_node`

**代码位置**：[`backend/agents/output_node.py:184`](backend/agents/output_node.py#L184)

这是所有路径的终点，根据 `intent` 分 4 种输出模式：

```python
async def output_node(state):
    intent = state.get("intent", "comprehensive")

    if intent == "comprehensive":
        # 直接使用 draft_report，如有未解决错误追加警告
        state["chat_reply"] = state.get("draft_report", "")
        if errors and retry >= MAX_RETRY_ROUNDS:
            state["chat_reply"] += "\n⚠️ 自动校验未完全通过\n请人工复核上述数据。"

    elif intent == "simple_query":
        # 格式化市场行情或财务指标
        if market_data:
            state["chat_reply"] = _format_market_data(market_data)
            # 汇率: "## 汇率 USD/CNY\n- 买入价: 7.25\n- 卖出价: 7.27"
            # 金价: "## 黄金价格\n- 品种: Au99.99\n- 收盘价: 580.00 元/克"
            # 股价: "## 贵州茅台（600519）\n日期: ...\n- 收盘价: 1850.00 元"
        else:
            state["chat_reply"] = _format_simple(raw, company)
            # "## 贵州茅台\n- 净利润: 150.50\n- 营收: 500.00\n> 数据来源: AKShare"

    elif intent == "sentiment_analysis":
        state["chat_reply"] = _format_sentiment(sentiment_result)
        # "## 整体倾向: 积极 (评分: 0.8)\n... 最多展示 5 条新闻明细"

    elif intent == "financial_analysis":
        # 先展示格式化指标，再追加 LLM 分析评述
        state["chat_reply"] = _format_metrics(metrics, company)
        if financial_analysis and financial_analysis.get("narrative"):
            state["chat_reply"] += "\n" + financial_analysis["narrative"]
        # 百分比指标自动 ×100 加 %，如 roe: 0.125 → "12.5%"

    state["status"] = "done"
```

**百分比格式化** (`PERCENT_FORMAT_METRICS`)：
```python
{"roe", "roa", "gross_margin", "net_margin", "debt_ratio", "dividend_yield", "revenue_yoy"}
# 显示时自动 ×100 加百分号: 0.125 → "12.5%"
```

**新闻明细上限**：`OUTPUT_NEWS_DETAIL_LIMIT = 5`（最多展示 5 条）

---

### 5.6 SSE 流式输出与前端渲染

#### 5.6.1 后端 SSE 事件流

**代码位置**：[`backend/main.py:213-227`](backend/main.py#L213)

```python
async def event_generator():
    graph = build_graph()
    # 事件 1: intent — 告知前端本次查询的意图分类
    yield f"event: intent\ndata: {json.dumps({'intent': intent_result.intent})}\n\n"

    # 执行 LangGraph 图
    final_state = await graph.ainvoke(state)

    # 事件 2-N: chunk — 逐行推送结果文本
    chat_reply = final_state.get("chat_reply", "")
    for line in chat_reply.split("\n"):
        yield f"event: chunk\ndata: {json.dumps({'text': line + '\n'})}\n\n"

    # 事件 N+1: done — 标记流结束
    yield f"event: done\ndata: {json.dumps({'task_id': task_id})}\n\n"
```

**SSE 响应示例**：
```
event: intent
data: {"intent": "financial_analysis"}

event: chunk
data: {"text": "## 贵州茅台 关键财务指标（报告期: 2024-09-30）\n"}

event: chunk
data: {"text": "- 净资产收益率(ROE): **12.5%**\n"}

event: chunk
data: {"text": "- 净利率: **30.1%**\n"}

...

event: done
data: {"task_id": "a1b2c3d4"}
```

#### 5.6.2 前端 SSE 解析

**代码位置**：[`frontend/src/api/chat.ts:30-80`](frontend/src/api/chat.ts#L30)

```typescript
async function postChat(message, onIntent, onChunk, onDone, onError, onStreamEnd) {
    const response = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ message }),
    });

    // 检测 comprehensive 降级（JSON 响应而非 SSE）
    if (contentType.includes('application/json')) {
        const data = await response.json();
        if (data.status === 'accepted') {
            onDone(data.task_id);  // 触发轮询
        }
        return;
    }

    // 标准 SSE 流解析
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // 按行分割解析 SSE 事件
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
            if (line.startsWith('data: ')) {
                const json = JSON.parse(line.slice(6));
                if (eventType === 'intent') onIntent(json.intent);
                if (eventType === 'chunk') onChunk(json.text);
                if (eventType === 'done') onDone(json.task_id);
                if (eventType === 'error') onError(json.message);
            }
        }
    }
    onStreamEnd();
}
```

#### 5.6.3 前端渲染（Chat.vue）

**代码位置**：[`frontend/src/views/Chat.vue`](frontend/src/views/Chat.vue)

```typescript
// onChunk 回调: 逐行追加到 AI 消息气泡中
onChunk: (text) => {
    aiMsg.content += text;
    // 自动滚动到底部
    msgContainer.value.scrollTop = msgContainer.value.scrollHeight;
}

// renderMarkdown: 将 Markdown 文本渲染为安全 HTML
renderMarkdown(text) {
    return DOMPurify.sanitize(
        marked.parse(text),
        { ALLOWED_TAGS: ['p','br','strong','em','h1','h2','h3','h4','h5','h6',
                         'ul','ol','li','table','thead','tbody','tr','th','td',
                         'code','pre','blockquote','a','hr','span','div'],
          ALLOWED_ATTR: ['href','target','rel','class'] }
    );
}
```

**意图标签映射**：
```typescript
{ simple_query: "数据查询", financial_analysis: "财务分析",
  sentiment_analysis: "舆情分析", comprehensive: "综合分析" }
```

---

## 6. 异步通道完整链路

当 `intent == "comprehensive"` 时，不走 LangGraph 同步执行，而是提交到 Celery。

### 6.1 任务提交

**代码位置**：[`backend/services/task_queue/manager.py`](backend/services/task_queue/manager.py)

```python
class TaskManager:
    @staticmethod
    async def submit(company_code, report_date, company_name=""):
        task_id = str(uuid.uuid4())

        # 1. 检查 Worker 存活
        inspect = celery_app.control.inspect(timeout=2.0)
        stats = inspect.stats()
        if not stats:
            raise RuntimeError("No Celery worker available")

        # 2. 写 Redis: task:{task_id} → {"status": "pending", ...}
        r = await get_redis()
        await r.setex(f"task:{task_id}", TASK_TTL, json.dumps({...}))

        # 3. 提交 Celery 任务
        celery_app.send_task(
            "services.task_queue.celery_app.run_comprehensive_analysis",
            args=[task_id, company_code, report_date, company_name],
        )
        return task_id
```

### 6.2 Celery Worker 执行

**代码位置**：[`backend/services/task_queue/celery_app.py`](backend/services/task_queue/celery_app.py)

```python
@app.task(bind=True, max_retries=CELERY_MAX_RETRIES,   # 默认 2 次
          default_retry_delay=CELERY_RETRY_COUNTDOWN)    # 默认 10 秒
def run_comprehensive_analysis(self, task_id, company_code, report_date, company_name):
    # 1. 更新 Redis: status → "running"
    redis.set(f"task:{task_id}", json.dumps({"status": "running", ...}))

    # 2. 构建 LangGraph State + 执行全管道
    state = make_initial_state(task_id, company_code, report_date)
    state["company_name"] = company_name
    state["intent"] = "comprehensive"

    graph = build_graph()
    final_state = await graph.ainvoke(state)

    # 3. 更新 Redis: status → "done", result → draft_report
    redis.setex(f"task:{task_id}", TASK_TTL, json.dumps({
        "status": "done",
        "result": {"draft_report": final_state["draft_report"], ...},
    }))
```

### 6.3 前端轮询

```typescript
// chat.ts
async function waitForReport(taskId, onDone, onError, pollIntervalMs=2000) {
    const poll = async () => {
        const status = await getTaskStatus(taskId);
        if (status.status === 'done') {
            const reportData = await fetch(`${API_BASE}/reports/${taskId}`);
            onDone(reportData.report);
        } else if (status.status === 'failed') {
            onError(status.error);
        } else {
            setTimeout(poll, pollIntervalMs);  // 每 2 秒轮询
        }
    };
    poll();
}
```

---

## 7. 每一步的代码位置索引

| 序号 | 环节 | 文件 | 行号 |
|------|------|------|------|
| 0 | 应用启动预热 | `backend/main.py` | :32-72 |
| 1 | 认证中间件 | `backend/middleware/auth.py` | :13-33 |
| 2 | 限流中间件 | `backend/middleware/rate_limit.py` | :10-37 |
| 3 | `/chat` 路由入口 | `backend/main.py` | :120-227 |
| 4 | `/tasks` 路由入口 | `backend/main.py` | :230-238 |
| 5 | 查询预处理(同步) | `backend/services/query_preprocessor.py` | :406-431 |
| 6 | 查询预处理(RAG增强) | `backend/services/query_preprocessor.py` | :436-487 |
| 7 | LLM查询改写 | `backend/services/query_preprocessor.py` | :89-158 |
| 8 | 意图分类(主函数) | `backend/agents/intent_classifier/classifier.py` | :123-216 |
| 9 | 意图分类(三级搜索) | `backend/agents/intent_classifier/classifier.py` | :33-77 |
| 10 | 意图分类(公司名校验) | `backend/agents/intent_classifier/classifier.py` | :93-120 |
| 11 | 闲聊分支 | `backend/main.py` | :147-183 |
| 12 | 综合报告转异步 | `backend/main.py` | :191-202 |
| 13 | StateGraph 构建 | `backend/graph.py` | :18-61 |
| 14 | intent_classifier_node | `backend/agents/intent_classifier/node.py` | :7-23 |
| 15 | data_collector_node | `backend/agents/data_collector/node.py` | :111-230 |
| 16 | 路由: route_after_collect | `backend/graph_routes.py` | :7-27 |
| 17 | financial_analyzer_node | `backend/agents/financial_analyzer/node.py` | :48-139 |
| 18 | 杜邦分解计算 | `backend/agents/financial_analyzer/dupont.py` | :5-75 |
| 19 | 异动检测 | `backend/agents/financial_analyzer/anomaly.py` | :38-142 |
| 20 | 路由: route_after_financial | `backend/graph_routes.py` | :30-37 |
| 21 | sentiment_analyzer_node | `backend/agents/sentiment_analyzer/node.py` | :96-207 |
| 22 | 新闻去重 | `backend/agents/sentiment_analyzer/node.py` | :12-56 |
| 23 | 路由: route_after_sentiment | `backend/graph_routes.py` | :40-47 |
| 24 | report_generator_node | `backend/agents/reviewer/report_generator.py` | :10-101 |
| 25 | 程序化事实核对 | `backend/agents/reviewer/fact_checker.py` | :22-81 |
| 26 | 反思路由 | `backend/agents/reviewer/router.py` | :9-26 |
| 27 | 重写节点 | `backend/agents/reviewer/rewriter.py` | :16-58 |
| 28 | 输出节点 | `backend/agents/output_node.py` | :184-239 |
| 29 | LLM 服务(重试+降级+限流) | `backend/services/llm_service.py` | :55-154 |
| 30 | 熔断器 | `backend/services/circuit_breaker.py` | — |
| 31 | 任务提交 | `backend/services/task_queue/manager.py` | — |
| 32 | Celery Worker | `backend/services/task_queue/celery_app.py` | — |
| 33 | 前端 SSE 解析 | `frontend/src/api/chat.ts` | :30-80 |
| 34 | 前端轮询 | `frontend/src/api/chat.ts` | :90-120 |
| 35 | 前端渲染 | `frontend/src/views/Chat.vue` | — |

---

> 📌 **阅读建议**：配合 [面试准备文档](interview-preparation.md) 一起阅读，前者回答"为什么这样设计"，本文档回答"具体怎么实现"。两篇文档结合可以覆盖绝大多数面试问题。
