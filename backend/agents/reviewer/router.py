import os
import structlog
from state import AgentState

logger = structlog.get_logger()
MAX_REWRITE_RETRIES = int(os.getenv("MAX_RETRY_ROUNDS", "3"))


def route_after_review(state: AgentState) -> str:
    errors = state.get("errors", [])
    retry = state.get("retry_count", 0)
    # 与上一轮相同的错误不再重试（反思循环无法修复）
    prev = state.get("prev_fact_errors", [])
    new_errors = [e for e in errors if e not in prev]
    state["prev_fact_errors"] = errors

    if new_errors and retry < MAX_REWRITE_RETRIES:
        logger.info("route_to_rewriter", new=len(new_errors), unchanged=len(errors)-len(new_errors), retry=retry)
        return "rewriter"
    else:
        if errors and not new_errors:
            logger.info("route_to_output_stale_errors", unchanged=len(errors), retry=retry)
        elif errors and retry >= MAX_REWRITE_RETRIES:
            logger.warning("route_to_output_with_errors", remaining=len(errors))
        logger.info("route_to_output", retry=retry)
        return "output"
