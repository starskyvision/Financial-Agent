import pytest
import json
from unittest.mock import AsyncMock, patch
from state import make_initial_state
from agents.sentiment_analyzer.node import sentiment_analyzer_node


class TestSentimentAnalyzerNode:
    @pytest.mark.asyncio
    async def test_node_analyzes_news(self):
        state = make_initial_state("task-001")
        state["raw_data"] = {
            "financial_metrics": {},
            "news_headlines": [
                {"title": "茅台Q3营收超预期", "summary": "贵州茅台第三季度营收同比增长18%"},
                {"title": "茅台公告分红方案", "summary": "拟每10股派发现金红利100元"},
                {"title": "白酒板块整体走弱", "summary": "受宏观影响白酒板块今日下跌"},
            ],
            "doc_snippets": [],
        }
        mock_result = {
            "overall_sentiment": "positive", "overall_score": 0.72,
            "key_topics": ["业绩增长", "分红"],
            "summary": "茅台近期舆情偏正面。",
            "details": [
                {"title": "茅台Q3营收超预期", "sentiment": "positive", "score": 0.85, "reasoning": "业绩超预期"},
                {"title": "茅台公告分红方案", "sentiment": "positive", "score": 0.7, "reasoning": "分红利好"},
                {"title": "白酒板块整体走弱", "sentiment": "negative", "score": 0.6, "reasoning": "板块下跌"},
            ]
        }
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = {"content": json.dumps(mock_result), "model": "deepseek-chat",
                                         "usage": {"prompt_tokens": 200, "completion_tokens": 100}}
        with patch("agents.sentiment_analyzer.node.get_llm_service", return_value=mock_llm):
            result = await sentiment_analyzer_node(state)
            assert result["sentiment_result"]["overall_sentiment"] == "positive"
            assert result["sentiment_result"]["positive_count"] == 2

    @pytest.mark.asyncio
    async def test_node_handles_empty_news(self):
        state = make_initial_state("task-002")
        state["raw_data"] = {"financial_metrics": {}, "news_headlines": [], "doc_snippets": []}
        result = await sentiment_analyzer_node(state)
        assert result["sentiment_result"]["overall_sentiment"] == "neutral"
        assert result["sentiment_result"]["overall_score"] == 0.5

    @pytest.mark.asyncio
    async def test_node_handles_llm_error(self):
        state = make_initial_state("task-003")
        state["raw_data"] = {"financial_metrics": {}, "news_headlines": [{"title": "测试", "summary": "摘要"}],
                              "doc_snippets": []}
        mock_llm = AsyncMock()
        mock_llm.invoke.side_effect = Exception("LLM timeout")
        with patch("agents.sentiment_analyzer.node.get_llm_service", return_value=mock_llm):
            result = await sentiment_analyzer_node(state)
            assert result["sentiment_result"]["overall_sentiment"] == "neutral"
            assert any("舆情分析" in e for e in result["errors"])
