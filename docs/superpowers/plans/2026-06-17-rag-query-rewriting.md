# RAG-Enhanced Query Rewriting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add retrieval-augmented query rewriting before intent classification, so short/vague queries like "茅台怎么样" are expanded with context from the knowledge base before hitting the LLM classifier.

**Architecture:** Three new steps injected into the existing `query_preprocessor` pipeline — RAG retrieval → rule-based entity injection → confidence-gated LLM rewrite. All steps are async-safe and degrade gracefully: RAG failure falls through to rule injection, LLM failure returns a user-facing error prompt (not silent fallback, since a low-confidence query would waste downstream processing anyway).

**Tech Stack:** Python 3.11+, BGE-M3 embeddings (existing), pgvector (existing), DeepSeek-V3 via LLMService (existing)

**Spec:** `docs/superpowers/specs/2026-06-17-rag-query-rewriting-design.md`

---

### Task 1: Add configuration constants

**Files:**
- Modify: `backend/constants/metrics.py`

- [ ] **Step 1: Add constants to metrics.py**

Read `backend/constants/metrics.py` to find the right section (near the end, after `MAX_HISTORY_TURNS`), then add:

```python
# 检索增强改写
RAG_REWRITE_THRESHOLD = 0.5   # top-1 相似度低于此值触发 LLM 改写
RAG_REWRITE_TOP_K = 3         # 检索增强所用的文档数
LLM_REWRITE_TIMEOUT = 3.0     # LLM 改写超时（秒）
```

- [ ] **Step 2: Verify import**

Run: `python -c "from constants.metrics import RAG_REWRITE_THRESHOLD, RAG_REWRITE_TOP_K, LLM_REWRITE_TIMEOUT; print(RAG_REWRITE_THRESHOLD)"`
Expected: `0.5`

- [ ] **Step 3: Commit**

```bash
git add backend/constants/metrics.py
git commit -m "feat: add RAG rewrite configuration constants"
```

---

### Task 2: Build entity injection from retrieved context

**Files:**
- Create: `backend/tests/services/test_query_preprocessor.py`
- Modify: `backend/services/query_preprocessor.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_query_preprocessor.py`:

```python
"""Unit tests for query preprocessor RAG-enhanced rewriting."""
import pytest
from services.query_preprocessor import _inject_retrieved_entities


class TestInjectRetrievedEntities:
    def test_injects_company_code_not_in_original(self):
        text = "分析茅台的盈利能力"
        retrieved = [
            {"content": "贵州茅台(600519) ROE=10.1%", "company_code": "600519", "score": 0.8},
        ]
        result = _inject_retrieved_entities(text, retrieved)
        assert "600519" in result

    def test_does_not_inject_duplicate_code(self):
        text = "分析600519的盈利能力"
        retrieved = [
            {"content": "贵州茅台(600519) ROE=10.1%", "company_code": "600519", "score": 0.8},
        ]
        result = _inject_retrieved_entities(text, retrieved)
        # 600519 already in text, should not appear twice
        assert result.count("600519") == 1

    def test_injects_metric_names(self):
        text = "腾讯盈利能力"
        retrieved = [
            {"content": "腾讯2024年净利率达到29.91%，毛利率56.2%", "company_code": "00700", "score": 0.6},
        ]
        result = _inject_retrieved_entities(text, retrieved)
        assert "净利率" in result or "毛利率" in result

    def test_injects_report_date(self):
        text = "分析茅台的盈利能力"
        retrieved = [
            {"content": "贵州茅台2024-03-31 报告期 ROE=10.1%", "company_code": "600519", "score": 0.7},
        ]
        result = _inject_retrieved_entities(text, retrieved)
        assert "2024-03-31" in result

    def test_empty_retrieved_returns_original(self):
        text = "分析茅台的盈利能力"
        result = _inject_retrieved_entities(text, [])
        assert result == text

    def test_caps_entities_at_five(self):
        text = "分析茅台的盈利能力"
        retrieved = [
            {"content": "600519 ROE ROA 净利率 毛利率 营收 净利润 2024-03-31", "company_code": "600519", "score": 0.8},
        ]
        result = _inject_retrieved_entities(text, retrieved)
        # Should inject at most 5 entities
        parts = result.split("补充信息: ")[1].rstrip("）")
        entity_count = len(parts.split(", "))
        assert entity_count <= 5
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/services/test_query_preprocessor.py -v`
Expected: `FAIL` — `_inject_retrieved_entities` not defined

- [ ] **Step 3: Implement `_inject_retrieved_entities`**

Add to `backend/services/query_preprocessor.py`, after the `_normalize_units` function:

```python
# ── 3.5. 检索结果实体注入 ──

# Metrics to extract from retrieved documents
_EXTRACT_METRICS = [
    "ROE", "ROA", "净利率", "毛利率", "资产负债率", "产权比率",
    "营收", "净利润", "每股经营现金流", "权益乘数",
]

# Regex for report dates like "2024-03-31" or "2025-12-31"
_REPORT_DATE_PATTERN = re.compile(r'(\d{4}-\d{2}-\d{2})')


def _inject_retrieved_entities(text: str, retrieved: list[dict]) -> str:
    """从 RAG 检索结果中提取关键实体并注入原 query 末尾。

    提取: 股票代码、指标名、报告期（最多 5 个实体）。
    若 text 中已含该实体则跳过，避免重复。
    """
    if not retrieved:
        return text

    entities: list[str] = []
    seen = set(text)

    for doc in retrieved:
        content = doc.get("content", "")

        # 提取股票代码
        code = str(doc.get("company_code", ""))
        if code and code not in seen and code not in entities:
            entities.append(code)
            seen.add(code)

        # 提取指标名
        for metric in _EXTRACT_METRICS:
            if metric in content and metric not in seen and metric not in entities:
                entities.append(metric)
                seen.add(metric)

        # 提取报告期
        dates = _REPORT_DATE_PATTERN.findall(content)
        for d in dates:
            if d not in seen and d not in entities:
                entities.append(d)
                seen.add(d)

        if len(entities) >= 5:
            break

    if entities:
        return f"{text}（补充信息: {', '.join(entities[:5])}）"
    return text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_query_preprocessor.py::TestInjectRetrievedEntities -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/query_preprocessor.py backend/tests/services/test_query_preprocessor.py
git commit -m "feat: add RAG entity injection to query preprocessor"
```

---

### Task 3: Add async RAG retrieval step to preprocessor

**Files:**
- Modify: `backend/services/query_preprocessor.py`
- Modify: `backend/tests/services/test_query_preprocessor.py`

- [ ] **Step 1: Write tests for async retrieval and confidence check**

Append to `backend/tests/services/test_query_preprocessor.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


class TestRetrieveContext:
    @patch("services.query_preprocessor.search_rag")
    def test_retrieve_returns_top_k_docs(self, mock_search):
        mock_search.return_value = [
            {"content": "doc1", "company_code": "600519", "score": 0.8, "doc_title": "t1"},
            {"content": "doc2", "company_code": "600519", "score": 0.6, "doc_title": "t2"},
        ]
        from services.query_preprocessor import _retrieve_context

        async def run():
            return await _retrieve_context("茅台盈利能力", top_k=3)

        docs = asyncio.run(run())
        assert len(docs) == 2
        assert docs[0]["score"] == 0.8

    @patch("services.query_preprocessor.search_rag")
    def test_retrieve_returns_empty_on_error(self, mock_search):
        mock_search.side_effect = Exception("DB down")
        from services.query_preprocessor import _retrieve_context

        async def run():
            return await _retrieve_context("茅台", top_k=3)

        docs = asyncio.run(run())
        assert docs == []


class TestConfidenceGate:
    def test_triggers_rewrite_when_below_threshold(self):
        from services.query_preprocessor import _should_llm_rewrite
        assert _should_llm_rewrite([], 0.5) is True        # no results
        assert _should_llm_rewrite([{"score": 0.3}], 0.5) is True
        assert _should_llm_rewrite([{"score": 0.49}], 0.5) is True

    def test_skips_rewrite_when_above_threshold(self):
        from services.query_preprocessor import _should_llm_rewrite
        assert _should_llm_rewrite([{"score": 0.5}], 0.5) is False
        assert _should_llm_rewrite([{"score": 0.78}], 0.5) is False
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/services/test_query_preprocessor.py::TestRetrieveContext tests/services/test_query_preprocessor.py::TestConfidenceGate -v`
Expected: FAIL

- [ ] **Step 3: Implement `_retrieve_context` and `_should_llm_rewrite`**

Add to `backend/services/query_preprocessor.py`, after the imports section:

```python
# ── Async: RAG 检索上下文（用于改写） ──

async def _retrieve_context(query: str, top_k: int = 3) -> list[dict]:
    """调用 RAG 检索引擎，返回 top-k 文档片段列表。

    失败时返回空列表（不抛异常），上层降级处理。
    """
    try:
        from services.rag.search import search_rag
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import sessionmaker

        # Use the shared async session factory if available
        try:
            from services.db_utils import get_async_session_factory
            session_factory = get_async_session_factory()
        except Exception:
            session_factory = None

        results = await search_rag(
            query=query,
            company_code="",
            top_k=top_k,
            session_factory=session_factory,
        )
        return results or []
    except Exception as exc:
        logger.warning("rag_retrieve_failed", error=str(exc))
        return []


def _should_llm_rewrite(retrieved: list[dict], threshold: float) -> bool:
    """判断是否需要触发 LLM 改写。

    Returns True if:
      - 无检索结果（query 太模糊，知识库无匹配）
      - top-1 相似度 < threshold（语义关联弱）
    """
    if not retrieved:
        return True
    top_score = retrieved[0].get("score", 0) if retrieved else 0
    return top_score < threshold
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_query_preprocessor.py::TestRetrieveContext tests/services/test_query_preprocessor.py::TestConfidenceGate -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/query_preprocessor.py backend/tests/services/test_query_preprocessor.py
git commit -m "feat: add RAG retrieval and confidence gate to preprocessor"
```

---

### Task 4: Add LLM rewrite function with error handling

**Files:**
- Modify: `backend/services/query_preprocessor.py`
- Modify: `backend/tests/services/test_query_preprocessor.py`

- [ ] **Step 1: Write tests for LLM rewrite**

Append to `backend/tests/services/test_query_preprocessor.py`:

```python
class TestLLMRewrite:
    @patch("services.query_preprocessor.get_llm_service")
    def test_rewrite_returns_content(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke = AsyncMock(return_value={
            "content": "分析贵州茅台(600519)的盈利能力",
        })
        mock_get_llm.return_value = mock_llm

        from services.query_preprocessor import _llm_rewrite_query

        async def run():
            return await _llm_rewrite_query(
                "茅台怎么样",
                [{"content": "贵州茅台(600519) ROE=10.1%", "company_code": "600519", "score": 0.3}],
            )

        result = asyncio.run(run())
        assert "600519" in result

    @patch("services.query_preprocessor.get_llm_service")
    def test_rewrite_raises_on_llm_failure(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke = AsyncMock(side_effect=Exception("API error"))
        mock_get_llm.return_value = mock_llm

        from services.query_preprocessor import _llm_rewrite_query, QueryRewriteError

        async def run():
            return await _llm_rewrite_query(
                "茅台怎么样",
                [{"content": "...", "company_code": "600519", "score": 0.3}],
            )

        with pytest.raises(QueryRewriteError) as exc_info:
            asyncio.run(run())
        assert "问题不够明确" in str(exc_info.value)

    @patch("services.query_preprocessor.get_llm_service")
    def test_rewrite_raises_on_empty_response(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke = AsyncMock(return_value={"content": ""})
        mock_get_llm.return_value = mock_llm

        from services.query_preprocessor import _llm_rewrite_query, QueryRewriteError

        async def run():
            return await _llm_rewrite_query(
                "xyz",
                [{"content": "...", "company_code": "", "score": 0.1}],
            )

        with pytest.raises(QueryRewriteError):
            asyncio.run(run())
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/services/test_query_preprocessor.py::TestLLMRewrite -v`
Expected: 3 FAIL

- [ ] **Step 3: Implement `QueryRewriteError` and `_llm_rewrite_query`**

Add to `backend/services/query_preprocessor.py`, after `_should_llm_rewrite`:

```python
# ── LLM 改写 ──

class QueryRewriteError(Exception):
    """查询改写失败——向用户返回提示，不降级到原 query。"""


_REWRITE_SYSTEM_PROMPT = """你是一个金融查询改写助手。用户的问题可能简短模糊。基于知识库中检索到的参考信息，将用户问题改写为精确、具体、包含关键实体（股票代码、指标名、时间）的查询。

规则：
1. 保留用户原意，仅补充缺失的关键信息
2. 如果检索信息不足以判断，不要编造
3. 直接输出改写后的查询，不要加解释
4. 输出长度不超过 100 字

示例：
原问题: 茅台怎么样
参考信息: 贵州茅台(600519)2024Q3 ROE=10.1% 净利率=52.2%
改写: 分析贵州茅台(600519)2024Q3的盈利能力和财务表现"""


async def _llm_rewrite_query(
    original: str,
    retrieved: list[dict],
    timeout: float = 3.0,
) -> str:
    """用 LLM 改写模糊查询。

    Args:
        original: 原始用户输入
        retrieved: RAG 检索结果列表
        timeout: LLM 调用超时（秒）

    Returns:
        改写后的查询字符串

    Raises:
        QueryRewriteError: LLM 调用失败或返回空结果
    """
    # 拼接检索片段
    doc_parts: list[str] = []
    for i, doc in enumerate(retrieved[:3], 1):
        content = doc.get("content", "")[:500]
        title = doc.get("doc_title", "")
        header = f"[文档{i}]" + (f" {title}" if title else "")
        doc_parts.append(f"{header}\n{content}")
    doc_text = "\n\n---\n\n".join(doc_parts) if doc_parts else "（无参考信息）"

    user_prompt = (
        f"原问题: {original}\n\n"
        f"知识库参考信息:\n{doc_text}\n\n"
        f"请改写上述问题。"
    )

    try:
        from services.llm_service import get_llm_service
        import asyncio

        llm = get_llm_service()
        result = await asyncio.wait_for(
            llm.invoke("default", [
                {"role": "system", "content": _REWRITE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]),
            timeout=timeout,
        )
        rewritten = (result.get("content", "") or "").strip()

        if not rewritten or len(rewritten) < 4:
            raise QueryRewriteError(
                "问题不够明确，请补充股票代码或公司名称，"
                "例如'分析茅台2024Q3的盈利能力'"
            )

        logger.info("query_rewritten", original=original[:60], rewritten=rewritten[:80])
        return rewritten

    except QueryRewriteError:
        raise
    except asyncio.TimeoutError:
        logger.error("llm_rewrite_timeout", original=original[:60])
        raise QueryRewriteError(
            "问题不够明确，请补充股票代码或公司名称，"
            "例如'分析茅台2024Q3的盈利能力'"
        )
    except Exception as exc:
        logger.error("llm_rewrite_failed", original=original[:60], error=str(exc))
        raise QueryRewriteError(
            "问题不够明确，请补充股票代码或公司名称，"
            "例如'分析茅台2024Q3的盈利能力'"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_query_preprocessor.py::TestLLMRewrite -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/query_preprocessor.py backend/tests/services/test_query_preprocessor.py
git commit -m "feat: add LLM rewrite function with QueryRewriteError"
```

---

### Task 5: Wire async pipeline and expose `preprocess_with_rag`

**Files:**
- Modify: `backend/services/query_preprocessor.py`
- Modify: `backend/tests/services/test_query_preprocessor.py`

- [ ] **Step 1: Write integration test for the full async pipeline**

Append to `backend/tests/services/test_query_preprocessor.py`:

```python
class TestPreprocessWithRag:
    @patch("services.query_preprocessor.search_rag")
    @patch("services.query_preprocessor.get_llm_service")
    def test_high_confidence_skips_llm(self, mock_llm, mock_search):
        """top-1 score >= 0.5 → rule injection only, no LLM call."""
        mock_search.return_value = [
            {"content": "贵州茅台(600519) ROE=10.1% 净利率=52.2% 2024-03-31",
             "company_code": "600519", "score": 0.78, "doc_title": "茅台研报"},
        ]

        from services.query_preprocessor import preprocess_with_rag

        async def run():
            return await preprocess_with_rag("茅台盈利能力")

        result = asyncio.run(run())
        # Should have entity injection
        assert "补充信息" in result
        # LLM should NOT have been called
        mock_llm.assert_not_called()

    @patch("services.query_preprocessor.search_rag")
    @patch("services.query_preprocessor.get_llm_service")
    def test_low_confidence_triggers_llm(self, mock_llm, mock_search):
        """top-1 score < 0.5 → LLM rewrite triggered."""
        mock_search.return_value = [
            {"content": "some vague doc", "company_code": "", "score": 0.2, "doc_title": "x"},
        ]
        mock_llm_obj = MagicMock()
        mock_llm_obj.invoke = AsyncMock(return_value={
            "content": "分析贵州茅台(600519)的盈利能力",
        })
        mock_llm.return_value = mock_llm_obj

        from services.query_preprocessor import preprocess_with_rag

        async def run():
            return await preprocess_with_rag("茅台怎么样")

        result = asyncio.run(run())
        assert "600519" in result
        mock_llm_obj.invoke.assert_called_once()

    @patch("services.query_preprocessor.search_rag")
    def test_rag_failure_raises_rewrite_error(self, mock_search):
        """RAG fails → LLM rewrite triggered → if that also fails, error raised."""
        mock_search.side_effect = Exception("DB connection refused")

        from services.query_preprocessor import preprocess_with_rag, QueryRewriteError

        async def run():
            return await preprocess_with_rag("xyz123")

        # With empty RAG results and no LLM, should raise
        with pytest.raises(QueryRewriteError):
            asyncio.run(run())
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/services/test_query_preprocessor.py::TestPreprocessWithRag -v`
Expected: 3 FAIL

- [ ] **Step 3: Implement `preprocess_with_rag`**

Add to `backend/services/query_preprocessor.py`, after `preprocess()`:

```python
# ── 异步 RAG 增强管线 ──

async def preprocess_with_rag(
    text: str,
    threshold: float | None = None,
    top_k: int | None = None,
) -> str:
    """对用户查询执行检索增强的预处理。

    管线顺序:
      1. 同步规则预处理（日期、别名、空白）
      2. RAG 检索 top-k 文档
      3. 规则实体注入
      4. 置信度检查 → LLM 改写（如需要）

    Args:
        text: 原始用户输入
        threshold: 触发 LLM 改写的相似度阈值，默认 RAG_REWRITE_THRESHOLD
        top_k: RAG 检索文档数，默认 RAG_REWRITE_TOP_K

    Returns:
        处理后的查询字符串

    Raises:
        QueryRewriteError: LLM 改写失败且不应降级
    """
    from constants.metrics import RAG_REWRITE_THRESHOLD, RAG_REWRITE_TOP_K

    if threshold is None:
        threshold = RAG_REWRITE_THRESHOLD
    if top_k is None:
        top_k = RAG_REWRITE_TOP_K

    # Step 1: Rule preprocessing (sync)
    cleaned = preprocess(text, steps=[
        "normalize_whitespace", "resolve_dates", "normalize_names",
    ])

    # Step 2: RAG retrieval
    retrieved = await _retrieve_context(cleaned, top_k=top_k)

    # Step 3: Entity injection
    injected = _inject_retrieved_entities(cleaned, retrieved)

    # Step 4: Confidence gate → LLM rewrite
    if _should_llm_rewrite(retrieved, threshold):
        rewritten = await _llm_rewrite_query(cleaned, retrieved)
        logger.info("query_rag_rewrite", original=text[:60],
                    injected=injected[:60], rewritten=rewritten[:60])
        return rewritten

    logger.info("query_rag_entity_inject", original=text[:60],
                num_docs=len(retrieved), result=injected[:80])
    return injected
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/services/test_query_preprocessor.py -v`
Expected: all 17 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/query_preprocessor.py backend/tests/services/test_query_preprocessor.py
git commit -m "feat: add preprocess_with_rag async pipeline"
```

---

### Task 6: Integrate into intent classifier

**Files:**
- Modify: `backend/agents/intent_classifier/classifier.py`

- [ ] **Step 1: Add async preprocessing call to `classify_intent`**

Read `backend/agents/intent_classifier/classifier.py`. In the `classify_intent` function, replace the existing `preprocess(message)` call with the async `preprocess_with_rag`. Handle `QueryRewriteError` by returning an error intent:

```python
from services.query_preprocessor import preprocess_with_rag, QueryRewriteError

async def classify_intent(message: str, history: list[dict] | None = None) -> IntentResult:
    """LLM 分类意图 + 提取实体，RAG 增强改写 + 关键词兜底"""
    # 第零层: RAG 增强改写
    try:
        message = await preprocess_with_rag(message)
    except QueryRewriteError as e:
        # LLM 改写失败 → 返回错误提示给用户
        logger.warning("query_rewrite_failed_prompt_user", original=message[:60])
        return IntentResult(
            intent="chitchat",
            company_code="",
            company_name="",
            report_date="",
            metric_names=[],
            query_type="",
            query_target="",
            # Abuse the company_name field to smuggle the error prompt back
            _rewrite_error=str(e),
        )

    # 第一层: LLM 分类（已有）
    llm = get_llm_service()
    messages = [{"role": "system", "content": INTENT_CLASSIFIER_SYSTEM}]
    ...
```

**Important**: `IntentResult` is a dataclass. If it doesn't support extra fields, we need to handle the error differently. Check `backend/state.py` for the `IntentResult` definition.

If `IntentResult` is a frozen/typed dataclass, modify it to add `_rewrite_error: str = ""` as an optional field, or handle the error by raising an exception that `main.py` catches.

- [ ] **Step 2: Handle the rewrite error in `main.py`**

Read `backend/main.py`, find the `/chat` endpoint. After `classify_intent`, check if an error occurred and return the error message directly:

Replace:
```python
intent_result = await classify_intent(request.message)
```

With:
```python
intent_result = await classify_intent(request.message)
if intent_result.intent == "chitchat" and not intent_result.company_code and not intent_result.company_name:
    from services.query_preprocessor import QueryRewriteError
    # If classify_intent returned chitchat due to rewrite failure
    # (check _rewrite_error attribute if added, or check specific pattern)
    ...
```

**Simpler approach**: Instead of modifying IntentResult, have `classify_intent` raise `QueryRewriteError` directly. Then `main.py` catches it and returns the error message to the user:

In `classifier.py`:
```python
try:
    message = await preprocess_with_rag(message)
except QueryRewriteError:
    raise  # propagate to main.py
```

In `main.py`:
```python
from services.query_preprocessor import QueryRewriteError

try:
    intent_result = await classify_intent(request.message)
except QueryRewriteError as e:
    return StreamingResponse(
        iter([f"data: {json.dumps({'text': str(e)})}\n\n"]),
        media_type="text/event-stream",
    )
```

- [ ] **Step 3: Commit**

```bash
git add backend/agents/intent_classifier/classifier.py backend/main.py
git commit -m "feat: integrate RAG query rewriting into intent classifier"
```

---

### Task 7: End-to-end verification

**Files:** None (manual testing)

- [ ] **Step 1: Start all services**

```bash
# Backend
cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Celery (if comprehensive needed)
cd backend && celery -A services.task_queue.celery_app worker --loglevel=info -P solo
```

- [ ] **Step 2: Test high-confidence query (no LLM rewrite)**

```bash
printf '{"message":"分析茅台2024Q3的盈利能力"}' | curl -s -N -X POST http://localhost:8000/api/v1/chat -H "Content-Type: application/json" -d @-
# Expected: financial_analysis intent, SSE stream with Moutai Q3 2024 data
# Check logs for: query_rag_entity_inject (NOT query_rag_rewrite)
```

- [ ] **Step 3: Test low-confidence query (LLM rewrite triggered)**

```bash
printf '{"message":"茅台怎么样"}' | curl -s -N -X POST http://localhost:8000/api/v1/chat -H "Content-Type: application/json" -d @-
# Expected: financial_analysis intent with expanded query
# Check logs for: query_rag_rewrite
```

- [ ] **Step 4: Test completely unrecognizable query (error prompt)**

```bash
printf '{"message":"xyz123abc"}' | curl -s -N -X POST http://localhost:8000/api/v1/chat -H "Content-Type: application/json" -d @-
# Expected: query_rewrite_failed_prompt_user log → error message returned
```

- [ ] **Step 5: Run full test suite**

```bash
cd backend && python -m pytest tests/ -v
# Expected: all 88+ tests PASS
```

---

### Task 8: Final commit

```bash
git add -A
git commit -m "feat: complete RAG-enhanced query rewriting with preprocess_with_rag pipeline"
```
