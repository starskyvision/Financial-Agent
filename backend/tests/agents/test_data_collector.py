import pytest
from unittest.mock import AsyncMock, patch
from state import make_initial_state
from agents.data_collector.node import data_collector_node


class TestDataCollectorNode:
    @pytest.mark.asyncio
    async def test_node_fetches_data(self):
        state = make_initial_state("task-001")
        state["company_code"] = "600519"
        state["report_date"] = "2024-09-30"
        state["intent"] = "financial_analysis"

        mock_adapter = AsyncMock()
        mock_adapter.fetch_financials.return_value = {"revenue": 100.0, "net_profit": 50.0}
        mock_adapter.fetch_news.return_value = [{"title": "茅台Q3业绩"}]
        mock_adapter.fetch_documents.return_value = []

        with patch("agents.data_collector.node.create_data_source", return_value=mock_adapter):
            result = await data_collector_node(state)
            assert result["raw_data"] is not None
            assert result["raw_data"]["financial_metrics"]["revenue"] == 100.0
            assert len(result["raw_data"]["news_headlines"]) == 1

    @pytest.mark.asyncio
    async def test_node_handles_partial_failure(self):
        state = make_initial_state("task-002")
        state["company_code"] = "000858"
        state["intent"] = "sentiment_analysis"

        mock_adapter = AsyncMock()
        mock_adapter.fetch_financials.side_effect = Exception("timeout")
        mock_adapter.fetch_news.return_value = [{"title": "五粮液提价"}]
        mock_adapter.fetch_documents.return_value = []

        with patch("agents.data_collector.node.create_data_source", return_value=mock_adapter):
            result = await data_collector_node(state)
            assert result["raw_data"] is not None
            assert result["raw_data"]["financial_metrics"] == {}
            assert len(result["raw_data"]["news_headlines"]) == 1
            assert any("财务数据" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_node_errors_on_empty_code(self):
        state = make_initial_state("task-003")
        state["company_code"] = ""
        result = await data_collector_node(state)
        assert result["raw_data"] is None
        assert any("company_code" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_node_skips_docs_for_simple_query(self):
        state = make_initial_state("task-004")
        state["company_code"] = "600519"
        state["intent"] = "simple_query"

        mock_adapter = AsyncMock()
        mock_adapter.fetch_financials.return_value = {"revenue": 100.0}
        mock_adapter.fetch_news.return_value = []

        with patch("agents.data_collector.node.create_data_source", return_value=mock_adapter):
            result = await data_collector_node(state)
            mock_adapter.fetch_documents.assert_not_called()
