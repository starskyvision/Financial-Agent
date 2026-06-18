"""
AgentState + 核心类型定义 —— 单元测试
"""

import pytest
from state import (IntentResult, DupontResult, Anomaly,
                   SentimentDetail, SentimentResult, make_initial_state)


class TestIntentResult:
    def test_valid_intent(self):
        r = IntentResult(intent="financial_analysis", company_code="600519")
        assert r.intent == "financial_analysis"

    def test_unknown_intent_is_accepted_as_string(self):
        # Pydantic str 字段无约束时接受任意字符串值
        r = IntentResult(intent="unknown", company_code="")
        assert r.intent == "unknown"


class TestDupontResult:
    def test_compute_roe(self):
        d = DupontResult(roe=0.15, net_margin=0.50, asset_turnover=0.20,
                         equity_multiplier=1.5, is_valid=True)
        # ROE ≈ net_margin * asset_turnover * equity_multiplier = 0.50*0.20*1.5 = 0.15
        assert abs(d.roe - (d.net_margin * d.asset_turnover * d.equity_multiplier)) < 0.01

    def test_invalid_when_missing_metrics(self):
        d = DupontResult(roe=0, net_margin=0, asset_turnover=0, equity_multiplier=0,
                         is_valid=False, missing_metrics=["revenue"])
        assert not d.is_valid
        assert "revenue" in d.missing_metrics


class TestAnomaly:
    def test_warning_severity(self):
        a = Anomaly(metric_name="revenue", current_value=100,
                    yoy_value=70, change_pct=0.30, severity="warning")
        assert a.severity == "warning"

    def test_critical_severity(self):
        a = Anomaly(metric_name="net_profit", current_value=50,
                    yoy_value=100, change_pct=-0.50, severity="critical")
        assert a.severity == "critical"


class TestSentimentDetail:
    def test_create_sentiment_detail(self):
        d = SentimentDetail(title="利好新闻", sentiment="positive", score=0.85)
        assert d.title == "利好新闻"
        assert d.sentiment == "positive"
        assert d.score == 0.85
        assert d.reasoning == ""


class TestSentimentResult:
    def test_create_sentiment_result(self):
        details = [
            SentimentDetail(title="新闻1", sentiment="positive", score=0.9),
            SentimentDetail(title="新闻2", sentiment="negative", score=0.2),
        ]
        r = SentimentResult(
            overall_sentiment="positive",
            overall_score=0.65,
            positive_count=1,
            neutral_count=0,
            negative_count=1,
            key_topics=["业绩", "市场"],
            summary="整体偏正面",
            details=details,
        )
        assert r.overall_sentiment == "positive"
        assert r.positive_count == 1
        assert len(r.details) == 2
        assert r.details[0].sentiment == "positive"


class TestMakeInitialState:
    def test_initial_state_defaults(self):
        state = make_initial_state("task-001")
        assert state["task_id"] == "task-001"
        assert state["status"] == "pending"
        assert state["intent"] == ""
        assert state["errors"] == []
        assert state["retry_count"] == 0
        assert state["raw_data"] is None

    def test_initial_state_with_company(self):
        state = make_initial_state("task-002", company_code="600519", report_date="2024-12-31")
        assert state["task_id"] == "task-002"
        assert state["company_code"] == "600519"
        assert state["report_date"] == "2024-12-31"
        assert state["status"] == "pending"
