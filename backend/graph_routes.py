import structlog
from state import AgentState

logger = structlog.get_logger()


def route_after_collect(state: AgentState) -> str:
    """数据收集节点后——根据 intent 分发"""
    intent = state.get("intent", "comprehensive")
    if state.get("raw_data") is None:
        logger.info("route_after_collect_no_data")
        return "output"
    logger.info("route_after_collect", intent=intent)
    match intent:
        case "simple_query":
            return "output"
        case "financial_analysis":
            return "financial_analyzer"
        case "sentiment_analysis":
            return "sentiment_analyzer"
        case "comprehensive":
            return "financial_analyzer"
        case _:
            return "financial_analyzer"


def route_after_financial(state: AgentState) -> str:
    """财务分析节点后——快速分析通道直接输出，comprehensive 继续"""
    intent = state.get("intent", "comprehensive")
    logger.info("route_after_financial", intent=intent)
    if intent == "financial_analysis":
        return "output"
    else:
        return "sentiment_analyzer"


def route_after_sentiment(state: AgentState) -> str:
    """舆情节点后——comprehensive 进入报告生成"""
    intent = state.get("intent", "comprehensive")
    logger.info("route_after_sentiment", intent=intent)
    if intent == "sentiment_analysis":
        return "output"
    else:
        return "report_generator"
