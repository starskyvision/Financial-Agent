import os
import asyncio
import structlog
from datetime import datetime
from services.data_sources import create_data_source
from services.data_sources.base import DataSourceConfig
from constants.metrics import DEFAULT_METRICS_FETCH, SIMPLE_QUERY_METRICS
from state import AgentState

logger = structlog.get_logger()

# --- Configurable settings (env vars with defaults) ---
DATA_SOURCE_TYPE = os.getenv("DATA_SOURCE", "akshare")
FETCH_TIMEOUT = int(os.getenv("FETCH_TIMEOUT", "30"))
NEWS_LOOKBACK_DAYS = int(os.getenv("NEWS_LOOKBACK_DAYS", "30"))
DOC_FETCH_LIMIT = int(os.getenv("DOC_FETCH_LIMIT", "5"))


async def data_collector_node(state: AgentState) -> AgentState:
    logger.info("data_collector_node_start", task_id=state.get("task_id"),
                code=state.get("company_code"))

    intent = state.get("intent", "comprehensive")
    code = state.get("company_code", "")
    date = state.get("report_date", "")
    query_type = state.get("query_type", "")

    config = DataSourceConfig(source_type=DATA_SOURCE_TYPE, timeout=FETCH_TIMEOUT)
    adapter = create_data_source(config)

    # --- 自动检测美股 ticker ---
    if not query_type and code and code.isalpha() and code.isupper():
        query_type = "stock_price"

    # --- 市场行情查询（金价/油价/股价/指数） ---
    MARKET_QUERY_TYPES = ("gold_price", "commodity_price", "exchange_rate", "stock_price", "index_price")
    if query_type in MARKET_QUERY_TYPES:
        target = state.get("query_target", "") or code or ""
        market_data = await adapter.fetch_market_data(query_type, target)
        if market_data:
            state["raw_data"] = {
                "financial_metrics": {},
                "news_headlines": [],
                "doc_snippets": [],
                "market_data": market_data,
                "data_sources": [DATA_SOURCE_TYPE],
                "fetched_at": datetime.now().isoformat(),
            }
            logger.info("data_collector_market_done", query_type=query_type)
        else:
            state["errors"].append(f"市场行情数据拉取失败: {query_type}")
            state["raw_data"] = None
        return state

    # --- 公司财务数据查询 ---
    if not code:
        state["errors"].append("数据收集失败: company_code 为空")
        state["raw_data"] = None
        return state

    if intent == "simple_query":
        metrics = SIMPLE_QUERY_METRICS
    else:
        metrics = DEFAULT_METRICS_FETCH

    financials_task = adapter.fetch_financials(code, date, metrics)
    news_task = adapter.fetch_news(code, days=NEWS_LOOKBACK_DAYS)

    if intent == "comprehensive":
        docs_task = adapter.fetch_documents(code, "announcement", limit=DOC_FETCH_LIMIT)
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
