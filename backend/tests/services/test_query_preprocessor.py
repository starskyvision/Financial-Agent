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
