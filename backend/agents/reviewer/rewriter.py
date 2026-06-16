import structlog
from state import AgentState

logger = structlog.get_logger()


async def rewriter_node(state: AgentState) -> AgentState:
    logger.info("rewriter_node_start", task_id=state.get("task_id"), retry=state.get("retry_count", 0))
    state["retry_count"] = state.get("retry_count", 0) + 1
    return state
