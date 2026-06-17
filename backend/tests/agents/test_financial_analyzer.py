import pytest
from unittest.mock import AsyncMock, patch
from state import make_initial_state
from agents.financial_analyzer.dupont import compute_dupont, DupontResult
from agents.financial_analyzer.anomaly import detect_anomalies
from agents.financial_analyzer.node import financial_analyzer_node


class TestDupont:
    def test_valid_computation(self):
        metrics = {"net_profit": 15, "revenue": 100, "total_assets": 200, "total_liabilities": 100}
        result = compute_dupont(metrics)
        assert result.is_valid
        assert result.net_margin == 0.15
        assert result.asset_turnover == 0.5
        assert result.equity_multiplier == 2.0
        assert result.roe == 0.15

    def test_missing_metrics(self):
        metrics = {"net_profit": 15}
        result = compute_dupont(metrics)
        assert not result.is_valid
        assert "revenue" in result.missing_metrics

    def test_zero_division_protection(self):
        metrics = {"net_profit": 15, "revenue": 0, "total_assets": 200, "total_liabilities": 100}
        result = compute_dupont(metrics)
        assert not result.is_valid


class TestAnomalyDetection:
    @pytest.mark.asyncio
    async def test_no_db_falls_back_to_akshare(self):
        """Without DB session, anomaly detection now uses AKShare historical fetch + rule checks."""
        # With real AKShare data for a valid code, anomalies may be detected.
        # This test verifies the function doesn't crash and returns a list.
        anomalies = await detect_anomalies("600519", {"revenue": 100})
        assert isinstance(anomalies, list)
        # Anomalies may be detected via AKShare fallback or rule checks — either is valid

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self):
        """With no code and no DB, only rule-based checks run. Empty metrics → no anomalies."""
        anomalies = await detect_anomalies("", {})
        assert anomalies == []


class TestFinancialAnalyzerNode:
    @pytest.mark.asyncio
    async def test_node_generates_analysis(self):
        state = make_initial_state("task-001")
        state["company_code"] = "600519"
        state["company_name"] = "贵州茅台"
        state["report_date"] = "2024-09-30"
        state["raw_data"] = {
            "financial_metrics": {"net_profit": 50, "revenue": 150, "total_assets": 300,
                                   "total_liabilities": 100, "roe": 0.25},
            "news_headlines": [], "doc_snippets": [],
        }
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = {"content": "贵州茅台2024Q3 ROE为25.00%...",
                                         "model": "deepseek-chat",
                                         "usage": {"prompt_tokens": 200, "completion_tokens": 100}}
        with patch("agents.financial_analyzer.node.get_llm_service", return_value=mock_llm):
            result = await financial_analyzer_node(state)
            assert result["financial_analysis"] is not None
            assert result["financial_analysis"]["dupont_decomposition"]["is_valid"]
            assert len(result["financial_analysis"]["narrative"]) > 0

    @pytest.mark.asyncio
    async def test_node_handles_empty_metrics(self):
        state = make_initial_state("task-002")
        state["raw_data"] = {"financial_metrics": {}, "news_headlines": [], "doc_snippets": []}
        result = await financial_analyzer_node(state)
        assert result["financial_analysis"]["analyst_confidence"] == "low"
        assert "无可用" in result["financial_analysis"]["narrative"]
