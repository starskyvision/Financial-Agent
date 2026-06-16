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
        if metrics:
            parts.append(f"### {state.get('company_name', state.get('company_code', ''))} 财务数据\n")
            for k, v in metrics.items():
                if v is not None:
                    parts.append(f"- {k}: {v}")
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
