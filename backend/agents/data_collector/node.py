import asyncio
import structlog
from datetime import datetime
from services.data_sources import create_data_source
from services.data_sources.base import DataSourceConfig
from state import AgentState

logger = structlog.get_logger()


async def data_collector_node(state: AgentState) -> AgentState:
    logger.info("data_collector_node_start", task_id=state.get("task_id"),
                code=state.get("company_code"))

    intent = state.get("intent", "comprehensive")
    code = state.get("company_code", "")
    date = state.get("report_date", "")

    if not code:
        state["errors"].append("数据收集失败: company_code 为空")
        state["raw_data"] = None
        return state

    config = DataSourceConfig(source_type="akshare", timeout=30)
    adapter = create_data_source(config)

    if intent == "simple_query":
        metrics = ["revenue", "net_profit"]
    else:
        metrics = [
            "revenue", "net_profit", "roe", "roa", "gross_margin",
            "net_margin", "operating_cashflow", "total_assets", "total_liabilities"
        ]

    financials_task = adapter.fetch_financials(code, date, metrics)
    news_task = adapter.fetch_news(code, days=30)

    if intent == "comprehensive":
        docs_task = adapter.fetch_documents(code, "announcement", limit=5)
        results = await asyncio.gather(financials_task, news_task, docs_task, return_exceptions=True)
    else:
        results = await asyncio.gather(financials_task, news_task, return_exceptions=True)
        results = [results[0], results[1], []]

    financials, news, docs = results[0], results[1], results[2]

    errors = []
    if isinstance(financials, Exception):
        logger.error("fetch_financials_failed", error=str(financials))
        errors.append(f"财务数据拉取失败: {str(financials)}")
        financials = {}
    if isinstance(news, Exception):
        logger.error("fetch_news_failed", error=str(news))
        errors.append(f"新闻拉取失败: {str(news)}")
        news = []
    if isinstance(docs, Exception):
        logger.error("fetch_docs_failed", error=str(docs))
        errors.append(f"文档拉取失败: {str(docs)}")
        docs = []

    state["raw_data"] = {
        "financial_metrics": financials if isinstance(financials, dict) else {},
        "news_headlines": news if isinstance(news, list) else [],
        "doc_snippets": docs if isinstance(docs, list) else [],
        "data_sources": ["akshare"],
        "fetched_at": datetime.now().isoformat(),
    }
    state["errors"].extend(errors)

    logger.info("data_collector_node_done",
                metrics_count=len(state["raw_data"]["financial_metrics"]),
                news_count=len(state["raw_data"]["news_headlines"]),
                errors=len(errors))
    return state
