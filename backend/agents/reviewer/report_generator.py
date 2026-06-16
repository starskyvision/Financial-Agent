import structlog
from state import AgentState
from services.llm_service import get_llm_service
from prompts.report_generation import REPORT_GENERATION_SYSTEM, build_report_prompt

logger = structlog.get_logger()


async def report_generator_node(state: AgentState) -> AgentState:
    logger.info("report_generator_node_start", task_id=state.get("task_id"))
    fin = state.get("financial_analysis")
    sent = state.get("sentiment_result")

    if not fin and not sent:
        state["errors"].append("报告生成跳过: 无分析数据")
        state["draft_report"] = "无法生成报告: 财务分析和舆情分析数据均不可用。"
        return state

    try:
        retry_context = ""
        if state.get("errors") and state.get("retry_count", 0) > 0:
            retry_context = "以下数据在上次报告中与源数据不匹配，请修正：\n" + "\n".join(
                f"  - {e}" for e in state["errors"]
            )

        prompt = build_report_prompt(state, retry_context)
        llm = get_llm_service()
        result = await llm.invoke("reviewer", [
            {"role": "system", "content": REPORT_GENERATION_SYSTEM},
            {"role": "user", "content": prompt},
        ])
        state["draft_report"] = result.get("content", "")
        logger.info("report_generator_node_done", length=len(state["draft_report"]))
    except Exception as e:
        logger.error("report_generator_error", error=str(e))
        state["errors"].append(f"报告生成失败: {str(e)}")
        if state.get("draft_report") is None:
            state["draft_report"] = f"报告生成异常: {str(e)}"

    return state
