import asyncio
import re
import structlog
from datetime import datetime, timedelta
from services.data_sources import create_data_source
from services.data_sources.base import DataSourceConfig
from services.env import env_str, env_int
from constants.metrics import DEFAULT_METRICS_FETCH, SIMPLE_QUERY_METRICS
from state import AgentState

logger = structlog.get_logger()

# --- Configurable settings (env vars with defaults) ---
DATA_SOURCE_TYPE = env_str("DATA_SOURCE", "akshare")
FETCH_TIMEOUT = env_int("FETCH_TIMEOUT", "30")
NEWS_LOOKBACK_DAYS = env_int("NEWS_LOOKBACK_DAYS", "30")
DOC_FETCH_LIMIT = env_int("DOC_FETCH_LIMIT", "5")


def _parse_date_range(report_date: str) -> tuple[datetime | None, datetime | None]:
    """Parse report_date into a (start, end) datetime range for news filtering.
    Returns (None, None) if no meaningful date constraint can be derived.
    """
    if not report_date or not report_date.strip():
        return None, None

    d = report_date.strip()
    # YYYY-MM: full month
    m = re.match(r'^(\d{4})-(\d{2})$', d)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        start = datetime(y, mo, 1)
        if mo == 12:
            end = datetime(y + 1, 1, 1) - timedelta(days=1)
        else:
            end = datetime(y, mo + 1, 1) - timedelta(days=1)
        return start, end
    # YYYY-MM-DD: single day
    if re.match(r'^\d{4}-\d{2}-\d{2}$', d):
        dt = datetime.strptime(d, "%Y-%m-%d")
        return dt, dt + timedelta(days=1) - timedelta(seconds=1)
    # YYYYQ[1-4]: quarter
    m = re.match(r'^(\d{4})Q([1-4])$', d, re.IGNORECASE)
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        start_month = (q - 1) * 3 + 1
        start = datetime(y, start_month, 1)
        end_month = q * 3
        if end_month == 12:
            end = datetime(y + 1, 1, 1) - timedelta(days=1)
        else:
            end = datetime(y, end_month + 1, 1) - timedelta(days=1)
        return start, end
    return None, None


def _news_in_range(published_at: str, start: datetime, end: datetime) -> bool:
    """Check if a news item's published_at falls within [start, end]."""
    if not published_at:
        return False
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(published_at[:19] if len(published_at) >= 19 else published_at[:10], fmt)
            return start <= dt <= end
        except ValueError:
            continue
    return False


def _compute_news_lookback(report_date: str, default_days: int = NEWS_LOOKBACK_DAYS) -> int:
    """根据 report_date 动态计算新闻回看天数。

    例如用户请求"4月份的新闻"，report_date="2026-04"，
    则回看天数应为 (今天 - 2026-04-30) + 30天缓冲。
    """
    if not report_date or not report_date.strip():
        return default_days

    d = report_date.strip()
    target_end = None

    # YYYY-MM: month-level → end of that month
    m = re.match(r'^(\d{4})-(\d{2})$', d)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        # last day of the month
        if mo == 12:
            target_end = datetime(y + 1, 1, 1) - timedelta(days=1)
        else:
            target_end = datetime(y, mo + 1, 1) - timedelta(days=1)
    # YYYY-MM-DD: exact date
    elif re.match(r'^\d{4}-\d{2}-\d{2}$', d):
        target_end = datetime.strptime(d, "%Y-%m-%d")
    # YYYYQ[1-4]: quarter → last day of quarter
    elif re.match(r'^\d{4}Q[1-4]$', d, re.IGNORECASE):
        y, q = int(d[:4]), int(d[5])
        last_month = q * 3
        if last_month == 12:
            target_end = datetime(y + 1, 1, 1) - timedelta(days=1)
        else:
            target_end = datetime(y, last_month + 1, 1) - timedelta(days=1)

    if target_end is None:
        return default_days

    # Days from target_end to now + 30-day buffer for the full period
    days_ago = (datetime.now() - target_end).days
    return max(days_ago + 30, default_days)


async def data_collector_node(state: AgentState) -> AgentState:
    logger.info("data_collector_node_start", task_id=state.get("task_id"),
                code=state.get("company_code"))

    try:
        return await _data_collector_impl(state)
    except Exception as e:
        logger.error("data_collector_node_fatal", error=str(e))
        state["errors"].append(f"数据收集节点异常: {str(e)}")
        state["raw_data"] = None
        return state


async def _data_collector_impl(state: AgentState) -> AgentState:

    intent = state.get("intent", "comprehensive")
    code = state.get("company_code", "")
    date = state.get("report_date", "")
    query_type = state.get("query_type", "")

    config = DataSourceConfig(source_type=DATA_SOURCE_TYPE, timeout=FETCH_TIMEOUT)
    adapter = create_data_source(config)

    # --- 自动检测美股 ticker（使用 AKShareAdapter 的验证方法） ---
    if not query_type and code:
        from services.data_sources.akshare_adapter import AKShareAdapter
        if AKShareAdapter._is_us_stock(code):
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

    news_lookback_days = _compute_news_lookback(date)
    financials_task = adapter.fetch_financials(code, date, metrics)
    news_task = adapter.fetch_news(code, days=news_lookback_days)

    # ── 新闻日期过滤：若用户指定了月份/日期，只保留该时间段的新闻 ──
    _target_start, _target_end = _parse_date_range(date)

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

    # ── 按用户指定日期过滤新闻 ──
    if isinstance(news, list) and _target_start and _target_end:
        filtered_news = [
            n for n in news
            if _news_in_range(n.get("published_at", ""), _target_start, _target_end)
        ]
        if filtered_news:
            logger.info("news_date_filtered",
                        before=len(news), after=len(filtered_news),
                        range=f"{_target_start.date()}~{_target_end.date()}")
            news = filtered_news
        else:
            logger.info("news_date_filter_empty",
                        total=len(news),
                        range=f"{_target_start.date()}~{_target_end.date()}")

    state["raw_data"] = {
        "financial_metrics": financials if isinstance(financials, dict) else {},
        "news_headlines": news if isinstance(news, list) else [],
        "doc_snippets": docs if isinstance(docs, list) else [],
        "data_sources": [DATA_SOURCE_TYPE],
        "fetched_at": datetime.now().isoformat(),
    }
    state["errors"].extend(errors)

    logger.info("data_collector_node_done",
                metrics_count=len(state["raw_data"]["financial_metrics"]),
                news_count=len(state["raw_data"]["news_headlines"]),
                errors=len(errors))
    return state
