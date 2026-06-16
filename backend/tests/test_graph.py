import pytest
from state import make_initial_state
from graph import build_graph
from graph_routes import route_after_collect, route_after_financial, route_after_sentiment


class TestRouteFunctions:
    def test_route_after_collect_simple_query(self):
        state = make_initial_state("task-001")
        state["intent"] = "simple_query"
        state["raw_data"] = {"financial_metrics": {"revenue": 100}}
        assert route_after_collect(state) == "output"

    def test_route_after_collect_financial(self):
        state = make_initial_state("task-001")
        state["intent"] = "financial_analysis"
        state["raw_data"] = {"financial_metrics": {"revenue": 100}}
        assert route_after_collect(state) == "financial_analyzer"

    def test_route_after_collect_sentiment(self):
        state = make_initial_state("task-001")
        state["intent"] = "sentiment_analysis"
        state["raw_data"] = {"financial_metrics": {}}
        assert route_after_collect(state) == "sentiment_analyzer"

    def test_route_after_collect_no_data(self):
        state = make_initial_state("task-001")
        state["raw_data"] = None
        assert route_after_collect(state) == "output"

    def test_route_after_financial_quick(self):
        state = make_initial_state("task-001")
        state["intent"] = "financial_analysis"
        assert route_after_financial(state) == "output"

    def test_route_after_financial_comprehensive(self):
        state = make_initial_state("task-001")
        state["intent"] = "comprehensive"
        assert route_after_financial(state) == "sentiment_analyzer"

    def test_route_after_sentiment_quick(self):
        state = make_initial_state("task-001")
        state["intent"] = "sentiment_analysis"
        assert route_after_sentiment(state) == "output"


class TestGraphBuild:
    def test_graph_compiles(self):
        graph = build_graph()
        assert graph is not None
        nodes = graph.get_graph().nodes
        assert len(nodes) > 0
