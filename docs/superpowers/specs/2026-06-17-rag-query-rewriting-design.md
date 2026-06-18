# 检索增强查询改写 (RAG-Enhanced Query Rewriting)

**日期**: 2026-06-17
**状态**: 已设计，待实现计划
**依赖**: 查询预处理器 `services/query_preprocessor.py`（已存在），RAG 检索引擎 `services/rag/`（已存在）

---

## 目标

用户输入的查询可能简短模糊（如"茅台怎么样"），导致意图分类不准确、数据检索命中率低。通过在意图分类前引入检索增强的查询改写，将模糊查询扩展为包含具体实体和上下文的精确查询。

## 总体架构

```
用户 query
  │
  ├─→ ① 规则预处理器（已有）
  │     相对日期、股票别名、空白清理
  │
  ├─→ ② RAG 快速检索（新增）
  │     top-3 文档片段 + 相似度分数
  │
  ├─→ ③ 实体注入（规则层，新增）
  │     从检索结果提取：公司名、指标名、报告期 → 拼入 query
  │
  ├─→ ④ 置信度判断（新增）
  │     top-1 相似度 < 0.5 → LLM 改写
  │     top-1 相似度 ≥ 0.5 → 直接用规则注入结果
  │
  ├─→ ⑤ LLM 改写（新增，仅低置信度时触发）
  │     prompt = 原始query + 检索片段 → 输出改写query
  │     失败 → 返回提示："问题不够明确，请补充股票代码或公司名称"
  │
  └─→ ⑥ 改写后 query → classify_intent → ...（现有流程）
```

## 模块设计

### 2. RAG 快速检索

**位置**: `services/query_preprocessor.py`（新增步骤 `retrieve_context`）

**逻辑**:
1. 将预处理后的 query 用 `Embedder.embed_query()` 向量化
2. 调用 `Retriever.search(query, top_k=3)` 检索
3. 返回 `list[{content, score, doc_title, company_code}]`

**失败处理**: 检索异常（DB 断开、embedder 未加载）→ 返回空列表，后续步骤降级为规则注入或原 query。

### 3. 实体注入（规则层）

**位置**: `services/query_preprocessor.py`（新增步骤 `inject_retrieved_entities`）

**逻辑**:
```python
def _inject_retrieved_entities(text: str, retrieved: list[dict]) -> str:
    """从检索结果中提取关键实体并注入原 query。"""
    if not retrieved:
        return text

    entities = []
    for doc in retrieved:
        # 提取公司代码
        code = doc.get("company_code", "")
        if code and code not in text:
            entities.append(code)
        # 提取指标名（正则匹配）
        for metric in ["ROE", "ROA", "净利率", "毛利率", "营收", "净利润"]:
            if metric in doc.get("content", "") and metric not in text:
                entities.append(metric)
        # 提取报告期
        import re
        dates = re.findall(r'\d{4}-\d{2}-\d{2}', doc.get("content", ""))
        for d in dates[:1]:
            if d not in text:
                entities.append(d)

    if entities:
        return f"{text}（补充信息: {', '.join(entities[:5])}）"
    return text
```

### 4. 置信度判断

**位置**: `services/query_preprocessor.py`（新增步骤 `maybe_llm_rewrite`）

**阈值**: `RAG_REWRITE_THRESHOLD = 0.5`

- `top-1 score < 0.5` → 触发 LLM 改写
- `top-1 score >= 0.5` → 直接使用规则注入结果
- 无检索结果 → 触发 LLM 改写（更激进的推断）

### 5. LLM 改写

**位置**: `services/query_preprocessor.py`（新增函数 `_llm_rewrite_query`）

**LLM Agent**: 复用现有 `default` agent 配置（DeepSeek-V3, temperature 0.2）

**System Prompt**:
```
你是一个金融查询改写助手。用户的问题可能简短模糊。基于知识库中检索到的参考信息，将用户问题改写为精确、具体、包含关键实体（股票代码、指标名、时间）的查询。

规则：
1. 保留用户原意，仅补充缺失的关键信息
2. 如果检索信息不足以判断，不要编造
3. 直接输出改写后的查询，不要加解释

示例：
用户: 茅台怎么样
检索: [文档1: 贵州茅台(600519)2024Q3 ROE=10.1% 净利率=52.2%...]
改写: 分析贵州茅台(600519)2024Q3的盈利能力和财务表现
```

**User Prompt**:
```
原始问题: {original_query}

知识库参考信息:
{doc_1_content}
---
{doc_2_content}
---
{doc_3_content}

请改写上述问题。
```

### 6. 失败降级

| 失败场景 | 降级行为 |
|---------|---------|
| RAG 检索异常 | 原 query + 规则预处理器 |
| 规则注入异常 | 原 query |
| LLM 改写超时（3s） | **不降级**：返回错误提示给用户 |
| LLM 改写 API 错误 | **不降级**：返回错误提示给用户 |
| LLM 返回空/无效结果 | 返回错误提示 |

**错误提示**: `"问题不够明确，请补充股票代码或公司名称，例如'分析茅台2024Q3的盈利能力'"`

**为什么 LLM 失败不降级？** 因为触发 LLM 改写意味着检索置信度低（< 0.5），原 query 本身太模糊。如果此时降级到原 query，后续意图分类和数据拉取大概率失败，反而浪费更多时间。尽早让用户明确问题更高效。

## 集成点

### 改写 pipeline 在分类器中的位置

```python
# agents/intent_classifier/classifier.py — classify_intent()

async def classify_intent(message, history=None):
    # 第零层: 规则预处理（已有）
    message = preprocess(message,
        steps=["normalize_whitespace", "resolve_dates", "normalize_names"])

    # 第零层-B: 检索增强改写（新增）
    message = await preprocess_with_rag(message)

    # 第一层: LLM 分类（已有）
    ...
```

### LLM 调用配置

改写使用的 LLM agent 名: `"query_rewriter"`

新增配置到 `AGENT_LLM_CONFIG`（可选，也可复用 `"default"`）:
```python
"query_rewriter": {
    "model": DEFAULT_MODEL,
    "temperature": 0.2,
    "max_tokens": 256
}
```

## 非功能需求

**延迟**:
| 步骤 | 延迟 | 触发条件 |
|------|------|---------|
| 规则预处理 | < 50ms | 始终 |
| RAG 检索 | ~100ms | 始终 |
| 规则注入 | < 10ms | 始终 |
| LLM 改写 | ~1-2s | 仅低置信度时 |
| **总计（最坏）** | **~2.2s** | |

**可配置参数**:
- `RAG_REWRITE_THRESHOLD`: 置信度阈值（默认 0.5）
- `RAG_REWRITE_TOP_K`: 检索文档数（默认 3）
- `LLM_REWRITE_TIMEOUT`: LLM 改写超时（默认 3s）

**测试策略**:
- 单元测试：`_inject_retrieved_entities` 实体提取正确性
- 单元测试：置信度阈值边界（score=0.49 触发改写，score=0.51 不触发）
- 集成测试：完整 pipeline 端到端，mock RAG 检索
- 降级测试：RAG 故障 → 规则注入成功，LLM 故障 → 返回错误提示

## 数据流示例

**示例 1: 模糊 query（触发 LLM 改写）**
```
输入: "茅台怎么样"

① 规则预处理: "贵州茅台怎么样"
② RAG 检索: [{"content":"贵州茅台(600519) ROE=10.1%...", "score": 0.32}]
③ 实体注入: "贵州茅台怎么样（补充信息: 600519, ROE, 净利率, 2024-03-31）"
④ 置信度: 0.32 < 0.5 → 触发 LLM 改写
⑤ LLM 输出: "分析贵州茅台(600519)2024Q3的盈利能力和财务表现"
⑥ → classify_intent → financial_analysis, code=600519
```

**示例 2: 具体 query（不触发 LLM）**
```
输入: "分析茅台2024Q3盈利能力"

① 规则预处理: "分析贵州茅台2024Q3盈利能力"
② RAG 检索: [{"content":"贵州茅台(600519) ROE=10.1%...", "score": 0.78}]
③ 实体注入: "分析贵州茅台2024Q3盈利能力（补充信息: 600519, ROE）"
④ 置信度: 0.78 ≥ 0.5 → 跳过 LLM
⑥ → classify_intent → financial_analysis, code=600519
```
