import structlog
from state import AgentState
from agents.financial_analyzer.dupont import compute_dupont
from agents.financial_analyzer.anomaly import detect_anomalies
from services.llm_service import get_llm_service
from prompts.financial_analysis import FINANCIAL_ANALYSIS_SYSTEM, build_financial_analysis_prompt

logger = structlog.get_logger()


async def financial_analyzer_node(state: AgentState) -> AgentState:
    logger.info("financial_analyzer_node_start", task_id=state.get("task_id"))

    raw_data = state.get("raw_data") or {}
    metrics = raw_data.get("financial_metrics", {})

    if not metrics:
        state["errors"].append("财务分析跳过: 无可用财务数据")
        state["financial_analysis"] = {
            "dupont_decomposition": {"roe": 0, "net_margin": 0, "asset_turnover": 0,
                                      "equity_multiplier": 0, "is_valid": False, "missing_metrics": ["all"]},
            "anomaly_flags": [],
            "narrative": "无可用的财务数据，无法完成分析。",
            "analyst_confidence": "low",
        }
        return state

    try:
        dupont = compute_dupont(metrics)
        dupont_dict = dupont.model_dump()
        anomalies = await detect_anomalies(state.get("company_code", ""), metrics)
        anomaly_dicts = [a.model_dump() for a in anomalies]

        llm = get_llm_service()
        prompt = build_financial_analysis_prompt(
            dupont_dict, anomaly_dicts,
            state.get("company_name", state.get("company_code", "")),
            state.get("report_date", ""),
        )
        result = await llm.invoke("financial_analyzer", [
            {"role": "system", "content": FINANCIAL_ANALYSIS_SYSTEM},
            {"role": "user", "content": prompt},
        ])
        narrative = result.get("content", "")

        confidence = "high"
        if not dupont.is_valid:
            confidence = "low"
        elif len(anomalies) > 3:
            confidence = "medium"

        state["financial_analysis"] = {
            "dupont_decomposition": dupont_dict,
            "anomaly_flags": anomaly_dicts,
            "narrative": narrative,
            "analyst_confidence": confidence,
        }
        logger.info("financial_analyzer_node_done", confidence=confidence)
    except Exception as e:
        logger.error("financial_analyzer_error", error=str(e))
        state["errors"].append(f"财务分析节点失败: {str(e)}")
        state["financial_analysis"] = None

    return state
