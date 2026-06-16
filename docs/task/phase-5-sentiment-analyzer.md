# Phase 5 — 舆情解读 Agent

**优先级**: P1　|　**前置**: Phase 3　|　**预计工时**: 1.5 天

## 目标

实现舆情解读 Agent 节点，对新闻标题和摘要进行情感三分类、主题聚合，输出结构化的舆情分析结果。

## 子任务

### 5.1 编写舆情分析 Prompt

📁 `backend/prompts/sentiment_analysis.md`

- [ ] 编写 System Prompt，定义情感三分类标准：

  | 标签 | 判定条件 | 示例 |
  |------|---------|------|
  | `positive` | 明显利好：业绩超预期、政策扶持、大额订单 | "茅台Q3营收同比增长18%" |
  | `neutral` | 信息性报道、人事变动、例行公告 | "茅台发布Q3财报" |
  | `negative` | 明显利空：业绩下滑、监管处罚、管理层负面 | "茅台Q3净利润不及预期" |

- [ ] 强度打分规则：0~1 分，positive ≥0.7 为强利好，negative ≤0.3 为强利空
- [ ] 要求 LLM 批量处理多条新闻（一次最多 30 条），输出 JSON 数组
- [ ] Few-shot 涵盖三种情感 + 边界案例（看似利好实为中性）
- [ ] Prompt 中明确要求**只基于提供的新闻文本判断**，不引入外部知识

**验收**: Prompt 通过 LLM Playground 测试 10 条新闻，情感标签人工评审准确率 ≥85%

### 5.2 实现舆情分析节点函数

📁 `backend/agents/sentiment_analyzer/node.py`

- [ ] 实现 `async def sentiment_analyzer_node(state: AgentState) -> AgentState`
- [ ] 从 `state["raw_data"]["news_headlines"]` 读取新闻列表
- [ ] 若新闻为空（无数据或数据拉取失败）→ 直接跳过：
  ```python
  state["sentiment_result"] = {"sentiment_label": "neutral", "score": 0.5, "summary": "无可用舆情数据"}
  ```
- [ ] 调用 LLM 批量分析，限制单次最多 30 条（超出时分批处理）
- [ ] 写入 `state["sentiment_result"]`：
  ```python
  {
      "overall_sentiment": "positive" | "neutral" | "negative",  # 整体倾向
      "overall_score": 0.65,                                      # 整体强度
      "positive_count": 5, "neutral_count": 3, "negative_count": 2,
      "key_topics": ["提价预期", "渠道改革"],                      # LLM 提取的关键主题
      "summary": "近期茅台舆情偏正面，主要围绕提价预期...",         # 1~2 段文字总结
      "details": [                                                # 逐条分析
          {"title": "...", "sentiment": "positive", "score": 0.8, "reasoning": "..."},
          ...
      ]
  }
  ```

**验收**: 传入 10 条新闻标题 → sentiment_result 中 overall_sentiment 和 details 完整

### 5.3 实现舆情数据写入 Redis 时序缓存

📁 `backend/agents/sentiment_analyzer/cache.py`

- [ ] 实现 `async def cache_sentiment(code: str, date: str, result: dict, redis_client) -> None`
- [ ] Key 格式：`sentiment:{code}:{date}`，Value 为 JSON
- [ ] TTL 设为 24 小时
- [ ] 实现 `async def get_sentiment_timeline(code: str, days: int, redis_client) -> list[dict]`
- [ ] 查询指定股票最近 N 天的舆情时序（用于前端走势图）

**验收**: 写入后通过 `get_sentiment_timeline("600519", 7, ...)` 能查到数据

### 5.4 实现舆情分析工具 Schema

📁 `backend/agents/sentiment_analyzer/tools.py`

- [ ] 定义 `search_news` Function Calling JSON Schema（供未来工具调用使用）
- [ ] `keyword` 参数为 required，`days` 默认为 7

**验收**: JSON Schema 通过校验

### 5.5 编写舆情分析单元测试

📁 `backend/tests/agents/test_sentiment_analyzer.py`

- [ ] Mock LLM 返回预定义 JSON，测试节点完整流程
- [ ] 测试空新闻列表时跳过分析
- [ ] 测试新闻 >30 条时自动分批并合并结果
- [ ] 测试 `cache_sentiment` / `get_sentiment_timeline` Redis 读写
- [ ] 测试 LLM 失败时降级为 neutral

**验收**: `pytest tests/agents/test_sentiment_analyzer.py` 全部通过

---

## 产出物

- [ ] `backend/prompts/sentiment_analysis.md` — 舆情分析 Prompt
- [ ] `backend/agents/sentiment_analyzer/__init__.py`
- [ ] `backend/agents/sentiment_analyzer/node.py` — LangGraph 节点
- [ ] `backend/agents/sentiment_analyzer/cache.py` — Redis 时序缓存
- [ ] `backend/agents/sentiment_analyzer/tools.py` — Function Calling Schema
- [ ] `backend/tests/agents/test_sentiment_analyzer.py` — 单元测试

*关联文档: [设计规格 §3.4](../superpowers/specs/2026-06-16-financial-agent-mvp-design.md#34-舆情解读-agent)*
