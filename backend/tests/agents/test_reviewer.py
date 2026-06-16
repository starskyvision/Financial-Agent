import pytest
import re
from unittest.mock import AsyncMock, patch
from state import make_initial_state
from agents.reviewer.fact_checker import verify_facts
from agents.reviewer.report_generator import report_generator_node
from agents.reviewer.router import route_after_review


class TestFactChecker:
    @pytest.mark.asyncio
    async def test_no_db_session_returns_empty(self):
        report = "ROE为12.3%，净利润50亿元，营收100亿元"
        errors = await verify_facts(report, "600519", db_session=None)
        assert errors == []

    @pytest.mark.asyncio
    async def test_extracts_numerical_claims(self):
        report = "ROE为12.3%，净利润56.78亿元"
        pattern = r'(净利润|营收)[^\d]*(\d+\.?\d*)\s*[亿元]'
        matches = list(re.finditer(pattern, report))
        assert len(matches) == 1
        assert matches[0].group(1) == "净利润"
        assert matches[0].group(2) == "56.78"


class TestReportGenerator:
    @pytest.mark.asyncio
    async def test_generates_report(self):
        state = make_initial_state("task-001")
        state["company_code"] = "600519"
        state["company_name"] = "贵州茅台"
        state["financial_analysis"] = {
            "dupont_decomposition": {"roe": 0.25, "net_margin": 0.50, "asset_turnover": 0.25,
                                      "equity_multiplier": 2.0, "is_valid": True},
            "anomaly_flags": [], "narrative": "茅台Q3盈利表现强劲", "analyst_confidence": "high",
        }
        state["sentiment_result"] = {
            "overall_sentiment": "positive", "overall_score": 0.72,
            "key_topics": ["业绩增长"], "summary": "舆情正面",
        }
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = {"content": "# 贵州茅台投研分析报告\n\n## 核心摘要\n...",
                                         "model": "deepseek-chat",
                                         "usage": {"prompt_tokens": 500, "completion_tokens": 800}}
        with patch("agents.reviewer.report_generator.get_llm_service", return_value=mock_llm):
            result = await report_generator_node(state)
            assert result["draft_report"] is not None
            assert len(result["draft_report"]) > 0

    @pytest.mark.asyncio
    async def test_handles_no_analysis_data(self):
        state = make_initial_state("task-002")
        result = await report_generator_node(state)
        assert "无法生成报告" in result.get("draft_report", "")


class TestRouting:
    def test_route_to_rewriter_when_errors_and_retry_under_3(self):
        state = make_initial_state("task-001")
        state["errors"] = ["ROE: 报告值 0.12，源数据 0.10"]
        state["retry_count"] = 0
        assert route_after_review(state) == "rewriter"

    def test_route_to_output_when_no_errors(self):
        state = make_initial_state("task-001")
        state["errors"] = []
        state["retry_count"] = 0
        assert route_after_review(state) == "output"

    def test_route_to_output_when_retry_exhausted(self):
        state = make_initial_state("task-001")
        state["errors"] = ["ROE: 偏差 0.02"]
        state["retry_count"] = 3
        state["draft_report"] = "report content"
        result = route_after_review(state)
        assert result == "output"
        assert "自动校验未完全通过" in state["draft_report"]
