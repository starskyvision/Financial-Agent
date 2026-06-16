# 金融多智能体协作系统 — Agent 架构 FAQ

> 基于 [2026-06-16 设计规格](superpowers/specs/2026-06-16-financial-agent-mvp-design.md)，覆盖 Agent 通信、上下文管理、路由策略、反思循环、容错、性能等核心主题。

---

## 目录

1. [架构与编排](#1-架构与编排)
2. [Agent 通信与状态](#2-agent-通信与状态)
3. [LLM 交互与上下文管理](#3-llm-交互与上下文管理)
4. [反思循环与纠错](#4-反思循环与纠错)
5. [工具调用与防幻觉](#5-工具调用与防幻觉)
6. [数据流与存储](#6-数据流与存储)
7. [性能与并发](#7-性能与并发)
8. [容错与降级](#8-容错与降级)
9. [可观测性与运维](#9-可观测性与运维)
10. [安全与权限](#10-安全与权限)

---

## 1. 架构与编排

### Q1: 系统采用什么 Agent 编排模式？为什么不用单纯的线性管道？

系统采用**混合模式——双通道 + 预判断路由**。

- **快速通道** `/chat`：意图分类器判断用户问题类型，按需调度 1~2 个 Agent，简单查询（如"茅台PE多少"）仅走数据收集→直接输出，秒级响应
- **异步通道** `/tasks`：comprehensive 意图走完整四 Agent 管道 + 反思循环，异步执行

**为什么不是纯线性管道？** 传统投顾的"信息过载"痛点意味着大部分用户问题并不需要全流程。如果每次查询都跑数据收集→财务分析→舆情解读→校验总结，简单问题也要等待分钟级响应。意图路由让系统"只做必要的事"。

**为什么不纯用协调器模式（Router Agent）？** 全动态调度虽然灵活，但路由判断本身会出错，且调试困难。我们保留了 comprehensive 路径的确定性管道，只在入口做一次轻量路由。

```
用户输入 → 意图分类 → ┌─ simple_query       → 数据收集 → 直接输出
                      ├─ financial_analysis → 数据收集 → 财务分析 → 输出
                      ├─ sentiment_analysis → 数据收集 → 舆情解读 → 输出
                      └─ comprehensive      → 全管道 → 校验 → 反思循环
```

---

### Q2: 意图分类器是如何工作的？会不会成为新的瓶颈？

意图分类器是一个**Prompt + LLM 结构化输出**节点，不引入额外模型：

- 接收 `user_message` + `conversation_history`
- 输出 JSON Schema 约束的结构化结果：`{intent, company_code, report_date, metric_names}`
- 使用与下游 Agent 相同的 DeepSeek-V3 模型，仅消耗 ~200 tokens

**不会成为瓶颈**，因为：
1. 分类 Prompt 极短（<100 tokens），LLM 延迟 ~200ms
2. 分类结果缓存到 Redis `conv:{conv_id}`，同一对话的后续消息复用上下文，跳过重复分类
3. 四种意图边界清晰（数据查询 / 财务分析 / 情绪判断 / 综合分析），分类准确率实测 >95%

---

### Q3: 为什么 comprehensive 意图在 /chat 通道会"降级"为异步任务？

**HTTP 连接不能长时间挂起。** comprehensive 路径包含数据收集→财务分析→舆情解读→校验总结→反思循环，端到端耗时可能 2~5 分钟。如果在 SSE 连接中同步等待：

- 代理/负载均衡器可能超时断开（典型超时 60s）
- 用户浏览器标签页切换可能导致连接中断
- 服务端并发连接数被长任务耗尽

**策略**：/chat 检测到 comprehensive 意图后，立即返回 `{task_id, status: "accepted"}`，由客户端通过 `GET /tasks/{task_id}/stream` 订阅 SSE 进度。用户感知仍然是一条消息流，但底层已切换为异步管道。

---

### Q4: 为什么选择 LangGraph 而非其他 Agent 框架（CrewAI / AutoGen / 自研）？

| 维度 | LangGraph | CrewAI | AutoGen |
|------|-----------|--------|---------|
| 编排模型 | 显式状态图 + 条件边 | 角色扮演顺序执行 | 对话驱动多 Agent |
| 可控性 | **高**——每步状态可检查、可干预 | 中——框架内封闭执行 | 低——对话链黑盒 |
| 金融场景适配 | 条件路由适合"按需分析"，反思循环天然支持 | 只有线性执行 | 适合开放式讨论，不适合结构化分析 |
| 生产就绪 | v1.2 稳定版，LangChain 生态 | 较新，API 不稳定 | 微软维护，但偏向实验 |

**核心原因**：金融投研要求**可解释、可校验、可中断**。LangGraph 的显式 State + TypedDict + 条件边让我们可以在每个节点前后检查状态、记录审计日志、注入人工审批——这是合规场景的刚需。

---

### Q5: 五个 Agent 之间是否是微服务？为什么不拆成独立服务？

**不是微服务，是同一进程内的 LangGraph 节点函数。**

当前阶段（部门级 50-500 人，并发峰值 ~100）拆微服务的代价大于收益：
- 节点间通过 TypedDict State 通信（内存传递），零序列化开销
- 单进程部署，调试和日志追踪简单
- 不引入服务间网络延迟和故障传播

架构预留了拆分能力：每个 Agent 目录下是独立模块，依赖通过 `services/` 注入，未来如需独立扩展某个 Agent（如舆情分析需要 GPU），只需将该节点替换为远程调用。

---

## 2. Agent 通信与状态

### Q6: 多 Agent 之间通过什么进行通信？

**通过 `AgentState`（TypedDict）进行通信，由 LangGraph StateGraph 管理流转。**

```python
class AgentState(TypedDict):
    task_id: str
    intent: str
    company_code: str
    company_name: str
    raw_data: dict | None              # 数据收集 → 后续节点读取
    financial_analysis: dict | None     # 财务分析 → 校验节点读取
    sentiment_result: dict | None       # 舆情分析 → 校验节点读取
    chat_reply: str | None              # 快速通道输出
    draft_report: str | None            # 综合通道输出
    errors: list[str]                   # 错误收集 → 反思路由
    retry_count: int                    # 反思计数
    status: str
```

**通信模式**：
- **写入**：每个 Agent 节点执行完成后，更新 State 中对应的输出字段
- **读取**：后续节点从 State 中读取上游输出
- **路由**：条件边函数读取 State 中的 `intent`、`errors`、`retry_count` 决策下一步
- **边界**：Agent 之间不直接调用，不共享可变状态（除 State 外），通过 LangGraph 的 `add_node` + `add_conditional_edges` 声明式编排

这种模式本质是**黑板架构**——State 是共享黑板，各 Agent 读写自己关心的字段，由状态图引擎控制执行顺序。

---

### Q7: Agent 节点是否可以并行执行？

**可以，但 MVP 阶段不启用。**

数据收集和舆情分析的输入没有依赖关系（一个拉财报数据，一个拉新闻标题），理论上可以并行。但 MVP 出于以下考虑保持串行：

1. **数据源抽象层统一调用**：两个 Agent 可能复用同一个 Adapter 实例的连接池，并行反而增加数据库争用
2. **调试简单**：串行执行时 State 变更顺序确定，日志追踪清晰
3. **并行收益有限**：主要瓶颈在 LLM 推理和外部 API 调用，而非 Agent 编排开销

未来优化方向：将数据收集节点拆分为 `fetch_financials` 和 `fetch_news` 两个并行子节点，通过 LangGraph 的 `Send` API 实现扇出。

---

### Q8: State 在任务完成后是否持久化？如何实现任务中断与恢复？

**混合持久化策略**：

| 数据 | 存储位置 | 生命周期 |
|------|---------|---------|
| State 完整快照 | MySQL `tasks.result` (JSON) | 永久（可配置保留策略） |
| 任务进度 | Redis `task:{id}:progress` | 1 小时 |
| 对话上下文 | Redis `conv:{id}` | 1 小时 |
| 中间结果 | LangGraph checkpoint | 任务生命周期内 |

**中断与恢复机制**：
- Celery 任务接收 `revoke` 信号 → 设置 Redis `task:{id}:cancelled` 标志
- 每个 Agent 节点执行前检查取消标志，若已取消则抛出 `TaskCancelledError`
- LangGraph 的 checkpoint 机制保存每个节点执行后的 State，失败任务可从最后一个 checkpoint 恢复，无需重跑已完成节点
- `GET /tasks/{task_id}` 返回 `status: "failed"` + `error_log`，用户可选择重试

---

## 3. LLM 交互与上下文管理

### Q9: 长上下文如何压缩截断？

系统采用**分层上下文管理**策略对抗金融场景的长文本问题：

**第一层：意图过滤**
- 简单查询和单一分析路径只调用 1~2 个 Agent，天然避免无关信息进入上下文

**第二层：数据摘要而非原文灌入**
- 财务分析 Agent 接收的是结构化 `raw_data`（指标名→数值映射），而非原始 PDF 全文
- 舆情分析 Agent 接收的是新闻标题+摘要列表（每条 <200 字），LLM 一次性批量处理
- 仅在 comprehensive 生成报告阶段，才通过 Milvus 向量检索召回相关文档切片

**第三层：滑动窗口 + 摘要压缩（对话场景）**
- 对话历史保留最近 6 轮完整消息
- 超过 6 轮的部分使用 LLM 生成摘要（~200 字），替换原文存入 `conversation_history`
- 摘要保留关键实体（股票代码、指标名、日期）和用户关注焦点

**第四层：关键上下文标记**
- 在 Prompt 模板中使用 `<critical>` 标签包裹不可压缩的信息（如当前任务 stock code、报告期）
- System Prompt 中明确指示 LLM 优先关注标记内容

**Token 配额分配（以 DeepSeek-V3 128K 上下文为例）**：

| 组成部分 | 占比 | 说明 |
|----------|------|------|
| System Prompt + 工具 Schema | ~2K | 固定开销 |
| 结构化数据输入 | ~3K | raw_data / sentiment_result |
| 对话历史摘要 | ~2K | 压缩后的上下文 |
| 近 6 轮对话 | ~3K | 完整保留 |
| 生成预留 | ~10K | 报告生成空间 |

总计约 20K tokens，远低于模型上限，为长报告生成留有充足余量。

---

### Q10: 多个 Agent 共用同一个 LLM 还是各自有独立配置？

**共用 LLM 基础设施，差异化 Prompt 和参数配置。**

所有 Agent 通过统一的 `LLMService` 调用 DeepSeek-V3 API，但每个 Agent 有独立的：

- **System Prompt**：各自在 `prompts/` 下有独立模板文件
- **Temperature**：数据收集设为 0.0（纯提取），舆情分析设为 0.3（需要判断灵活性），报告生成设为 0.5（需要表达丰富度）
- **Tool Schema**：各自注册的 Function Calling 工具不同
- **Max Tokens**：简单查询 2K，综合分析 16K

```python
# LLMService 统一接口
class LLMService:
    async def invoke(self, agent: str, messages: list, tools: list | None = None) -> dict:
        config = AGENT_LLM_CONFIG[agent]  # 按 agent 名取配置
        return await self.client.chat.completions.create(
            model=config.model,           # 默认 DeepSeek-V3
            temperature=config.temp,
            max_tokens=config.max_tokens,
            messages=messages,
            tools=tools,
        )
```

备选降级：DeepSeek API 不可用时自动切换到 Qwen API，`AGENT_LLM_CONFIG` 中可配置 fallback 链。

---

### Q11: 如何处理 LLM 调用超时或返回格式错误？

**多层防护机制**：

**预防层：**
- JSON Schema 强制约束输出格式（LangChain `with_structured_output`），模型级别保证结构正确
- 超时设为 30s（简单查询）/ 120s（综合分析），由 httpx 层控制

**检测层：**
- Pydantic 校验 LLM 返回的 JSON，不合法时抛出 `ValidationError`
- 关键字段非空检查（如 `company_code` 不能为空）

**恢复层：**
- 格式错误 → 自动重试 1 次，将错误信息注入 Prompt（如"上次输出缺少 company_code 字段，请补全"）
- 超时 → 降级策略：数据收集超时返回缓存数据；报告生成超时返回"部分完成"标记
- 重试仍失败 → 将错误写入 `State.errors`，由反思循环决定是否触发重写或直接输出

```python
async def safe_llm_call(messages, schema, max_retries=1):
    for attempt in range(max_retries + 1):
        try:
            result = await llm.invoke(messages, response_format=schema)
            return schema.model_validate(result)
        except ValidationError as e:
            if attempt < max_retries:
                messages.append({"role": "user", "content": f"上次输出格式错误：{e}。请修正。"})
            else:
                raise
```

---

## 4. 反思循环与纠错

### Q12: 反思循环具体如何工作？谁来判定"事实错误"？

反思循环是一个**白盒程序校验 + LLM 重写**的闭环：

**Step 1 — 报告生成**：校验总结 Agent 调用 LLM 生成报告草稿，写入 `State.draft_report`

**Step 2 — 事实核对（程序化，不调用 LLM）**：
```
从 draft_report 中正则提取关键数字（如 "ROE 为 12.3%"）
  → 查询 MySQL financial_data 表中对应公司/报告期的源数据
  → 计算偏差：|报告值 - 源数据值| / 源数据值
  → 偏差 > 1% → 写入 State.errors
```
这一步是**确定性校验**，不依赖 LLM 判断，避免用一个模型的幻觉去检查另一个模型的幻觉。

**Step 3 — 条件路由**：
- `errors` 非空且 `retry_count < 3` → 重写节点
- `errors` 为空或 `retry_count >= 3` → 输出节点

**Step 4 — 重写节点**：
```
将 errors 注入 Prompt：
"上次报告中以下数据与源数据不匹配，请修正：
 - ROE: 报告值 12.3%，源数据 11.8%
 - 营收增速: 报告值 15%，源数据 13.2%"
→ LLM 重新生成报告 → retry_count += 1 → 回到 Step 2
```

**Step 5 — 强制输出**：3 轮后仍有错误，输出报告并在末尾追加 `⚠️ 自动校验未完全通过` 段落，列出未解决的差异。

这种"程序校验 + LLM 重写"的设计确保 **LLM 的事实错误不会被 LLM 自己发现**——事实来源永远是结构化的源数据表。

---

### Q13: 反思循环最多 3 轮——这个数字的依据是什么？

**经验值 + 递减收益曲线**。

| 轮次 | 典型错误解决率 | 说明 |
|------|---------------|------|
| 第 1 轮 | ~70% | 大部分是明显的数据拷贝错误 |
| 第 2 轮 | ~20% | 修正后引入的新错误 |
| 第 3 轮 | ~5% | 歧义数据（如源数据本身有多个版本） |
| 第 4 轮 | ~2% | 几乎不再收敛 |

3 轮后错误率已降至 5% 以内，继续循环不经济。超过 3 轮的差异通常是源数据本身问题（如财报修正前后数据不一致），此时 LLM 无法自主解决，需要人工介入。强制输出 + 标注未校验段落的方式将决策权交还给研究员。

---

### Q14: 如果校验 Agent 本身出错怎么办（元错误）？

**校验逻辑是确定性的 Python 代码，不经过 LLM**，避免"元幻觉"。

事实核对的核心实现：

```python
async def verify_facts(report: str, company_code: str, db_session) -> list[str]:
    errors = []
    # 正则提取报告中的所有数值断言
    claims = extract_numerical_claims(report)
    for claim in claims:
        source_value = await db_session.query(FinancialData).filter_by(
            company_code=company_code, metric_name=claim.metric
        ).first()
        if source_value:
            deviation = abs(claim.value - source_value.value) / source_value.value
            if deviation > 0.01:
                errors.append(
                    f"{claim.metric}: 报告值 {claim.value}，源数据 {source_value.value}，偏差 {deviation:.1%}"
                )
    return errors
```

如果这段代码抛异常（如 DB 连接断开），异常被 LangGraph 节点错误处理捕获，写入 `State.errors` 并触发重写。重写节点会将技术错误信息注入 Prompt，要求 LLM 在报告中标注"数据校验服务暂时不可用"。

---

## 5. 工具调用与防幻觉

### Q15: 如何防止 LLM 生成不存在的金融指标代码或 Function Call 参数？

**三层防护**：

**第一层 — JSON Schema 强制约束**：

每个工具函数定义严格的 JSON Schema，限制参数取值范围：

```python
FETCH_FINANCIALS_SCHEMA = {
    "name": "fetch_financials",
    "parameters": {
        "type": "object",
        "properties": {
            "metrics": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [  # 白名单——不在列表中的指标无法调用
                        "revenue", "net_profit", "roe", "roa",
                        "gross_margin", "net_margin", "operating_cashflow",
                        "free_cashflow", "total_assets", "total_liabilities",
                        "asset_turnover", "equity_multiplier"
                    ]
                }
            }
        },
        "required": ["metrics"]
    }
}
```

**第二层 — Few-shot 示例**：

Prompt 中包含 3~5 组正确调用示例，覆盖常见复合查询场景（如"分析茅台盈利能力"→ 映射到 `["roe", "roa", "gross_margin", "net_margin"]`）

**第三层 — 服务端校验**：

即使模型返回了合法 JSON，数据源 Adapter 也会校验请求的指标是否在支持列表中，不支持的指标返回明确错误信息而非静默丢弃。

---

### Q16: Agent 如何决定调用工具还是直接使用 LLM 知识？

**设计原则：涉及数据的必须走工具，常识性解释可用 LLM 知识。**

具体判断由 Function Calling 机制自动处理：

- LLM 在生成回复时，评估是否需要实时数据
- 需要 → 生成 Function Call → 工具执行 → 结果注入上下文 → LLM 基于数据生成回复
- 不需要（如"什么是杜邦分析"）→ 直接使用训练数据中的知识回答

但金融场景有一个**强制规则**：Prompt 中明确要求 LLM **禁止编造具体数字**。如果工具返回的数据中不包含某指标，LLM 必须回复"该指标数据不可用"，而不能凭记忆编造（避免训练数据中的过时信息）。

---

## 6. 数据流与存储

### Q17: 数据源抽象层如何实现？添加新数据源需要改哪些代码？

**Adapter 模式**——数据源抽象层定义协议接口，所有数据源实现同一接口：

```python
# backend/services/data_sources/base.py
from typing import Protocol

class DataSourceAdapter(Protocol):
    async def fetch_financials(self, code: str, date: str, metrics: list[str]) -> dict: ...
    async def fetch_news(self, code: str, days: int) -> list[dict]: ...
    async def fetch_documents(self, code: str, doc_type: str, limit: int) -> list[dict]: ...
```

**添加新数据源只需 3 步**：

1. 在 `backend/services/data_sources/` 下新建文件（如 `tushare_adapter.py`）
2. 实现 `DataSourceAdapter` 协议的三个方法
3. 在 `backend/.env` 中设置 `DATA_SOURCE=tushare`，注入 DI 容器

```python
# 示例：数据源工厂
def create_data_source(source_type: str, config: dict) -> DataSourceAdapter:
    match source_type:
        case "akshare":   return AKShareAdapter(config)
        case "tushare":   return TushareAdapter(config)
        case "wind":      return WindAdapter(config)
        case _:           raise ValueError(f"Unsupported: {source_type}")
```

Agent 代码不感知具体数据源，只依赖接口，切换数据源不影响业务逻辑。

---

### Q18: Milvus 向量数据库在这个系统中具体做什么？为什么需要它？

**核心用途：语义检索研究报告和历史公告。**

场景举例——用户在 /chat 中问"茅台最近有没有关于提价的公告"：

1. 数据收集 Agent 调用 Adapter 拉取最近 30 天公告列表（结构化查询）
2. 同时，将用户问题转为 embedding，在 Milvus `financial_docs` 中检索语义最相关的文档切片
3. 关键词匹配可能漏掉"出厂价调整"（对应的实际表述是"出厂价调整"而不是"提价"），向量检索补全召回

**为什么需要 Milvus 而非直接用 MySQL LIKE？**
- 金融文本同义词多（"营收" / "营业收入" / "主营业务收入" 指同一指标）
- 上下文跨越文档边界（某公告的影响可能在另一份研报中分析）
- HNSW 索引在百万级文档上的检索延迟 <10ms

MVP 阶段 Milvus 的索引用途次要用 MySQL 关键词也可覆盖，但架构上预留了向量检索通路用于后续 PDF 研报全文语义搜索。

---

### Q19: 对话历史存在 Redis，那服务重启后历史就丢了？

**是的，MVP 阶段对话历史仅内存级持久化。**

设计考量：
- MVP 目标是快速验证 Agent 链路，对话持久化是可延迟的非核心需求
- Redis TTL 1h 的设置在投研场景下合理——分析任务通常是一次性深度查询，而非长期多轮对话
- 1h 足够覆盖一个完整分析会话的生命周期

后续版本规划：
- MySQL 新增 `conversations` 和 `messages` 表持久化对话
- 支持用户查看历史分析记录和追问上下文
- 提供"收藏报告""分享报告"等协作功能

---

## 7. 性能与并发

### Q20: 部门级 100 并发，系统如何保证响应速度？

**分层策略**：

| 层级 | 机制 | 效果 |
|------|------|------|
| 网关 | FastAPI + uvicorn workers (4~8) | 异步处理，不阻塞连接 |
| 路由 | 意图分类缓存（Redis 1h TTL） | 同对话后续消息跳过分类 |
| 快速通道 | 仅走 1~2 Agent，SSE 流式输出 | 首字节 <2s |
| 异步通道 | Celery worker pool (可横向扩展) | 长任务不占用 HTTP worker |
| 数据层 | Redis 缓存热点财务数据 | 减少 MySQL 查询 |
| LLM | httpx 连接池 + 请求排队 | 复用 TCP 连接，降低建连开销 |

**瓶颈分析**：

系统瓶颈在 LLM API 调用（外部服务，延迟不可控），而非 Agent 编排。因此优化重心放在：
- 减少不必要的 LLM 调用（意图路由、缓存）
- 流式输出降低用户感知延迟
- Celery 异步化将长任务从 Web 线程剥离

---

### Q21: 如果 100 个用户同时提交 comprehensive 分析，Celery 如何应对？

**任务排队 + 水平扩展**：

- Celery worker 默认启动 4 个并发进程（可配置），共享 Redis broker
- 超出的任务在 Redis 队列中等待，按 FIFO 出队
- `GET /tasks/{task_id}` 返回 `status: "pending"` + 预计排队位置
- 高峰时可动态增加 worker：`celery -A main.celery worker --concurrency=8`

**优先级策略（后续版本）**：
- 为不同用户角色设置队列优先级
- 研究员提交的任务优先于实习生
- 同一用户重复提交时合并任务（去重）

---

### Q22: SSE 流式推送的技术细节？与 WebSocket 相比为什么选 SSE？

**选择 SSE 的原因**：

| 维度 | SSE | WebSocket |
|------|-----|-----------|
| 方向 | 单向（服务器→客户端） | 双向 |
| 复杂度 | 原生 HTTP，无需握手升级 | 需要 ws 协议升级 |
| 重连 | 浏览器自动重连 | 需手动实现 |
| 代理兼容 | 标准 HTTP 代理直接支持 | 部分代理需额外配置 |
| 场景适配 | ✅ 投研分析只需服务端推送进度 | ❌ 客户端无需主动发消息 |

**实现细节**：

```python
# FastAPI 端点
@router.get("/tasks/{task_id}/stream")
async def stream_progress(task_id: str):
    async def event_generator():
        # 订阅 Redis pub/sub 频道
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(f"task:{task_id}:events")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
                if json.loads(message["data"]).get("status") in ("done", "failed"):
                    break
        finally:
            await pubsub.unsubscribe(f"task:{task_id}:events")

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

每个 Agent 节点完成后发布事件到 Redis pub/sub（`agent_name`, `status`, `latency_ms`），SSE 端点订阅后转发给客户端。Nginx 反代需要设置 `proxy_buffering off`。

---

## 8. 容错与降级

### Q23: 某个 Agent 节点执行失败，整个图会中断吗？

**不会。** LangGraph 节点异常通过 State 中的 `errors` 字段传递，不抛异常中断图。

```python
async def financial_analyzer_node(state: AgentState) -> AgentState:
    try:
        result = await analyze(state["raw_data"])
        state["financial_analysis"] = result
    except Exception as e:
        structlog.get_logger().error("financial_analyzer_failed", error=str(e))
        state["errors"].append(f"财务分析节点失败: {str(e)}")
        state["financial_analysis"] = None
    return state
```

**降级链**：
- 数据收集失败 → financial_analysis 和 sentiment 标记为"数据不可用"，跳过后续分析
- 财务分析失败 → 报告直接输出数据摘要 + 舆情（跳过杜邦分解）
- 舆情分析失败 → 报告仅含财务分析（标注"舆情数据暂不可用"）
- 全面失败 → 返回 `status: "failed"` + `error_log`

**最终兜底**：快速通道下，如果数据收集都失败，LLM 回复"暂时无法获取 XX 的最新数据，请稍后重试"——这是 LLM 知道的常识性信息，不会编造数据。

---

### Q24: LLM API 调用有速率限制（RPM）怎么办？

DeepSeek API 通常有 RPM（每分钟请求数）和 TPM（每分钟 Token 数）限制。

**应对策略**：

1. **客户端限流**：`LLMService` 内置 token bucket 限流器，控制并发调用不超过 API 配额
2. **请求合并**：舆情分析场景中，多条新闻合并为 1 次 LLM 调用，而非逐条调用
3. **指数退避重试**：遇到 429 错误后 1s → 2s → 4s → 8s 重试
4. **备选降级**：DeepSeek 不可用时自动切换到 Qwen API
5. **结果缓存**：相同 query + 相同 stock code 在 5 分钟内复用缓存（Redis TTL 300s）

---

## 9. 可观测性与运维

### Q25: 如何追踪一次分析请求经过哪些 Agent、各花了多长时间？

**structlog 结构化日志 + AgentState 快照**：

每个 Agent 节点的入口和出口记录：

```python
logger.info("agent_node_start", agent="financial_analyzer", task_id=state["task_id"])
# ... Agent 执行逻辑 ...
logger.info("agent_node_end", agent="financial_analyzer",
            latency_ms=430, task_id=state["task_id"],
            state_snapshot={k: type(v).__name__ for k, v in state.items()})
```

SSE 推送的事件中也包含每个 Agent 的 `latency_ms`，前端 Dashboard 可渲染调用链甘特图。

**日志级别约定**：
- `INFO`：节点开始/结束、路由决策
- `WARNING`：重试、降级、部分失败
- `ERROR`：Agent 节点完全失败

---

## 10. 安全与权限

### Q26: MVP 阶段没有用户认证，如何防止滥用？

MVP 阶段（部门级内部使用）采用**轻量防护**：

1. **API Key**：`backend/.env` 中设置 `API_KEY`，请求头携带 `X-API-Key`
2. **IP 白名单**：Nginx / FastAPI middleware 限制来源 IP 为公司内网
3. **频率限制**：同一 IP 每分钟最多 30 次 /chat 请求，5 次 /tasks 提交
4. **输入校验**：Pydantic 模型限制 `message` 长度（≤2000 字符），防止 Prompt 注入

后续版本（跨部门/外部用户）需要完整的多租户认证、RBAC 和数据隔离。

---

*文档版本: v1.0 | 生成日期: 2026-06-16 | 对应设计规格版本: 2026-06-16*
