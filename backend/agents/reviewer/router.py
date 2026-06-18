import os
import structlog
from state import AgentState

logger = structlog.get_logger()
MAX_REWRITE_RETRIES = int(os.getenv("MAX_RETRY_ROUNDS", "3"))


def route_after_review(state: AgentState) -> str:
    errors = state.get("errors", [])
    retry = state.get("retry_count", 0)
    if errors and retry < MAX_REWRITE_RETRIES:
        logger.info("route_to_rewriter", errors=len(errors), retry=retry)
        return "rewriter"
    else:
        if errors and retry >= MAX_REWRITE_RETRIES:
            warning = f"\n\n---\n\n⚠️ **自动校验未完全通过**\n\n以下数据项在 {MAX_REWRITE_RETRIES} 轮校验后仍与源数据库存在偏差：\n\n"
            for e in errors:
                warning += f"- {e}\n"
            warning += "\n请人工复核上述数据。"
            state["draft_report"] = (state.get("draft_report", "") + warning)
            logger.warning("route_to_output_with_errors", remaining=len(errors))
        logger.info("route_to_output", retry=retry)
        return "output"
