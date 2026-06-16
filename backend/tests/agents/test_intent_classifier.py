import pytest
import json
from unittest.mock import AsyncMock, patch
from state import IntentResult, make_initial_state
from agents.intent_classifier.classifier import classify_intent
from agents.intent_classifier.node import intent_classifier_node


class TestClassifyIntent:
    @pytest.mark.asyncio
    async def test_financial_analysis_intent(self):
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = {
            "content": json.dumps({"intent": "financial_analysis", "company_code": "600519",
                                    "company_name": "贵州茅台", "report_date": "2024-09-30",
                                    "metric_names": ["revenue", "net_profit", "roe"]}),
            "model": "deepseek-chat",
            "usage": {"prompt_tokens": 100, "completion_tokens": 30},
        }
        with patch("agents.intent_classifier.classifier.get_llm_service", return_value=mock_llm):
            result = await classify_intent("分析茅台2024Q3的盈利能力")
            assert result.intent == "financial_analysis"
            assert result.company_code == "600519"
            assert "roe" in result.metric_names

    @pytest.mark.asyncio
    async def test_simple_query_intent(self):
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = {
            "content": json.dumps({"intent": "simple_query", "company_code": "600519",
                                    "company_name": "贵州茅台", "report_date": "",
                                    "metric_names": ["pe"]}),
            "model": "deepseek-chat",
            "usage": {"prompt_tokens": 80, "completion_tokens": 20},
        }
        with patch("agents.intent_classifier.classifier.get_llm_service", return_value=mock_llm):
            result = await classify_intent("茅台PE多少")
            assert result.intent == "simple_query"

    @pytest.mark.asyncio
    async def test_fallback_on_json_error(self):
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = {
            "content": "这是一些废话 {invalid json}",
            "model": "deepseek-chat",
            "usage": {"prompt_tokens": 50, "completion_tokens": 10},
        }
        with patch("agents.intent_classifier.classifier.get_llm_service", return_value=mock_llm):
            result = await classify_intent("测试消息")
            assert result.intent == "comprehensive"

    @pytest.mark.asyncio
    async def test_name_to_code_mapping(self):
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = {
            "content": json.dumps({"intent": "sentiment_analysis", "company_code": "",
                                    "company_name": "宁德时代", "report_date": "",
                                    "metric_names": []}),
            "model": "deepseek-chat",
            "usage": {"prompt_tokens": 80, "completion_tokens": 20},
        }
        with patch("agents.intent_classifier.classifier.get_llm_service", return_value=mock_llm):
            result = await classify_intent("宁德时代最近怎么样")
            assert result.company_code == "300750"


class TestIntentClassifierNode:
    @pytest.mark.asyncio
    async def test_node_sets_intent_and_status(self):
        state = make_initial_state("task-001")
        state["company_code"] = "600519"
        state["intent"] = "financial_analysis"
        result = await intent_classifier_node(state)
        assert result["status"] == "running"
        assert result["intent"] == "financial_analysis"

    @pytest.mark.asyncio
    async def test_node_defaults_to_comprehensive_when_no_input(self):
        state = make_initial_state("task-002")
        result = await intent_classifier_node(state)
        assert result["intent"] == "comprehensive"
        assert result["status"] == "running"
