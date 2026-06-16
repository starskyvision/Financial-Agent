import structlog
from state import AgentState

logger = structlog.get_logger()


async def intent_classifier_node(state: AgentState) -> AgentState:
    logger.info("intent_classifier_node_start", task_id=state.get("task_id"))

    if state.get("intent") and state["intent"] != "":
        logger.info("intent_already_set", intent=state["intent"])
        state["status"] = "running"
        return state

    if not state.get("company_code"):
        logger.warning("intent_classifier_no_input")
        state["intent"] = "comprehensive"
        state["status"] = "running"
        return state

    state["status"] = "running"
    logger.info("intent_classifier_node_done", intent=state.get("intent"))
    return state
