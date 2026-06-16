import structlog
from langgraph.graph import StateGraph, END
from state import AgentState

from agents.intent_classifier.node import intent_classifier_node
from agents.data_collector.node import data_collector_node
from agents.financial_analyzer.node import financial_analyzer_node
from agents.sentiment_analyzer.node import sentiment_analyzer_node
from agents.reviewer.report_generator import report_generator_node
from agents.reviewer.rewriter import rewriter_node
from agents.reviewer.router import route_after_review
from agents.output_node import output_node
from graph_routes import route_after_collect, route_after_financial, route_after_sentiment

logger = structlog.get_logger()


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("data_collector", data_collector_node)
    graph.add_node("financial_analyzer", financial_analyzer_node)
    graph.add_node("sentiment_analyzer", sentiment_analyzer_node)
    graph.add_node("report_generator", report_generator_node)
    graph.add_node("rewriter", rewriter_node)
    graph.add_node("output", output_node)

    graph.set_entry_point("intent_classifier")
    graph.add_edge("intent_classifier", "data_collector")

    graph.add_conditional_edges("data_collector", route_after_collect, {
        "output": "output",
        "financial_analyzer": "financial_analyzer",
        "sentiment_analyzer": "sentiment_analyzer",
    })

    graph.add_conditional_edges("financial_analyzer", route_after_financial, {
        "output": "output",
        "sentiment_analyzer": "sentiment_analyzer",
    })

    graph.add_conditional_edges("sentiment_analyzer", route_after_sentiment, {
        "output": "output",
        "report_generator": "report_generator",
    })

    graph.add_conditional_edges("report_generator", route_after_review, {
        "rewriter": "rewriter",
        "output": "output",
    })

    graph.add_edge("rewriter", "report_generator")
    graph.add_edge("output", END)

    logger.info("graph_built", nodes=7)
    return graph.compile()


app_graph = build_graph()
