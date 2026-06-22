# 🎯 金融多智能体协作系统 — 面试准备文档

> 本文档面向参加该项目面试的候选人，涵盖项目背景、技术架构、开发过程中遇到的问题及解决方案，以及超过 20 条高频面试问答对。建议在面试前通读 2-3 遍，并结合代码加深理解。

---

## 目录

1. [项目背景](#1-项目背景)
2. [系统流程](#2-系统流程)
3. [技术框架](#3-技术框架)
4. [遇到的问题及解决方案](#4-遇到的问题及解决方案)
5. [面试问答对（25 条）](#5-面试问答对)
6. [关键数字速记表](#6-关键数字速记表)

---

## 1. 项目背景

### 1.1 项目定位

**金融多智能体协作系统**是一个面向券商自营及资管团队的 AI 投研辅助工具（Copilot），核心目标不是替代研究员，而是**大幅缩短从"提出问题"到"获得结构化分析结论"的时间**。

### 1.2 解决的核心痛点

| 痛点 | 传统投顾系统的表现 | 本项目的解法 |
|------|-------------------|-------------|
| **信息过载** | 研究员日均需阅读上百份研报、公告、新闻，简单问题（如"茅台PE多少"）也要走完整查询流程 | **意图路由**：5 种意图分类，简单查询秒级响应，复杂分析才启动全链路 |
| **逻辑推理弱** | 传统工具只会罗列数据，无法像人类分析师那样关联宏观数据、财报指标与市场情绪 | **校验 Agent + 反思循环**：报告中的关键数据与数据库源表逐项比对，偏差 >1% 自动重写，最多 3 轮 |
| **幻觉问题** | LLM 生成不存在的股票代码、编造财务指标 | **多层防幻觉机制**：JSON Schema 白名单校验 + Few-shot 示例 + 程序化事实核对 + 源数据 0 值检测 |
| **长任务阻塞** | 综合投研报告生成需要几分钟，同步等待会超时 | **双通道架构**：快速通道 SSE 流式（秒级），异步通道 Celery 后台执行（分钟级） |

### 1.3 目标用户与使用场景

- **券商研究员**：日常盯盘、快速查询财务指标、生成标准化研报初稿
- **资管团队**：组合分析前的标的尽调、舆情监控、定期报告生成
- **个人投资者**（远期）：通过前端对话界面获取机构级分析能力

---

## 2. 系统流程

### 2.1 整体架构图

```
                          ┌──────────────────────────┐
                          │     Vue 3 前端 (Nginx)     │
                          │   /chat  ┊  /tasks  ┊ /rag │
                          └──────────┬───────────────┘
                                     │ HTTP + SSE
                          ┌──────────▼───────────────┐
                          │    FastAPI 网关 (8000)     │
                          │  认证中间件 ┊ 限流中间件     │
                          └──────────┬───────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                 ▼
          ┌────────────┐   ┌────────────┐   ┌────────────┐
          │  /chat SSE  │   │ /tasks      │   │  /health   │
          │  快速通道    │   │ 异步通道    │   │  健康检查   │
          └──────┬─────┘   └──────┬─────┘   └────────────┘
                 │                │
                 ▼                ▼
          ┌────────────┐   ┌────────────────────┐
          │ LangGraph   │   │  Celery Worker     │
          │ StateGraph  │   │  + Redis 任务队列   │
          │ (同步执行)   │   │  (异步执行)         │
          └──────┬─────┘   └────────┬───────────┘
                 │                  │
                 └────────┬─────────┘
                          ▼
          ┌─────────────────────────────────┐
          │        PostgreSQL 16 + pgvector  │
          │   financial_data ┊ documents    │
          │   tasks (JSONB)  ┊ 向量索引      │
          └─────────────────────────────────┘
```

### 2.2 Agent 编排流程（LangGraph StateGraph）

```
用户输入
    │
    ▼
┌──────────────────┐
│  🧭 意图分类器     │  ← LLM 调用 (DeepSeek-V3, temperature=0.0, max_tokens=512)
│  classify_intent  │     输出 5 种意图 + 实体提取 (股票代码/公司名/报告期)
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  📡 数据收集员     │  ← asyncio.gather 并行拉取：财务数据 + 新闻 + 文档
│  data_collector   │     AKShare + 熔断器保护 (3次失败/60s恢复)
└────────┬─────────┘
         │
    ┌────┴────────────────────┐
    │ 条件路由 1:              │
    │ route_after_collect()   │
    └────┬────────────────────┘
         │
    ┌────┼──────────────────────────────┐
    ▼    ▼                              ▼
┌──────┐ ┌──────────────┐  ┌──────────────────────┐
│ 输出  │ │ 💰 财务分析师  │  │ 📰 舆情分析师          │
│ 节点  │ │ fin_analyzer │  │ sentiment_analyzer   │
│      │ │ 杜邦分解+异动 │  │ 三分类情感+去重+排序   │
└──────┘ └──────┬───────┘  └──────────┬───────────┘
                │                      │
           ┌────┴────┐            ┌────┴────┐
           │ 条件路由2│            │ 条件路由3│
           └────┬────┘            └────┬────┘
                │                      │
    ┌───────────┼──────────────────────┘
    ▼           ▼
┌──────┐  ┌──────────────────────────┐
│ 输出  │  │ ✅ 报告生成 + 校验总结      │
│ 节点  │  │ report_generator         │  ← LLM 生成 800-2000 字结构化报告
└──────┘  │ + fact_checker (程序化)   │  ← 正则提取 → DB 查询 → 偏差 >1%?
          └──────────┬───────────────┘
                     │
                ┌────┴────────────┐
                │ 条件路由 4:      │
                │ route_after_    │
                │ review()        │
                └────┬────────────┘
                     │
         ┌───────────┼───────────┐
         ▼                       ▼
┌─────────────────┐    ┌──────────────┐
│ 🔄 重写节点       │    │  📤 输出节点   │
│ rewriter         │    │ output_node  │
│ retry_count++    │    │ 4种输出模式   │
│ 清除旧错误        │    │ 强制输出时     │
└────────┬────────┘    │ 标注警告       │
         │             └──────────────┘
         │ (循环回报告生成, 最多3轮)
         │
         └──────→ report_generator
```

### 2.3 双通道对比

| 维度 | 🚀 快速通道 `/chat` | 📝 异步通道 `/tasks` |
|------|-------------------|---------------------|
| **触发意图** | chitchat, simple_query, financial_analysis, sentiment_analysis | comprehensive |
| **执行方式** | 同步运行 LangGraph StateGraph，结果通过 SSE 流式推送 | Celery Worker 异步执行，结果写入 Redis，前端轮询 |
| **响应时间** | 3-15 秒（取决于调用的 Agent 数量） | 1-5 分钟 |
| **返回格式** | SSE 事件流：`intent → chunk* → done` | 轮询 `GET /tasks/{id}` → 完成后 `GET /reports/{id}` |
| **前端表现** | 逐字打字效果（`marked.js` 渲染 Markdown） | 任务状态指示器，完成后展示结构化报告 |
| **超时处理** | 无显式超时，流自然结束 | Celery `TASK_TTL=3600s`，任务 1 小时后 Redis 自动过期 |

### 2.4 反思循环机制（仅 comprehensive）

```
report_generator (LLM 生成报告)
        │
        ▼
fact_checker (程序化校验, 不依赖 LLM)
  ├─ 正则提取报告中的关键数字 (4 种模式)
  ├─ 查询 financial_data 表获取源数据
  ├─ 偏差计算: |报告值 - 源数据| / |源数据|
  └─ 收集 errors 列表
        │
        ▼
route_after_review (router.py)
  ├─ errors 为空 → output_node (✅ 通过)
  ├─ retry_count >= 3 → output_node (⚠️ 强制输出, 标记"自动校验未完全通过")
  └─ errors 非空 + 有新错误(与上一轮不同) + retry_count < 3
        │
        ▼
rewriter (LLM 重写, temperature=0.5, max_tokens=8192)
  ├─ retry_count++
  ├─ 清除上一轮旧错误 (防止 stale retry triggers)
  ├─ 注入错误上下文到 LLM prompt
  └─ 循环回 report_generator
```

**关键设计决策**：事实核对使用程序化正则而非 LLM 调用，原因：
- LLM 核对 LLM 生成的内容会引入二次幻觉风险
- 正则 + DB 查询确定性 100%，延迟毫秒级
- 降低 API 调用成本

---

## 3. 技术框架

### 3.1 技术选型及理由

| 层级 | 技术 | 版本 | 选型理由 |
|------|------|------|---------|
| **Agent 编排** | LangGraph | 1.2+ | 显式 StateGraph + 条件边，可审计、可中断、可回溯，比 CrewAI 的黑盒编排更适合金融合规要求 |
| **LLM 框架** | LangChain | 1.3+ | 与 LangGraph 同生态，提供标准化的 LLM 调用、工具定义 |
| **主力模型** | DeepSeek-V3 | — | 国产模型（合规），性价比极高（约 ¥1/百万 token），金融领域中文能力强 |
| **备选模型** | Qwen | turbo | 当 DeepSeek 不可用时自动降级（`llm_service.py` 重试第 3 次失败后切换） |
| **Web 框架** | FastAPI | 0.115+ | 原生 async/await 支持，自动生成 OpenAPI 文档，SSE 流式响应开箱即用 |
| **数据库** | PostgreSQL 16 + pgvector | pg16 | 一个库同时存业务数据 + 向量嵌入，避免维护多套存储（如 Milvus + MySQL） |
| **缓存/队列** | Redis | 7.x (redis-py≤5.2.1) | Celery 5.6 的 broker + 结果后端 + 限流计数器 + 对话缓存，一鱼多吃 |
| **任务队列** | Celery | 5.6 | 深度报告异步执行，支持重试、撤销、进度查询 |
| **向量模型** | BGE-M3 | — | 国产 Embedding 模型，1024 维，中英双语，支持稠密+稀疏混合检索 |
| **金融数据** | AKShare | 1.16+ | 开源免费，覆盖 A 股/港股/期货/黄金/汇率 |
| **前端** | Vue 3 + Vite | 3.4 / 5.2 | 轻量级，组合式 API，TypeScript 支持好 |
| **部署** | Docker Compose | v2 | 6 个服务一键编排，本地/服务器一致 |

### 3.2 关键架构模式

#### 3.2.1 Adapter 模式（数据源抽象层）

```python
# backend/services/data_sources/base.py
class DataSourceAdapter(Protocol):
    async def fetch_financials(code: str, date: str, metrics: list[str]) -> dict: ...
    async def fetch_news(code: str, days: int) -> list[dict]: ...
    async def fetch_documents(code: str, doc_type: str, limit: int) -> list[dict]: ...
    async def fetch_market_data(query_type: str, target: str) -> dict: ...
```

- 新增数据源只需实现 4 个方法，工厂函数 `create_data_source()` 根据配置自动分发
- 当前实现：AKShare（完整），Tushare/Wind（预留，抛 NotImplementedError）
- 实例缓存：`_instances` 字典复用 adapter，避免重复初始化

#### 3.2.2 黑板模式（Agent 间通信）

所有 Agent 共享一个 `AgentState` (TypedDict, `total=False`)，节点只读写自己关心的字段：

```
IntentClassifier → state["intent"], state["company_code"]...
DataCollector    → state["raw_data"]
FinancialAnalyzer → state["financial_analysis"]
SentimentAnalyzer → state["sentiment_result"]
Reviewer         → state["draft_report"], state["errors"]
OutputNode       → state["chat_reply"]
```

不需要微服务间的 RPC 调用，所有 Agent 是同一进程内的 LangGraph 节点函数。

#### 3.2.3 三态熔断器模式

```
closed ──(failures >= 5)──→ open ──(timeout 30s)──→ half_open
  ↑                        ↓                          │
  └──(success)─────────────┘          ┌──(success)────┘
                                      └──(failure)────→ open
```

- 使用 `asyncio.Lock` 保护状态转换，但实际调用在锁外执行（允许并发通过 half_open 门槛）
- LLM 服务和 AKShare 各自持有一个独立的 CircuitBreaker 实例

#### 3.2.4 三级降级链

```
正常调用 → 指数退避重试(最多3次) → 备选模型(Qwen) → 熔断器打开 → 返回错误
```

### 3.3 数据库设计

#### 3.3.1 表结构

**financial_data** — 财务指标时序数据
| 列 | 类型 | 说明 |
|---|---|---|
| id | BIGSERIAL PK | 自增主键 |
| company_code | VARCHAR(10) | 股票代码 |
| report_date | DATE | 报告期 |
| metric_name | VARCHAR(64) | 指标名（如 roe, net_margin） |
| metric_value | NUMERIC(20,4) | 指标值 |
| source | VARCHAR(32) | 数据来源，默认 'akshare' |

索引：`(company_code, report_date)` 联合索引，`(metric_name)` 单列索引

**documents** — 文档向量库
| 列 | 类型 | 说明 |
|---|---|---|
| id | BIGSERIAL PK | 自增主键 |
| company_code | VARCHAR(10) | 关联股票 |
| doc_type | VARCHAR(32) | 文档类型 |
| content | TEXT | 原始文本 |
| embedding | VECTOR(1024) | BGE-M3 向量（1024 维） |

索引：`HNSW` 向量索引（`vector_cosine_ops`），用于余弦相似度搜索

**tasks** — 异步任务记录
| 列 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(36) PK | UUID 任务 ID |
| company_code | VARCHAR(10) | 分析标的 |
| status | VARCHAR(16) | pending/running/done/failed（CHECK 约束） |
| progress | INT | 进度百分比 0-100 |
| result | JSONB | 任务结果（报告全文等） |
| error_log | TEXT | 错误日志 |

#### 3.3.2 pgvector 检索 SQL

```sql
SELECT id, company_code, doc_title, content,
       1 - (embedding <=> CAST(:query_vec AS vector)) AS score
FROM documents
WHERE company_code = :code OR doc_type = 'market'
ORDER BY embedding <=> CAST(:query_vec AS vector)
LIMIT :k
```

- `<=>` 是 pgvector 的余弦距离运算符
- `1 - distance` 转换为相似度分数（越大越相关）

### 3.4 LLM 调用配置

| Agent | Temperature | Max Tokens | 设计考量 |
|-------|------------|------------|---------|
| intent_classifier | 0.0 | 512 | 分类任务需确定性输出，禁止创造性 |
| financial_analyzer | 0.3 | 2,048 | 需要一定灵活性解释财务现象 |
| sentiment_analyzer | 0.3 | 2,048 | 情感判断需适度主观 |
| reviewer | 0.5 | 8,192 | 报告生成需要最大的创造性空间和输出长度 |
| default | 0.2 | 2,048 | 通用默认配置 |

---

## 4. 遇到的问题及解决方案

### 问题 1：LLM 生成不存在的股票代码（幻觉）

**现象**：用户在对话中说"分析一下茅台"，LLM 有时返回 `company_code: "600519"`（正确），有时返回 `"600000"`（浦发银行）或完全虚构的代码。

**解决方案（4 层防御）**：
1. **Prompt 层**：在 intent_classifier system prompt 中嵌入 `_KNOWN_COMPANIES`（46 家知名公司硬编码映射），并要求 company_code 必须在原始消息中有迹可循
2. **规则层**：`company_name in original_message` 校验，LLM 返回的公司名不在用户消息中的不采纳
3. **搜索兜底层**：三级 AKShare 搜索策略：
   - L1 精确匹配：`df['name'] == company_name`
   - L2 包含匹配：子串匹配，唯一时采纳
   - L3 模糊匹配：`difflib.SequenceMatcher` 相似度 ≥ 0.6，且领先第二名 > 0.15
4. **RAG 增强**：查询预处理器 `preprocess_with_rag()` 在 LLM 分类前通过向量检索自动补全股票代码，置信度 < 0.5 时触发 LLM 改写

**效果**：股票代码识别准确率从 ~85% 提升到 >95%

---

### 问题 2：杜邦公式 ROE 不闭合

**现象**：`ROE ≠ 净利率 × 资产周转率 × 权益乘数`，Three 因子乘积与直接获取的 ROE 值偏差超过 20%。

**根因**：
- AKShare 返回的各指标精度不一致（有的是 4 位小数，有的 2 位）
- 资产周转率 = 营收 / 总资产，但 total_assets 数据可能缺失

**解决方案**：
1. 引入 `ROE_DEVIATION_TOLERANCE = 0.05`（5% 容差），偏差在 5% 以内视为公式闭合
2. 部分缺失数据处理：total_assets 缺失时跳过资产周转率计算，使用公式 `ROE ≈ 净利率 × 权益乘数`（近似推导），标记 `missing_metrics: ["asset_turnover"]`
3. 除零保护：资产周转率为 0 时不能推导 ROE，标记 `is_valid: false`
4. 一致性校验：传入 ROE 与计算 ROE 偏差 > 5% 单独在报告中标注

---

### 问题 3：情感分析中重复新闻污染

**现象**：同一事件被多家媒体转载，导致舆情分析结果被少数热点事件主导。例如某公司发布财报后，20 家媒体同时报道，如果不做去重，情感分布会严重失真。

**解决方案（基于归一化的语义去重）**：
1. **标题归一化**：替换数字 → `#`，日期 → `#DATE#`，金额 → `#亿`/`#万`，百分比 → `#%`
   ```python
   title = re.sub(r'\d+\.?\d*亿', '#亿', title)
   title = re.sub(r'\d{4}-\d{2}-\d{2}', '#DATE#', title)
   title = re.sub(r'\d+\.?\d*%', '#%', title)
   ```
2. **相似度计算**：`difflib.SequenceMatcher` 比较归一化后的标题对
3. **去重阈值**：相似度 > 0.70 视为重复，保留首次出现的新闻
4. **排序优先级**：按情感极端度排序（强利好/利空优先，中性靠后）

**效果**：新闻去重率约 30-50%，情感分析结果更均衡。

---

### 问题 4：Celery Worker 多实例冲突

**现象**：开发环境中多次重启后出现 `DuplicateNodenameWarning`，多个 celery worker 进程残留，综合任务卡在 pending 状态不动。

**根因**：Windows 上 Celery 默认使用主机名作为节点名，多个 worker 实例同名导致冲突。

**解决方案**：
1. **PID 文件锁**（`celery_app.py`）：启动时检查 `.celery_worker.pid`，发现旧进程则 kill
   - Unix：`os.kill(pid, 0)` 检查进程存活
   - Windows：`ctypes.windll.kernel32.OpenProcess()` 检查进程
2. **唯一节点名**：`celery -A ... worker -n worker1@%COMPUTERNAME%`
3. **开发环境用 solo 池**：`-P solo` 单进程模式，避免 prefork 在 Windows 上的兼容性问题
4. **启动脚本**（`run_services.py`）：`--kill` 参数先清理 `taskkill /F /IM celery.exe`，等待 2 秒后启动

---

### 问题 5：Redis 版本兼容性踩坑

**现象**：某次依赖更新后，Celery Worker 无法连接 Redis，报 `AUTH <password> called without any password configured` 错误。

**根因**：`redis-py` 6.x 改变了连接参数的处理方式，不向后兼容。而 Celery 5.6 要求 `redis-py <= 5.2.1`，更高版本会导致 broker 连接失败。

**解决方案**：
1. 在 `requirements.txt` 中锁定版本：`redis>=5.0.0,<=5.2.1`
2. 在 CLAUDE.md 和 README 中明确标注"禁止升 Redis 8.x，Celery 不兼容"
3. CI pipeline 中添加版本一致性检查步骤

---

### 问题 6：综合报告请求 HTTP 超时

**现象**：早期版本所有请求都走 `/chat` SSE，compresive 意图需要等 2-3 分钟才能生成完整报告，Nginx 默认 60s 超时会截断连接。

**解决方案（双通道架构的核心动机）**：
1. **快速通道**：`/chat` 只处理秒级完成的意图（chitchat, simple_query, financial_analysis, sentiment_analysis）
2. **异步通道**：compresive 意图立即返回 `{"task_id": "...", "status": "accepted"}`，前端切换到轮询模式
3. **前端智能切换**：`chat.ts` 中检测 SSE 响应 `content-type: application/json` + `status: accepted` 时，自动调用 `waitForReport(taskId)` 轮询，每 2 秒一次
4. **进度可见**：`task:{id}:progress` Redis key 记录进度，前端可以展示"数据收集中... 财务分析中..."

---

### 问题 7：模糊查询无法定位公司

**现象**：用户输入"猪场最近怎么样"，系统无法识别"猪场"指网易。类似问题还包括"鹅厂"（腾讯）、"猫厂"（阿里巴巴）等网络别名。

**解决方案**：
1. **规则别名映射**（`query_preprocessor.py`）：硬编码 28 个常见别名 `{"猪场": "网易", "鹅厂": "腾讯控股", "猫厂": "阿里巴巴", ...}`
2. **RAG 实体注入**：向量检索匹配到的公司名注入到改写后的 query 中
3. **意图分类 Prompt 强化**：system prompt 中加入公司别名解析规则（"猪场/鹅厂/猫厂 → 正式名称"）
4. **扩展性设计**：别名映射通过常量定义，方便新增，后续规划接入外部实体识别 API

---

### 问题 8：财务数据多市场差异处理

**现象**：A 股、港股、美股的 AKShare API 完全不同，返回的列名、数值单位也各不相同：
- A 股：`stock_financial_abstract_ths`，中文列名，净利润单位亿元
- 港股：`stock_financial_hk_analysis_indicator_em`，英文列名，百分比为原始值（21.13 → 需 /100），金额为原始值（751766000000 → 需 /1e8）
- 美股：AKShare 不支持财务数据 API，返回空字典

**解决方案**：
1. **独立的列映射表**：`A_SHARE_COLUMN_MAP`（中→英）和 `HK_COLUMN_MAP`（英→内）
2. **独立的单位转换逻辑**：
   - A 股：`s.replace("亿", "")` → 直接转 float
   - 港股：`BILLION_METRICS` 集合内的指标 `/1e8`，百分比指标 `/100`
3. **独立的最佳行查找**：`_find_best_row()` 查找最近但不晚于目标日期的数据行
4. **美股优雅降级**：返回空字典 `{}`，下游节点通过 `missing_metrics` 感知

---

### 问题 9：BGE-M3 模型加载慢导致首个请求超时

**现象**：首个包含 RAG 的请求需要等待 5-10 秒加载 BGE-M3 模型（SentenceTransformer），用户体验差。

**解决方案**：
1. **应用启动时预热**：`main.py` 的 `lifespan` 中通过 `run_in_executor` 在后台线程预加载 BGE-M3
2. **Lazy init + 单例**：`_get_embedder()` 使用模块级变量缓存，首次调用后不再重复加载
3. **维度校验**：启动时比对模型实际输出维度与预期 `EMBEDDING_DIM=1024`，不匹配时打 warning（不会阻断）

---

### 问题 10：Port 冲突和进程残留

**现象**：开发过程中频繁重启，8000 端口被旧进程占用，新进程无法启动。

**解决方案**：
1. **启动时端口绑定检测**：`main.py` lifespan 中尝试 bind 127.0.0.1:8000，失败则明确报错并提示 `taskkill /F /IM python.exe`
2. **跳过测试环境**：`PYTEST_CURRENT_TEST` 环境变量存在时跳过检测
3. **启动脚本**：`run_services.py --kill` 按端口 kill（`Get-NetTCPConnection` / `lsof -ti :8000`）
4. **Graceful shutdown**：关闭时 dispose DB engine + close Redis 连接

---

## 5. 面试问答对

### 基础架构类

#### Q1：请简要介绍这个项目

**参考答案**：
这是一个基于 LangGraph 的金融投研多智能体协作系统，面向券商自营和资管团队。核心架构是**"意图分类 + 条件路由 + 反思循环"**。

系统有 5 个专职 Agent（意图分类、数据收集、财务分析、舆情解读、校验总结），通过 LangGraph StateGraph 编排。提供双通道交互——快速对话（`/chat` SSE 流式，秒级响应）和深度报告（`/tasks` 异步，分钟级出报告）。

核心技术栈：FastAPI + LangGraph + DeepSeek-V3 + PostgreSQL/pgvector + Redis + Celery + AKShare + Vue 3。

我最满意的设计是**程序化事实核对 + 反思循环**——报告中的数据不靠 LLM 自我检查，而是用正则提取后直接查数据库比对，偏差 >1% 就自动重写，最多 3 轮。这解决了 LLM "自己写的自己查不出来"的幻觉问题。

---

#### Q2：为什么选择 LangGraph 而不是 CrewAI 或 AutoGen？

**参考答案**：
三个核心原因：

1. **可审计性（金融合规要求）**：LangGraph 的 StateGraph 是显式状态机，每个节点的输入/输出都是 TypedDict，可以随时查看和回溯。CrewAI 的 Agent 编排是黑盒的，金融场景下这是硬伤。

2. **条件边路由**：我们需要根据意图按需调度 Agent（简单查询不走全链路），LangGraph 的 `add_conditional_edges` 天然支持，而 CrewAI 是顺序执行。

3. **中断与恢复**：LangGraph 支持 `checkpointer` 在任意节点中断和恢复，这对异步任务（compresive 可能要跑几分钟）很重要。

另外，LangGraph 1.2+ 与 LangChain 生态无缝集成，我们的 LLM 调用、工具定义都基于 LangChain。

---

#### Q3：系统的 5 个 Agent 是微服务吗？它们如何通信？

**参考答案**：
**不是微服务**。所有 Agent 是同一 FastAPI 进程内的 LangGraph 节点函数（async Python 函数），通过**共享的 TypedDict State（黑板模式）**通信。

每个节点只读写自己关心的字段：
- IntentClassifier → `state["intent"]`
- DataCollector → `state["raw_data"]`
- FinancialAnalyzer → `state["financial_analysis"]`
- Reviewer → `state["draft_report"]`, `state["errors"]`

这避免了微服务间的 RPC 开销和复杂性。Agent 之间不需要网络调用，数据通过内存传递。这是一个架构取舍——放弃了独立部署的灵活性，换来了低延迟和调试简便。

---

#### Q4：双通道设计的核心考虑是什么？

**参考答案**：
双通道设计源自一个实际教训——早期版本所有请求都走 `/chat` SSE 流式返回，但 compresive 意图需要 2-3 分钟生成完整报告，Nginx 的 60s 代理超时会截断连接。

解决方案是将请求按**意图**分成两类：
- **秒级请求**（闲聊/简单查询/财务分析/舆情分析）：走快速通道，同步执行 LangGraph，SSE 流式输出
- **分钟级请求**（综合深度报告）：走异步通道，立即返回 `task_id`，Celery 后台执行，前端轮询结果

前端 `chat.ts` 会自动检测：如果 SSE 返回 `{"status": "accepted"}` 而非流式数据，就自动切换到轮询模式（每 2 秒轮询任务状态）。

---

#### Q5：系统如何处理 LLM 调用失败？

**参考答案**：
三层防护：

1. **指数退避重试**（`llm_service.py`）：调用失败后等待 `2^attempt` 秒重试，最多 3 次（`LLM_MAX_RETRIES=3`）

2. **模型降级**（Qwen 备胎）：第 3 次重试失败后，自动切换到 Qwen API（需配置 `QWEN_API_KEY` 和 `QWEN_API_BASE`）

3. **熔断器**：5 次失败后熔断器打开，30 秒内所有请求直接返回错误而不实际调用（防止雪崩）。30 秒后进入 half_open 尝试恢复。

此外，还有限流器（Token Bucket，30 次/分钟）避免超出 API 配额。

---

### Agent 设计类

#### Q6：意图分类器如何工作？准确率如何？

**参考答案**：
意图分类器是三阶段流水线：

1. **预处理阶段**：查询预处理器做规则清洗（空白归一化、日期解析、单位标准化、别名映射），然后通过 RAG 检索增强查询（实体注入、低置信度时 LLM 改写）

2. **LLM 分类阶段**：DeepSeek-V3 + 结构化 System Prompt（temperature=0.0 保证确定性），输出 JSON 格式的意图分类结果：`{"intent": "financial_analysis", "company_code": "600519", ...}`

3. **规则兜底阶段**：
   - 股票代码 3 级搜索（精确 → 包含 → 模糊，最低相似度 0.6）
   - 公司名校验（LLM 返回的名称必须在用户消息中有迹可循）
   - `"一份...报告"` 模式强制归类为 comprehensive

分类延迟约 200ms（不含 RAG 预处理），准确率 >95%。分类结果缓存在 Redis `conv:{conversation_id}` 中（TTL 1 小时），同一对话中重复分类直接命中缓存。

---

#### Q7：杜邦分解的具体实现逻辑是什么？

**参考答案**：
杜邦分解的核心公式是 **ROE = 净利率 × 资产周转率 × 权益乘数**。

具体实现（`dupont.py`）：

```python
net_margin = net_profit / revenue          # 净利率
asset_turnover = revenue / total_assets    # 资产周转率
equity_multiplier = total_assets / total_equity  # 权益乘数
# 或从产权比率推导: 1 + debt_to_equity_ratio
roe_calculated = net_margin * asset_turnover * equity_multiplier
```

健壮性设计：
- **部分数据缺失处理**：`total_assets` 缺失时跳过资产周转率，用 `ROE ≈ 净利率 × 权益乘数` 近似，标记 `missing_metrics`
- **除零保护**：资产周转率为 0 时不推导 ROE
- **公式闭合校验**：`|ROE_actual - ROE_calculated| / ROE_actual > 5%` 时标记为不闭合
- **三级权益乘数推导**：优先使用已有值 → 从产权比率推导 → 从总资产/总负债计算

---

#### Q8：情感分析如何做去重？为什么不用 embedding 做语义去重？

**参考答案**：
我们使用了**基于归一化的标题相似度去重**：

1. 用正则将数字/日期/金额/百分比替换为占位符（如 `82.43亿 → #亿`，`2026-06-09 → #DATE#`）
2. 用 `difflib.SequenceMatcher` 计算归一化后的标题相似度
3. 相似度 > 70% 视为重复

**为什么不用 embedding 做语义去重**：
- BGE-M3 推理每次需要 100-200ms，30 条新闻两两比较需要 435 次推理，太慢
- 金融新闻标题结构固定（"XX公司发布2025年报：净利润同比增长30%"），归一化后的字符串相似度已经足够准确
- 正则归一化是毫秒级的，30 条新闻全部比完不到 10ms

这是一个"够用就好"的工程决策——在性能和准确率之间选择了更实用的方案。

---

#### Q9：反思循环如何避免无限重写？

**参考答案**：
三重保险防止死循环：

1. **硬性次数限制**：`MAX_RETRY_ROUNDS = 3`（可通过 `MAX_RETRY_ROUNDS` 环境变量配置），retry_count >= 3 时强制走 output_node

2. **新错误检测**（`prev_fact_errors`）：仅当本轮错误与上轮不同时才触发重写。如果 LLM 重复犯同样的错误（如编造同一个数字），系统会识别出"没有新错误"并退出循环

3. **事实核对是确定性的**：用正则 + DB 查询而非 LLM 做校验，避免了"LLM 检查 LLM → 二次幻觉 → 再次触发重写"的循环

强制输出时会在报告中标注"⚠️ 自动校验未完全通过"。

---

#### Q10：程序化事实核对具体怎么实现？

**参考答案**：
核心思路是**用确定性代码而非 LLM 做校验**（`fact_checker.py`）：

**第一步：正则提取报告中的数字**（4 种模式）
```python
# 百分比指标: "ROE为12.5%" → (ROE, 0.125)
(r'(ROE|ROA|净利率|毛利率|资产负债率)\s*[为=：:]?\s*(\d+\.?\d*)\s*%', normalize_100)

# 亿元指标: "净利润为150.5亿元" → (净利润, 150.5)
(r'(净利润|营收|营业总收入)\s*[为=：:]?\s*(\d+\.?\d*)\s*亿', direct_match)

# 现金流: "经营现金流为50.2" → (经营现金流, 50.2)
(r'(经营现金流|现金流|每股经营现金流)\s*[为=：:]?\s*(\d+\.?\d*)', direct_match)

# 小数格式: "净利率为0.15" → (净利率, 0.15)
(r'(净利率|毛利率)\s*[为=：:]?\s*(\d+\.\d{2,4})\b(?!\s*%)', direct_match)
```

**第二步：查数据库获取源数据**
三层查找：`financial_data` 表 → `source_metrics` dict → 空列表

**第三步：偏差计算与判定**
```python
deviation = abs(report_value - source_value) / abs(source_value)
if deviation > FACT_CHECK_DEVIATION_TOLERANCE (0.01):  # 1%
    errors.append(f"{metric}: 报告值={report_value}, 源数据={source_value}, 偏差={deviation:.1%}")
```

**防幻觉特效检测**：源数据为 0 但报告值非零时，标记"疑似编造数据"。

---

### 工程实践类

#### Q11：为什么从 Milvus 迁移到 pgvector？

**参考答案**：
最初的设计方案使用 Milvus 2.4 + MySQL 8.0 的组合，后来统一迁移到 PostgreSQL 16 + pgvector。原因：

1. **运维复杂度**：Milvus 依赖 etcd + MinIO，总共需要维护 5 个容器（etcd + minio + milvus + mysql + redis）。pgvector 只需在现有的 PostgreSQL 上加一个扩展，Docker 服务数从 7 个降到 6 个。

2. **事务一致性**：业务数据和向量嵌入在同一个数据库中，可以用 SQL 事务保证一致性。Milvus + MySQL 是异构存储，无法跨库事务。

3. **MVP 阶段够用**：pgvector 的 HNSW 索引在百万级向量以内的性能与 Milvus 差距不大（两者都基于 HNSW 算法），而我们 MVP 阶段的文档量远不到百万级。

4. **SQL 灵活性**：可以用 `WHERE company_code = ? AND doc_type = ?` 做过滤后再向量搜索，比 Milvus 的标量过滤更直观。

这个决策体现了 MVP 阶段的"减法思维"——用最简单可靠的方案满足需求，而不是过度设计。

---

#### Q12：为什么 Celery 的 `task_acks_late=True` 和 `worker_prefetch_multiplier=1`？

**参考答案**：
这两个配置组合是为了实现**至少一次（at-least-once）任务执行语义**和**公平调度**：

- **`task_acks_late=True`**：Worker 在任务执行完成后才发送 ACK（确认），而不是取到任务就确认。如果 Worker 在执行中崩溃，任务会自动重新分配给其他 Worker。代价是可能有重复执行，但我们综合报告是幂等的（覆盖写 Redis/DB）。

- **`worker_prefetch_multiplier=1`**：每个 Worker 一次只预取 1 个任务。防止某个 Worker 囤积大量任务而其他 Worker 空闲（"任务倾斜"问题）。我们的综合报告任务耗时差异大（1-5 分钟），不限制预取会导致调度不均。

---

#### Q13：项目中的异步 I/O 实践有哪些？

**参考答案**：
全链路异步设计，没有同步阻塞：

1. **FastAPI async handlers**：所有路由处理函数都是 `async def`
2. **`asyncio.gather` 并行数据拉取**（`data_collector/node.py`）：
   ```python
   financials, news, docs = await asyncio.gather(
       adapter.fetch_financials(code, date, metrics),
       adapter.fetch_news(code, days),
       adapter.fetch_documents(code, "research", 5),
   )
   ```
   三个数据源并行拉取，总耗时 ≈ max(单次耗时) 而非 sum

3. **异步数据库驱动**：`asyncpg` 而非 `psycopg2`，URL 自动转换 `postgresql://` → `postgresql+asyncpg://`

4. **异步 Redis**：`redis.asyncio` 客户端，非阻塞的 INCR/PING/GET/SET

5. **后台线程处理 CPU 密集任务**：BGE-M3 模型加载（SentenceTransformer）通过 `loop.run_in_executor(None, _warm_embedder)` 在线程池执行

---

#### Q14：如何做 API 安全防护？

**参考答案**：
三层防护 + MVP 阶段务实的取舍：

1. **认证中间件**（`auth.py`）：
   - `X-API-Key` 头校验
   - IP 白名单（可选，`IP_WHITELIST` 环境变量）
   - 公开路径白名单：`/health`, `/docs`, `/openapi.json`, `/`

2. **限流中间件**（`rate_limit.py`）：
   - Redis 滑动窗口算法，`INCR + EXPIRE 60`
   - 默认 60 次/分钟，可按 API Key 或 IP 分别限流
   - Redis 不可用时**降级放行**（不阻断正常请求）

3. **输入验证**：
   - Pydantic 模型自动验证请求体（`ChatRequest.message` 不受长度限制但下游截断）
   - SQLAlchemy 参数化查询防注入
   - `DOMPurify.sanitize()` 前端防 XSS

MVP 阶段没有做 JWT/OAuth2（我们只有一种用户角色），注释里标注了"真正的认证需要服务端 JWT"作为后续优化方向。

---

#### Q15：项目中的熔断器（Circuit Breaker）是怎么实现的？

**参考答案**：
实现了标准的三态熔断器（`circuit_breaker.py`）：

```
CLOSED (正常) ──失败>=5次──▶ OPEN (熔断, 直接拒绝)
                              │
                         等待30秒
                              │
                              ▼
                        HALF_OPEN (探测)
                        ├─成功→ CLOSED
                        └─失败→ OPEN
```

**并发安全设计**：
- 使用 `asyncio.Lock` 保护状态转换，但**实际调用在锁外执行**
- 这样做的目的是允许并发请求通过 half_open 门槛（否则探测期间只有一个请求能通过，恢复太慢）

**使用场景**：
- LLM 服务有一个独立的 CircuitBreaker（阈值 3，恢复 30s）
- AKShare 数据源有另一个独立的 CircuitBreaker（阈值 3，恢复 60s）

---

### 数据与算法类

#### Q16：如何处理 A 股、港股、美股的数据差异？

**参考答案**（`akshare_adapter.py` 核心逻辑）：

| 维度 | A 股 | 港股 | 美股 |
|------|------|------|------|
| **API** | `stock_financial_abstract_ths` | `stock_financial_hk_analysis_indicator_em` | 无财务数据 API |
| **列名** | 中文（"净利润"→net_profit） | 英文（缩写，需映射） | — |
| **金额单位** | 亿元（直接 parse） | 元（÷1e8 转换） | — |
| **百分比** | 百分比（21.13→0.2113） | 百分比（21.13→0.2113） | — |
| **股票代码** | 6 位数字 | 5 位，0 开头 | 1-5 位字母 |

**统一内部表示**：
- 所有金额单位统一为**亿元**
- 所有比率统一为**0-1 的小数**（非百分比）
- 返回统一 dict 格式：`{"net_profit": 150.5, "roe": 0.125, ...}`

**美股降级策略**：返回 `{}` 空字典，下游通过 `missing_metrics` 感知，使用 LLM 知识兜底。

---

#### Q17：RAG 检索的具体流程是什么？

**参考答案**：
RAG 系统包含 3 个核心组件：

1. **文档切块器**（`chunker.py`）：
   - 优先段落边界切分
   - 超长段落用滑动窗口拆分：`chunk_size=500` 字符，`overlap=50`
   - 保留原文 + 中文翻译双份存储

2. **嵌入器**（`embedder.py`）：
   - BGE-M3（SentenceTransformer），1024 维，L2 归一化
   - CPU 运行（可配置 CUDA），懒加载单例
   - 启动时维度校验

3. **检索器**（`retriever.py`）：
   ```sql
   SELECT *, 1 - (embedding <=> CAST(:query_vec AS vector)) AS score
   FROM documents
   WHERE company_code = :code OR doc_type = 'market'
   ORDER BY embedding <=> CAST(:query_vec AS vector)
   LIMIT 5
   ```
   - `<=>` 是 pgvector 余弦距离算符
   - `1 - distance` 转为相似度（越大越相关）
   - 过滤条件：目标公司的文档 + 全市场通用文档

4. **定时入库**（`tasks.py`）：Celery Beat 每日凌晨 2:00 从东方财富拉取研报，自动入库前 50 条。

---

#### Q18：查询预处理器做了什么？为什么需要它？

**参考答案**：
查询预处理器（`query_preprocessor.py`）是一个**零延迟同步管道 + 可选异步 RAG 增强**的组合，解决用户输入不规范的问题。

**同步管道**（5 步，毫秒级）：

| 步骤 | 例子 |
|------|------|
| 空白归一化 | "茅台    PE  多少" → "茅台 PE 多少" |
| 日期解析 | "去年Q3" → "2025-09-30" |
| 别名映射 | "猪场" → "网易"（28 个映射） |
| 单位标准化 | "50个亿" → "50亿" |
| 标点统一 | 全角转半角 |

**异步 RAG 增强**（`preprocess_with_rag`）：
1. RAG 向量检索（top_k=3，阈值 0.5）
2. 实体注入（股票代码 + 指标名 + 报告期）
3. 低置信度时 LLM 改写（超时 3s，失败抛出 `QueryRewriteError` 返回友好提示而非降级）

**为什么需要它**：用户输入极不规范（口语化、别名、模糊日期），直接扔给 LLM 分类会导致准确率大幅下降。预处理后 LLM 分类准确率从 ~75% 提升到 >95%。

---

### 部署与运维类

#### Q19：Docker Compose 中定义了哪几个服务？为什么这样拆分？

**参考答案**：
6 个服务：

| 服务 | 作用 | 为什么独立 |
|------|------|----------|
| **postgres** | 数据库 + 向量存储 | 数据持久化，独立升级/备份 |
| **redis** | 缓存 + 消息队列 + 限流 | Celery broker，独立扩缩 |
| **api** | FastAPI HTTP 服务 | 处理用户请求，可水平扩展 |
| **worker** | Celery 异步任务执行 | 执行耗时报告，资源隔离 |
| **beat** | Celery 定时任务调度 | 每日 RAG 入库，仅需 1 个实例 |
| **frontend** | Nginx + Vue SPA | 静态资源 + API 反代，独立部署 |

**拆分原则**：
- **关注点分离**：api/worker/beat 虽然用同一镜像，但职责完全不同
- **独立扩缩**：api 可以多副本，worker 可以按任务量调整并发，beat 只能单实例
- **故障隔离**：worker 内存溢出不影响 api 响应正常请求
- **健康检查独立**：每个服务独立 healthcheck，`docker compose ps` 一目了然

---

#### Q20：CI/CD 流程是怎样的？

**参考答案**（`.github/workflows/deploy.yml`）：

**Job 1：Test（每次 push）**
1. 启动服务容器（pgvector + Redis）
2. Setup Python 3.11
3. `pip install` + `pytest` 运行测试
4. `ruff check` Lint 检查
5. `alembic upgrade head && alembic check` 数据库迁移验证

**Job 2：Deploy（仅 master 分支，依赖 test 通过）**
1. SSH 到生产服务器
2. `git pull origin master`
3. 注入 Secrets（`PG_PASSWORD`, `DEEPSEEK_API_KEY`, `API_KEY` 等）
4. `docker compose build && up -d --force-recreate`
5. 健康检查：`curl -f http://localhost:8000/api/v1/health`
6. 失败则 `docker compose down` 回滚，`unset` 清除环境变量

**关键设计**：Secrets 通过 GitHub Secrets 传递，不写入文件系统，用完立即 `unset`。

---

### 开放思考类

#### Q21：如果你重新设计这个系统，会做哪些改进？

**参考答案**：
三个方向的改进：

1. **Agent 并行化**：当前 Agent 是严格串行的（数据收集→财务分析→舆情解读）。实际上财务分析和舆情分析可以并行执行（它们依赖的输入都是 `raw_data`，互不依赖）。用 `asyncio.gather` 并行后，comprehensive 请求的端到端延迟可以减少 30-40%。

2. **流式中间结果**：当前 comprehensive 任务在 Celery 中黑盒执行，用户只有轮询才能看到进度。如果每个 Agent 节点完成时都通过 Redis Pub/Sub 推送中间结果，前端可以逐步展示"数据收集中... → 财务分析结果预览... → 舆情分析结果预览..."，用户体验会好很多。

3. **持久化对话历史**：MVP 阶段对话历史只存在前端内存和 Redis（TTL 1h），刷新就没了。后续应该写入 PostgreSQL，支持跨设备同步、历史搜索。

---

#### Q22：这个系统最大的技术挑战是什么？

**参考答案**：
最大的挑战是**防幻觉**——让 LLM 生成准确可靠的金融数据报告。

金融场景对数据准确性要求极高（偏差 >1% 就可能导致错误的投资决策），而 LLM 天生有幻觉倾向。我们的应对策略是一个多层防御体系：

1. **Prompt 层**：Few-shot 示例 + 严格的 JSON Schema + 明确的数据来源标注要求
2. **代码层**：程序化事实核对（正则提取→DB 查询→偏差计算），不依赖 LLM 自查
3. **架构层**：反思循环（最多 3 轮重写）+ 强制退出机制
4. **特效检测**：源数据为 0 但报告值非零时标记为"疑似编造"

这个体系的核心理念是**"不要相信 LLM，用代码验证"**。

---

#### Q23：为什么选择 DeepSeek-V3 而不是 GPT-4？

**参考答案**：
三个原因，按重要性排序：

1. **合规性**：券商/资管属于金融监管行业，数据不出境是硬要求。DeepSeek 是国内厂商，API 服务在国内。

2. **成本**：DeepSeek-V3 约 ¥1/百万 token，GPT-4 约 $30/百万 token，价格差 200 倍以上。我们的 comprehensive 报告一次可能消耗 15K-20K token，高频使用成本差异巨大。

3. **中文金融能力**：DeepSeek 在中文金融文本上的表现不输 GPT-4，特别是财报分析、指标识别等任务。

但架构上我们通过 `llm_service.py` 的 fallback 机制预留了模型切换能力——改一个环境变量就能切换到 Qwen 或其他兼容 OpenAI API 的模型。

---

#### Q24：这个项目中你个人贡献最大的是哪部分？

**建议回答思路**（根据实际情况调整）：
- 如果你做了**意图分类器**：强调三级搜索兜底策略的设计，从 85% 提升到 95% 的准确率
- 如果你做了**事实核对**：强调程序化校验 vs LLM 校验的权衡，以及 4 种正则模式的覆盖度
- 如果你做了**查询预处理器**：强调 RAG 增强 + 规则管道的组合，以及 "失败抛错不降级" 的交互设计
- 如果你做了**数据源适配层**：强调多市场差异处理（A股/港股/美股三种完全不同的 API 和单位体系）

---

#### Q25：这个项目让你最有成就感的技术细节是什么？

**建议回答思路**：
可以选的几个方向：
1. **反思循环的退出机制**：`prev_fact_errors` 实现了"不重复修正同类型错误"的优化，防止 LLM 在同一个数字上反复横跳
2. **情感分析去重的归一化策略**：用正则归一化 + 字符串相似度替代 embedding，效果好且快 40 倍
3. **熔断器的并发设计**：细粒度的锁控制（只在状态转换时加锁，调用时释放），允许 half_open 下的并发探测
4. **"一只脚踩两船"的模型降级**：DeepSeek 重试 3 次失败后自动切 Qwen，对用户完全透明

---

## 6. 关键数字速记表

面试中能随口说出以下数字会显得你对项目非常熟悉：

| 类别 | 数字 | 说明 |
|------|------|------|
| **Agent 数量** | 5 个专职 + 2 个辅助 | 意图分类、数据收集、财务分析、舆情分析、校验总结 + rewriter、output |
| **意图分类** | 5 种 | chitchat / simple_query / financial_analysis / sentiment_analysis / comprehensive |
| **路由决策点** | 4 个条件边 | after_collect / after_financial / after_sentiment / after_review |
| **反思循环** | 最多 3 轮 | `MAX_RETRY_ROUNDS=3` |
| **事实核对** | 偏差 >1% 触发 | `FACT_CHECK_DEVIATION_TOLERANCE=0.01` |
| **杜邦容差** | 5% | `ROE_DEVIATION_TOLERANCE=0.05` |
| **LLM 重试** | 最多 3 次 | 指数退避 2^n 秒 |
| **熔断器** | 5 次失败 / 30s 恢复 | LLM；AKShare 用 3 次 / 60s |
| **限流** | 60 次/分钟 | Redis 滑动窗口 |
| **RAG Top-K** | 5 条 | `RAG_TOP_K=5` |
| **Embedding 维度** | 1024 维 | BGE-M3 |
| **报告篇幅** | 800-2000 字 | comprehensive 结构化报告 |
| **新闻批次** | 最多 30 条 | `MAX_NEWS_PER_BATCH=30` |
| **新闻去重阈值** | 相似度 >70% | difflib.SequenceMatcher |
| **Docker 服务** | 6 个 | postgres / redis / api / worker / beat / frontend |
| **API 端口** | 8000 (API) / 80 (前端) | PostgreSQL 15432 / Redis 16379 |
| **前端轮询** | 每 2 秒 | `waitForReport` |
| **Celery TTL** | 1 小时 | `TASK_TTL=3600` |
| **已知公司** | 46 家 | `_KNOWN_COMPANIES` 硬编码映射 |
| **别名映射** | 28 个 | 猪场→网易, 鹅厂→腾讯 等 |
| **中概股映射** | 6 只 | BIDU→09888, JD→09618 等 US→HK |
| **RAG 改写超时** | 3 秒 | `LLM_REWRITE_TIMEOUT=3.0` |
| **RAG 改写阈值** | 相似度 <0.5 | 低置信度触发 LLM 改写 |

---

> 💡 **面试小贴士**：
> 1. 回答问题时尽量从**具体代码或数字**切入，展现你对项目的真实掌控力
> 2. 技术选型类问题一定要说"为什么"——你为什么选 A 而不是 B，展示权衡能力
> 3. "遇到的问题及解决方案"是面试官最爱问的，准备 2-3 个你有深度参与的例子
> 4. 如果被问到不熟悉的部分，诚实说"这部分我不直接负责，但我的理解是..."比瞎编要好
> 5. 主动提到"如果有更多时间我会优化 X"展示你的工程品味和自驱力
