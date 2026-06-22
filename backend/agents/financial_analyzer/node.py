import structlog
from state import AgentState
from agents.financial_analyzer.dupont import compute_dupont
from agents.financial_analyzer.anomaly import detect_anomalies
from constants.metrics import ANOMALY_MEDIUM_CONFIDENCE_THRESHOLD, RAG_TOP_K_DEFAULT, RAG_CONTENT_TRUNCATE
from services.llm_service import get_llm_service
from prompts.financial_analysis import FINANCIAL_ANALYSIS_SYSTEM, build_financial_analysis_prompt

logger = structlog.get_logger()


async def _fetch_rag_context(state: AgentState) -> str:
    """从知识库检索与当前公司相关的研报，返回格式化上下文。"""
    try:
        from services.rag.search import search_rag
        from services.db_utils import get_async_session_factory

        code = state.get("company_code", "")
        name = state.get("company_name", code)
        code_hint = f" ({code})" if code else ""
        name_en = state.get("company_name_en", "")
        en_hint = f" {name_en}" if name_en else ""
        query = f"{name}{en_hint}{code_hint} 财务分析 盈利能力 杜邦 风险"
        session_factory = get_async_session_factory()
        results = await search_rag(
            query=query, company_code=code, top_k=RAG_TOP_K_DEFAULT,
            session_factory=session_factory, doc_type="report",
        )
        if not results and code:
            results = await search_rag(
                query=query, company_code="", top_k=RAG_TOP_K_DEFAULT,
                session_factory=session_factory, doc_type="report",
            )
        if results:
            parts = []
            for r in results:
                parts.append(
                    f"**[{r['doc_title']}]** (相关度: {r['score']:.0%})\n"
                    f"{r['content'][:RAG_CONTENT_TRUNCATE]}"
                )
            logger.info("fin_rag_context_fetched", company=name, docs=len(results))
            return "\n\n---\n\n".join(parts)
    except Exception as e:
        logger.warning("fin_rag_skipped", error=str(e))
    return ""


async def financial_analyzer_node(state: AgentState) -> AgentState:
    logger.info("financial_analyzer_node_start", task_id=state.get("task_id"))

    raw_data = state.get("raw_data") or {}
    metrics = raw_data.get("financial_metrics", {})

    if not metrics:
        state["errors"].append("财务分析跳过: 无可用财务数据")
        company = state.get("company_name", state.get("company_code", ""))
        knowledge_narrative = ""
        if company:
            try:
                # 拉取 RAG 上下文辅助分析
                rag_context = await _fetch_rag_context(state)
                llm = get_llm_service()
                user_prompt = (
                    f"请基于你的训练知识分析 {company} 的盈利能力。"
                    f"注意：数据源暂时不可用，请基于公开信息给出概览性分析，"
                    f"并在开头注明'数据源暂时不可用，以下分析基于公开信息和模型知识'。"
                )
                if rag_context:
                    user_prompt += f"\n\n参考研报（来自知识库）:\n{rag_context}\n\n请结合参考研报中的信息进行分析。"
                result = await llm.invoke("financial_analyzer", [
                    {"role": "system", "content": FINANCIAL_ANALYSIS_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ])
                knowledge_narrative = result.get("content", "")
            except Exception as e:
                logger.warning("financial_knowledge_fallback_failed", error=str(e))
        state["financial_analysis"] = {
            "dupont_decomposition": {"roe": 0, "net_margin": 0, "asset_turnover": 0,
                                      "equity_multiplier": 0, "is_valid": False, "missing_metrics": ["all"]},
            "anomaly_flags": [],
            "narrative": knowledge_narrative or "无可用的财务数据，无法完成分析。",
            "analyst_confidence": "low",
        }
        return state

    try:
        dupont = compute_dupont(metrics)
        dupont_dict = dupont.model_dump()
        anomalies = await detect_anomalies(state.get("company_code", ""), metrics)
        anomaly_dicts = [a.model_dump() for a in anomalies]

        llm = get_llm_service()
        # 使用实际数据报告期（来自数据源），而非用户请求的日期
        actual_date = metrics.get("_report_date", "") or state.get("report_date", "")
        user_date = state.get("report_date", "")
        company = state.get("company_name", state.get("company_code", ""))
        prompt = build_financial_analysis_prompt(
            dupont_dict, anomaly_dicts, company, actual_date,
        )
        # 若用户指定了时间段但数据不匹配，前置强硬提示
        if user_date and actual_date and user_date != actual_date:
            prompt = (
                f"重要约束: 用户请求 {user_date}, "
                f"但数据源仅有 {actual_date} 的数据. "
                f"你必须基于 {actual_date} 进行分析, "
                f"严禁在分析中使用 {user_date} 或 Q1/Q2/Q3 等季度描述. "
                f"开头请说明: 本分析基于 {actual_date} 数据.\n\n"
            ) + prompt

        # 拉取 RAG 知识库上下文辅助分析
        rag_context = await _fetch_rag_context(state)
        if rag_context:
            prompt += f"\n\n参考研报（来自知识库，可引用辅助分析）:\n{rag_context}\n\n请结合参考研报中的行业信息和分析视角，丰富你的分析内容。引用时标注 [来源: 知识库]。\n"

        result = await llm.invoke("financial_analyzer", [
            {"role": "system", "content": FINANCIAL_ANALYSIS_SYSTEM},
            {"role": "user", "content": prompt},
        ])
        narrative = result.get("content", "")

        confidence = "high"
        if not dupont.is_valid:
            confidence = "low"
        elif len(anomalies) > ANOMALY_MEDIUM_CONFIDENCE_THRESHOLD:
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
