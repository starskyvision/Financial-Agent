import json
import structlog
from state import AgentState
from constants.metrics import METRIC_LABELS, PERCENT_FORMAT_METRICS

logger = structlog.get_logger()

SENTIMENT_LABELS = {"positive": "积极", "neutral": "中性", "negative": "消极"}


def _format_metrics(metrics: dict, company: str) -> str:
    """格式化财务指标为 Markdown"""
    parts = [f"## {company} 关键财务指标\n"]
    displayed = 0
    for k, v in metrics.items():
        if v is not None:
            label = METRIC_LABELS.get(k, k)
            if k in PERCENT_FORMAT_METRICS:
                parts.append(f"- {label}: **{v*100:.1f}%**")
            else:
                parts.append(f"- {label}: **{v:.2f}**")
            displayed += 1
    if displayed == 0:
        parts.append("暂无可用数据")
    parts.append("")
    return "\n".join(parts)


def _format_sentiment(sent: dict) -> str:
    """格式化舆情结果为 Markdown"""
    parts = ["## 舆情分析\n"]
    overall = sent.get("overall_sentiment", "neutral")
    score = sent.get("overall_score", 0.5)
    summary = sent.get("summary", "")
    topics = sent.get("key_topics", [])
    details = sent.get("details", [])

    label = SENTIMENT_LABELS.get(overall, overall)
    parts.append(f"**整体倾向: {label}** (评分: {score:.1f})\n")
    if topics:
        parts.append(f"**关键主题**: {', '.join(topics)}\n")
    if summary:
        parts.append(f"\n{summary}\n")
    if details:
        parts.append("\n**代表性新闻**:\n")
        for d in details[:5]:
            s_label = SENTIMENT_LABELS.get(d.get("sentiment", ""), d.get("sentiment", ""))
            parts.append(f"- [{s_label}] {d.get('title', '')}")
            if d.get("reasoning"):
                parts.append(f"  > {d['reasoning']}")
            parts.append("")

    return "\n".join(parts)


def _format_simple(raw: dict, company: str) -> str:
    """格式化简单查询的回答"""
    metrics = raw.get("financial_metrics", {})
    if not metrics:
        return "暂无相关数据。"
    lines = []
    for k, v in metrics.items():
        if v is not None:
            label = METRIC_LABELS.get(k, k)
            if k in PERCENT_FORMAT_METRICS:
                lines.append(f"- {label}: **{v*100:.1f}%**")
            else:
                lines.append(f"- {label}: **{v:.2f}**")
    if not lines:
        return f"{company} 暂无可用数据。"
    return f"## {company}\n" + "\n".join(lines)


def _format_market_data(market: dict) -> str:
    """格式化市场行情数据"""
    mtype = market.get("type", "")
    if mtype == "exchange_rate":
        pair = market.get("pair", "")
        inverted = market.get("inverted", False)
        if inverted:
            # 解析 pair 如 "100JPY/CNY" → 显示 "CNY/JPY"
            parts = pair.replace("100", "").split("/")
            if len(parts) == 2:
                pair = f"{parts[1]}/{parts[0]}"
        return (
            f"## 汇率 {pair}\n\n"
            f"- 买入价: **{market.get('bid', 0):.4f}**\n"
            f"- 卖出价: **{market.get('ask', 0):.4f}**\n"
        )
    elif mtype == "commodity_price":
        change = market.get("change_pct", 0)
        sign = "+" if change >= 0 else ""
        return (
            f"## {market.get('label', '大宗商品')}\n\n"
            f"- 最新价: **{market.get('price', 0):.2f}**\n"
            f"- 涨跌幅: **{sign}{change:.2f}%**\n"
            f"\n> 数据来源: 全球期货市场"
        )
    elif mtype == "oil_price":
        change = market.get("change_pct", 0)
        sign = "+" if change >= 0 else ""
        return (
            f"## 原油价格\n\n"
            f"- 品种: {market.get('label', 'NYMEX WTI')}\n"
            f"- 最新价: **{market.get('price', 0):.2f}** {market.get('unit', '美元/桶')}\n"
            f"- 涨跌幅: **{sign}{change:.2f}%**\n"
            f"\n> 数据来源: 全球期货市场"
        )
    elif mtype == "gold_price":
        return (
            f"## 黄金价格\n\n"
            f"- 品种: {market.get('label', 'Au99.99')}\n"
            f"- 日期: {market.get('date', '')}\n"
            f"- 开盘价: **{market.get('open', 0):.2f}** {market.get('unit', '元/克')}\n"
            f"- 收盘价: **{market.get('close', 0):.2f}** {market.get('unit', '元/克')}\n"
            f"\n> 数据来源: 上海黄金交易所"
        )
    elif mtype == "stock_price":
        change = market.get("change_pct", 0)
        sign = "+" if change >= 0 else ""
        mkt = market.get("market", "")
        if mkt == "US":
            currency = "美元"
        elif mkt == "HK":
            currency = "港元"
        else:
            currency = "元"
        market_names = {"US": "美股", "HK": "港股", "A": "A股"}
        lines = [
            f"## {market.get('name', '')}（{market.get('code', '')}）",
            f"日期: {market.get('date', '')} | 市场: {market_names.get(mkt, mkt)}",
            f"",
            f"- 收盘价: **{market.get('price', 0):.2f}** {currency}",
            f"- 涨跌幅: **{sign}{change:.2f}%**",
        ]
        if "open" in market:
            lines.append(f"- 开盘价: {market['open']:.2f}")
            lines.append(f"- 最高价: {market['high']:.2f}")
            lines.append(f"- 最低价: {market['low']:.2f}")
        lines.append(f"- 成交量: {market.get('volume', 0):.0f} 股")
        lines.append(f"- 成交额: {market.get('amount', 0):.2f} {currency}")
        return "\n".join(lines)
    return f"## {mtype}\n\n{json.dumps(market, ensure_ascii=False)}"


async def output_node(state: AgentState) -> AgentState:
    logger.info("output_node_start", task_id=state.get("task_id"), intent=state.get("intent"))
    intent = state.get("intent", "comprehensive")
    company = state.get("company_name") or state.get("company_code", "")

    if intent == "comprehensive":
        state["chat_reply"] = state.get("draft_report", "")

    elif intent == "simple_query":
        raw = state.get("raw_data") or {}
        market = raw.get("market_data", {})
        if market:
            state["chat_reply"] = _format_market_data(market)
        else:
            state["chat_reply"] = _format_simple(raw, company)

    elif intent == "sentiment_analysis":
        # 只显示舆情，不显示财务指标
        parts = [f"## {company} 舆情分析\n"]
        sent = state.get("sentiment_result")
        if sent and sent.get("summary"):
            parts.append(_format_sentiment(sent))
        else:
            parts.append("暂无可用舆情数据。")
        state["chat_reply"] = "\n".join(parts)

    elif intent == "financial_analysis":
        # 显示财务指标 + 分析评述
        raw = state.get("raw_data") or {}
        metrics = raw.get("financial_metrics", {})
        if metrics:
            state["chat_reply"] = _format_metrics(metrics, company)
        fin = state.get("financial_analysis")
        if fin and fin.get("narrative"):
            state["chat_reply"] = (state.get("chat_reply", "") or "") + "\n" + fin["narrative"]

    else:
        state["chat_reply"] = "无法处理该请求，请提供股票代码或公司名称。"

    if not state.get("chat_reply"):
        state["chat_reply"] = "未能获取到相关数据，请稍后重试。"

    state["status"] = "done"
    logger.info("output_node_done", reply_length=len(state.get("chat_reply", "")))
    return state
