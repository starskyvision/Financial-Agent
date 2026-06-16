# 金融多智能体协作系统 — 设计规格

**日期**: 2026-06-16
**状态**: 已确认
**目标**: 基于 README 骨架，构建轻量、可扩展、响应迅速的金融智能 Copilot，解决传统投顾系统"信息过载"和"逻辑推理弱"两大痛点。

---

## 一、核心决策摘要

| 决策项 | 选择 | 说明 |
|--------|------|------|
| 交互模式 | A+B — 对话 Copilot + 异步报告 | /chat 快速问答 + /tasks 深度分析 |
| 数据源 | 可插拔抽象层 | Adapter 模式，MVP 默认 AKShare，预留 Wind/Tushare |
| 大模型 | 云端优先，按需下沉 | 全部走 DeepSeek/Qwen API，后续高频调用本地化 |
| 规模 | 部门级（50-500人） | 并发峰值 ~100，Redis 队列 + 限流即可 |
| MVP 范围 | 最小端到端 | 4 个 Agent 各做 1 个核心功能，快速跑通全链路 |
| 编排架构 | 混合模式 — 双通道 + 预判断 | /chat 意图路由选择性执行，/tasks 走完整反思管道 |

---

## 二、系统架构

```
┌─────────────────────────────────────────────────────┐
│                    用户层                            │
│   Chat 对话界面          │      报告 Dashboard       │
└────────┬─────────────────┴──────────────┬──────────┘
         │ POST /chat (SSE流式)           │ POST /tasks (异步)
         ▼                                ▼
┌─────────────────────────────────────────────────────┐
│               FastAPI 网关层                         │
│   /chat 快速通道          │   /tasks 异步任务通道     │
│   SSE 流式返回            │   Redis Queue + 轮询     │
└────────┬─────────────────┴──────────────┬──────────┘
         │                                │
         ▼                                ▼
┌─────────────────────────────────────────────────────┐
│              LangGraph StateGraph                    │
│                                                      │
│   ┌──────────┐                                      │
│   │ 意图分类  │ ← 入口节点（区分快/慢通道）          │
│   └────┬─────┘                                      │
│        │ 条件边分发                                  │
│   ┌────┼────────────────────────────┐               │
│   ▼    ▼            ▼               ▼               │
│ ┌──┐ ┌──────┐  ┌──────────┐  ┌──────────┐         │
│ │简│ │数据   │  │ 财务分析  │  │ 舆情解读  │         │
│ │单│ │收集   │  │ Agent    │  │ Agent    │         │
│ │查│ │Agent  │  └────┬─────┘  └────┬─────┘         │
│ │询│ └──┬───┘       │             │                │
│ └──┘   │           │             │                │
│         └───────────┼─────────────┘                │
│                     ▼                              │
│              ┌──────────────┐                       │
│              │ 校验总结 Agent │ ← 仅综合分析通道     │
│              │ 事实核对+反思  │                      │
│              └──────┬───────┘                       │
│                     │                              │
│              ┌──────▼───────┐                       │
│              │   条件边      │                       │
│              │ 矛盾→重写     │                       │
│              │ 通过→输出     │                       │
│              └──────────────┘                       │
└─────────────────────────────────────────────────────┘
         │                                │
         ▼                                ▼
┌─────────────────────────────────────────────────────┐
│                  公共服务层                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ 数据源    │  │ Milvus   │  │ Redis            │  │
│  │ 抽象层    │  │ 向量检索  │  │ 任务队列+缓存     │  │
│  │ (Adapter) │  │          │  │                  │  │
│  └─────┬────┘  └──────────┘  └──────────────────┘  │
│        │                                            │
│  ┌─────┴──────────────────────────┐                │
│  │ AKShare │ Tushare │ Wind(预留) │  ← 可插拔     │
│  └────────────────────────────────┘                │
│                                                      │
│  ┌──────────┐  ┌──────────────────┐                 │
│  │ MySQL 8  │  │ LLM API 路由     │                 │
│  │ 结构化数据│  │ DeepSeek / Qwen  │                 │
│  └──────────┘  └──────────────────┘                 │
└─────────────────────────────────────────────────────┘
```

**相比 README 的关键变化：**
- 入口增加意图分类节点，替代固定线性起点
- Agent 节点从串联变为可按需跳过的条件图
- 校验 Agent 仅在 comprehensive 路径激活
- 新增数据源抽象层（Adapter 模式）

---

## 三、Agent 组件定义

### 3.1 意图分类器（新增入口节点）

```
输入: user_message, conversation_history
输出: intent ("simple_query" | "financial_analysis" | "sentiment_analysis" | "comprehensive")
      + extracted_params {company_code, company_name, report_date, metric_names}
```

- 实现方式：Prompt + LLM 结构化输出（JSON Schema 约束），不引入额外模型
- 简单查询（"茅台PE多少"）直接路由到数据收集→输出，跳过其他 Agent
- comprehensive 意图在 /chat 通道自动转入异步任务

### 3.2 数据收集 Agent

```
输入: company_code, data_requests[]
输出: State.raw_data {financial_metrics: {}, news_headlines: [], doc_snippets: []}
```

- MVP 核心功能：拉取指定股票基础财务指标和最新公告标题
- 数据源抽象层接口：

```python
class DataSourceAdapter(Protocol):
    async def fetch_financials(code: str, date: str, metrics: list[str]) -> dict
    async def fetch_news(code: str, days: int) -> list[dict]
    async def fetch_documents(code: str, doc_type: str, limit: int) -> list[dict]
```

- MVP 默认实现：AKShareAdapter，后续可加 TushareAdapter、WindAdapter

### 3.3 财务分析 Agent

```
输入: State.raw_data
输出: State.financial_analysis {dupont_decomposition: {}, anomaly_flags: [], narrative: str}
```

- MVP 核心功能：杜邦分解（ROE = 净利率 × 资产周转率 × 权益乘数）
- 异常检测：同比变化超过 30% 的指标自动标记预警
- Function Calling Schema：每个计算函数定义严格 JSON Schema + Few-shot 示例

### 3.4 舆情解读 Agent

```
输入: State.raw_data.news_headlines
输出: State.sentiment_result {sentiment_label: str, score: float, key_topics: [], summary: str}
```

- MVP 核心功能：对新闻标题+摘要做情感三分类（积极/中性/消极）并打分
- 聚合方式：LLM 一次性输入多条新闻，要求输出结构化 JSON

### 3.5 校验总结 Agent（仅 comprehensive 通道）

```
输入: State.financial_analysis, State.sentiment_result
输出: State.draft_report, State.errors
```

- MVP 核心功能：将分析结果组装为 Markdown 报告
- 校验方式：报告中的关键数字与 raw_data 源数据逐项比对，偏差 >1% 写入 errors
- 反思循环：最多 3 轮"生成 → 校验 → 重写"，与当前 README 设计一致

---

## 四、State 设计

```python
class AgentState(TypedDict):
    # --- 任务元数据 ---
    task_id: str
    intent: str                    # simple_query | financial_analysis | sentiment_analysis | comprehensive

    # --- 用户输入 ---
    company_code: str
    company_name: str              # 从数据源自动补全
    report_date: str

    # --- 各 Agent 输出 ---
    raw_data: dict | None
    financial_analysis: dict | None
    sentiment_result: dict | None

    # --- 输出 ---
    chat_reply: str | None          # 快速通道：直接回复文本
    draft_report: str | None        # 综合分析通道：Markdown 报告

    # --- 反思控制 ---
    errors: list[str]
    retry_count: int
    status: str                    # running | done | failed
```

---

## 五、数据流

### 快速通道 /chat

```
用户消息 → 意图分类 → [路由分发]
  → simple_query:        数据收集 → chat_reply → SSE 流式返回
  → financial_analysis:  数据收集 → 财务分析 → chat_reply → SSE 返回
  → sentiment_analysis:  数据收集 → 舆情解读 → chat_reply → SSE 返回
  → comprehensive:       自动转为异步任务，返回 task_id
```

### 异步通道 /tasks

```
POST /tasks → 入 Redis 队列 → LangGraph 执行：
  数据收集 → 财务分析 → 舆情解读 → 校验总结 → [条件边]
                                              ↓errors非空 & retry<3
                                         重写节点 → 回到校验总结
                                              ↓通过
                                         draft_report 写入 MySQL tasks 表
```

**关键设计决策：** /chat 中的 comprehensive 意图自动转为异步任务，返回 task_id 供 SSE 订阅进度，避免在 HTTP 连接中长期阻塞。

---

## 六、API 设计

### 新增/变更接口

| 方法 | 路径 | 说明 | 变化 |
|------|------|------|------|
| POST | `/api/v1/chat` | 对话入口，SSE 流式返回 | **新增** |
| POST | `/api/v1/tasks` | 提交异步分析任务 | 不变，内部固定 intent=comprehensive |
| GET | `/api/v1/tasks/{task_id}` | 查询任务状态 | 不变 |
| GET | `/api/v1/tasks/{task_id}/stream` | SSE 订阅任务进度 | 路径调整为归入 tasks 下 |
| GET | `/api/v1/reports/{task_id}` | 获取报告详情 | 不变 |
| GET | `/api/v1/health` | 系统健康状态 | 不变 |

### POST /chat 请求/响应

```json
// Request
{
  "message": "分析一下贵州茅台2024Q3的盈利能力",
  "conversation_id": "conv_abc123",
  "attachments": []
}

// Response: SSE 事件流
event: intent
data: {"intent": "financial_analysis", "latency_ms": 200}

event: progress
data: {"agent": "data_collector", "status": "done", "latency_ms": 800}

event: chunk
data: {"text": "贵州茅台2024Q3 ROE为**12.3%**，同比..."}

event: done
data: {"conversation_id": "conv_abc123", "sources": [...], "total_latency_ms": 3200}
```

### 暂不纳入 MVP

- 对话历史持久化（内存会话，后续入 MySQL conversations 表）
- 报告导出 PDF（仅 Markdown 渲染）
- 多用户认证/权限
- `/api/v1/companies/{code}/metrics` 和 `/sentiment` 独立查询接口（由 /chat 覆盖）

---

## 七、LangGraph 条件边规则

### 第一条件边：意图路由（入口节点后）

所有意图先经过数据收集，再根据 intent 决定后续路径：

```python
def route_intent(state: AgentState) -> str:
    # 所有意图都先进入数据收集节点
    return "data_collector"
```

### 第二条件边：数据收集节点后

```python
def route_after_collect(state: AgentState) -> str:
    if state["intent"] == "simple_query":
        return "output"              # 直接输出 chat_reply
    elif state["intent"] == "financial_analysis":
        return "financial_analyzer"
    elif state["intent"] == "sentiment_analysis":
        return "sentiment_analyzer"
    else:  # comprehensive
        return "financial_analyzer"  # 走全管道
```

### 第三条件边：财务分析节点后（仅 comprehensive 需要舆情）

```python
def route_after_financial(state: AgentState) -> str:
    if state["intent"] == "financial_analysis":
        return "output"              # 快速通道直接输出
    else:  # comprehensive
        return "sentiment_analyzer"  # 继续走全管道
```

### 反思循环条件边（校验总结节点后）

与当前 README 一致：
- `retry_count < 3 AND errors 非空` → 路由至重写节点
- `retry_count >= 3 OR errors 为空` → 路由至输出节点

---

## 八、技术约束

### 语言与运行时

- **Python 3.11+**，全异步 I/O（httpx + asyncio）
- **前端**: Vue3 + Vite，复用 README 已有目录结构，不引入新框架

### 依赖版本（2026-06-16 锁定）

| 包 | 锁定版本 | 约束原因 |
|---|---|---|
| langgraph | >=1.2.0 | 最新稳定版，StateGraph API 核心兼容 |
| langchain | >=1.3.0 | v1.0 稳定版，18 个月无破坏性变更承诺 |
| langchain-community | >=0.4.0 | 与 LangChain 1.x 配套 |
| fastapi | >=0.115.0 | 稳定 SSE 支持 |
| pymilvus | >=2.4.0, <2.5.0 | 与 docker-compose Milvus 2.4 对齐 |
| celery[redis] | >=5.6.0 | 任务队列，5.6 修复内存泄漏 |
| redis | >=5.0.0, <=5.2.1 | **Celery 5.6 仅兼容到此范围，禁止升 8.x** |
| pydantic | >=2.7.0, <3.0.0 | LangGraph/LangChain 均依赖 v2 |
| openai | >=1.30.0 | DeepSeek/Qwen 兼容接口 |
| sse-starlette | >=2.0.0 | FastAPI SSE 流式推送 |

### 关键兼容性约束

1. **Celery ↔ Redis**: Celery 5.6 不支持 redis-py 6.x/8.x，redis 必须锁死在 5.0~5.2.1
2. **pymilvus ↔ Milvus**: pymilvus 2.4.x ↔ Milvus 2.4.x 严格对应，不可混用大版本
3. **LangGraph ↔ LangChain**: 1.x 系列同步升级，不单独升其中一个

### LLM

- DeepSeek-V3 作为主力推理模型，Qwen 作为备选降级
- 向量模型: 使用 LLM API 的 embedding 接口（无需本地模型），维度 4096

### FastAPI SSE

- 使用 `sse-starlette` 或原生 `StreamingResponse`

---

## 九、数据库表（复用 README 设计）

### MySQL

| 表 | 用途 | 变化 |
|----|------|------|
| `financial_data` | 财务数据中心 | 不变 |
| `documents` | 文档切片 | 不变 |
| `tasks` | 任务记录 | 新增 `intent` 字段，新增 `chat_reply` 字段（快速通道结果存储） |

### Milvus

- Collection `financial_docs` 不变，用于研究报告/公告的语义检索

### Redis

| Key 模式 | 用途 | 变化 |
|----------|------|------|
| `task:{task_id}` | 任务状态 | 不变 |
| `task:{task_id}:progress` | 进度 0-100 | 不变 |
| `sentiment:{code}:{date}` | 舆情时序 | 不变 |
| `conv:{conv_id}` | 对话历史（新增） | TTL 1h，仅内存 |

---

## 十、与 README 现有设计的差异总结

| 项目 | README 原设计 | 新设计 | 原因 |
|------|--------------|--------|------|
| Agent 编排 | 固定线性管道 | 条件路由 + 双通道 | 解决"信息过载"——简单问题不用走全链路 |
| 入口节点 | 数据收集直接开始 | 意图分类前置 | 支持 /chat 和 /tasks 两种交互模式 |
| 数据源 | Wind API 耦合 | Adapter 抽象层 | 降低接入门槛，Wind 作为可选实现 |
| 大模型 | Qwen2.5-14B 本地 + DeepSeek-V3 校验 | DeepSeek API 主力，后续按需下沉 | 快速启动，无需 GPU 硬件 |
| State | 扁平字段 | 增加 intent / chat_reply 字段 | 支持快速通道直接回复 |
| API | 以 /tasks 为中心 | 新增 /chat SSE 流式接口 | 支持对话式 Copilot |
