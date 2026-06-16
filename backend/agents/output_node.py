import structlog
from state import AgentState

logger = structlog.get_logger()


async def output_node(state: AgentState) -> AgentState:
    logger.info("output_node_start", task_id=state.get("task_id"), intent=state.get("intent"))
    intent = state.get("intent", "comprehensive")

    if intent == "comprehensive":
        state["chat_reply"] = state.get("draft_report", "")
    else:
        parts = []
        raw = state.get("raw_data") or {}
        metrics = raw.get("financial_metrics", {})

        # 指标中文名映射
        METRIC_LABELS = {
            "revenue": "营收(亿)", "net_profit": "净利润(亿)", "roe": "ROE",
            "gross_margin": "毛利率", "net_margin": "净利率",
            "debt_ratio": "资产负债率", "equity_ratio": "产权比率",
            "operating_cashflow_per_share": "每股经营现金流",
        }

        if metrics:
            company = state.get("company_name") or state.get("company_code", "")
            parts.append(f"## {company} 关键财务指标\n")
            displayed = 0
            for k, v in metrics.items():
                if v is not None:
                    label = METRIC_LABELS.get(k, k)
                    if k in ("roe", "gross_margin", "net_margin", "debt_ratio"):
                        parts.append(f"- {label}: **{v*100:.1f}%**")
                    else:
                        parts.append(f"- {label}: **{v:.2f}**")
                    displayed += 1
            if displayed == 0:
                parts.append("暂无可用数据")
            parts.append("")

        fin = state.get("financial_analysis")
        if fin and fin.get("narrative"):
            parts.append(fin["narrative"])

        sent = state.get("sentiment_result")
        if sent and sent.get("summary"):
            parts.append(f"\n### 舆情概况\n{sent['summary']}")

        if not parts:
            parts.append("未能获取到相关数据，请稍后重试。")

        state["chat_reply"] = "\n".join(parts)

    state["status"] = "done"
    logger.info("output_node_done", reply_length=len(state.get("chat_reply", "")))
    return state
