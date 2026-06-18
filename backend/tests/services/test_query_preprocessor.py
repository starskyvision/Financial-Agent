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


import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


class TestRetrieveContext:
    @patch("services.rag.search.search_rag")
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

    @patch("services.rag.search.search_rag")
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


class TestPreprocessWithRag:
    @patch("services.rag.search.search_rag")
    @patch("services.query_preprocessor.get_llm_service")
    def test_high_confidence_skips_llm(self, mock_llm, mock_search):
        """top-1 score >= 0.5 -> rule injection only, no LLM call."""
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

    @patch("services.rag.search.search_rag")
    @patch("services.query_preprocessor.get_llm_service")
    def test_low_confidence_triggers_llm(self, mock_llm, mock_search):
        """top-1 score < 0.5 -> LLM rewrite triggered."""
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

    @patch("services.rag.search.search_rag")
    def test_rag_failure_raises_rewrite_error(self, mock_search):
        """RAG fails -> no results -> LLM rewrite not available -> error."""
        mock_search.side_effect = Exception("DB connection refused")

        from services.query_preprocessor import preprocess_with_rag, QueryRewriteError

        async def run():
            return await preprocess_with_rag("xyz123")

        with pytest.raises(QueryRewriteError):
            asyncio.run(run())
