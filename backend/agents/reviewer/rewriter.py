import structlog
from state import AgentState
from services.llm_service import get_llm_service

logger = structlog.get_logger()

REWRITE_SYSTEM_PROMPT = """你是一个严谨的金融报告校对专家。请修正以下报告中与源数据不符的部分。

要求：
1. 仅修正错误列表中指出的数据项（数值、百分比），不改动其他内容
2. 保持报告原有的结构和语言风格
3. 如果某个错误无法确定正确值，标注"[待核实]"
4. 修正后直接输出完整报告，不要添加解释说明"""


async def rewriter_node(state: AgentState) -> AgentState:
    logger.info("rewriter_node_start", task_id=state.get("task_id"),
                retry=state.get("retry_count", 0),
                errors=len(state.get("errors", [])))

    draft = state.get("draft_report", "")
    errors = state.get("errors", [])

    # Clear rewriter-origin errors from previous cycles to avoid stale retry triggers
    state["errors"] = [e for e in errors if not e.startswith("报告重写失败")]

    if not draft or not state["errors"]:
        logger.info("rewriter_skip", reason="no draft or no errors")
        return state

    state["retry_count"] = state.get("retry_count", 0) + 1

    try:
        error_block = "\n".join(f"- {e}" for e in errors)
        user_prompt = (
            f"以下报告中存在与源数据不匹配的数据项，请修正：\n\n"
            f"## 需要修正的数据项\n{error_block}\n\n"
            f"## 当前报告\n{draft}"
        )

        llm = get_llm_service()
        result = await llm.invoke("reviewer", [
            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ])

        rewritten = result.get("content", "")
        if rewritten and len(rewritten) > 50:
            state["draft_report"] = rewritten
            logger.info("rewriter_node_done", length=len(rewritten))
        else:
            logger.warning("rewriter_empty_response")

    except Exception as e:
        logger.error("rewriter_error", error=str(e))
        state["errors"].append(f"报告重写失败: {str(e)}")

    return state
