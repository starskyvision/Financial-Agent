# Phase 2 — 意图分类器 Agent

**优先级**: P0　|　**前置**: Phase 0　|　**预计工时**: 1 天

## 目标

实现入口意图分类节点，接收用户消息后输出四种意图之一并提取关键实体，驱动后续 Agent 路由。

## 子任务

### 2.1 编写意图分类 Prompt

📁 `backend/prompts/intent_classifier.md`

- [ ] 编写 System Prompt，定义四种意图的判定规则：

  | 意图 | 判定条件 | 典型问法 |
  |------|---------|---------|
  | `simple_query` | 查询单一指标或数据点，不需要分析 | "茅台PE多少""XX最新营收" |
  | `financial_analysis` | 涉及盈利能力/偿债能力/现金流分析，需计算或同比 | "分析茅台Q3盈利能力""XX现金流怎么样" |
  | `sentiment_analysis` | 询问市场情绪/舆论/新闻 | "市场怎么看XX""XX最近有什么利好" |
  | `comprehensive` | 同时涉及财务+舆情，或明确要求出报告 | "全面分析茅台""出份XX的投研报告" |

- [ ] 包含 3 个 Few-shot 示例
- [ ] 要求输出 JSON 格式：`{"intent":"...", "company_code":"...", "company_name":"...", "report_date":"...", "metric_names":[...]}`
- [ ] 定义实体提取规则：自动补全拼音简称→标准代码（如"茅台"→"600519"）

**验收**: Prompt 通过 LLM Playground 测试 5 条典型问法，分类准确

### 2.2 实现意图分类节点函数

📁 `backend/agents/intent_classifier/classifier.py`

- [ ] 实现 `async def classify_intent(message: str, history: list[dict]) -> IntentResult`
- [ ] `IntentResult` 为 Pydantic BaseModel，包含 `intent`、`company_code`、`company_name`、`report_date`、`metric_names`
- [ ] 调用 `LLMService.invoke("intent_classifier", messages=[system_prompt, user_message])`
- [ ] 使用 `with_structured_output(IntentResult)` 强制 JSON Schema 输出
- [ ] 缓存策略：同一 `conversation_id` 的最新意图缓存到 Redis `conv:{id}:intent`（TTL 1h），后续消息复用
- [ ] 降级策略：LLM 调用失败时默认返回 `intent="comprehensive"`（安全兜底走完整链路）

**验收**: 传入"分析茅台2024Q3的盈利能力" → 返回 `intent=financial_analysis, company_code=600519`

### 2.3 实现 LangGraph 入口节点

📁 `backend/agents/intent_classifier/node.py`

- [ ] 实现 LangGraph 节点函数 `async def intent_classifier_node(state: AgentState) -> AgentState`
- [ ] 从 `state["messages"]` 取最后一条用户消息
- [ ] 调用 `classify_intent()` 获取意图
- [ ] 写入 `state["intent"]`、`state["company_code"]`、`state["company_name"]`、`state["report_date"]`
- [ ] 写入 `state["status"] = "running"`
- [ ] 节点开始/结束记录 `structlog` 日志

**验收**: 作为 LangGraph 节点调用后 State 中 intent 字段被正确填充

### 2.4 编写意图分类单元测试

📁 `backend/tests/agents/test_intent_classifier.py`

- [ ] Mock `LLMService.invoke`，测试四种意图的正确分发
- [ ] 测试实体提取：拼音→代码映射
- [ ] 测试缓存命中时跳过 LLM 调用
- [ ] 测试 LLM 失败时降级为 comprehensive
- [ ] 测试 `IntentResult` Pydantic 校验（缺失字段时抛出 ValidationError）

**验收**: `pytest tests/agents/test_intent_classifier.py` 全部通过

---

## 产出物

- [ ] `backend/prompts/intent_classifier.md` — 意图分类 Prompt
- [ ] `backend/agents/intent_classifier/__init__.py`
- [ ] `backend/agents/intent_classifier/classifier.py` — 分类逻辑
- [ ] `backend/agents/intent_classifier/node.py` — LangGraph 节点
- [ ] `backend/tests/agents/test_intent_classifier.py` — 单元测试

*关联文档: [设计规格 §3.1](../superpowers/specs/2026-06-16-financial-agent-mvp-design.md#31-意图分类器新增入口节点)*
