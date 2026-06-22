import structlog
from state import AgentState
from services.llm_service import get_llm_service
from prompts.report_generation import REPORT_GENERATION_SYSTEM, build_report_prompt
from constants.metrics import RAG_TOP_K_DEFAULT, RAG_CONTENT_TRUNCATE

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
        # Build retry_context BEFORE clearing errors (so rewriter corrections are visible)
        retry_context = ""
        existing_errors = state.get("errors", [])
        if existing_errors and state.get("retry_count", 0) > 0:
            retry_context = "以下数据在上次报告中与源数据不匹配，请修正：\n" + "\n".join(
                f"  - {e}" for e in existing_errors
            )

        # Clear previous cycle's fact-check errors
        state["errors"] = [e for e in existing_errors if not e.startswith((
            "ROE:", "ROA:", "净利润:", "营收:", "净利率:", "毛利率:", "现金流:",
            "经营现金流:", "资产负债率:", "每股经营现金流:",
        ))]

        # --- RAG 检索：报告生成前从知识库搜索相关研报 ---
        rag_context = ""
        try:
            from services.rag.search import search_rag
            from services.db_utils import get_async_session_factory

            code = state.get("company_code", "")
            name = state.get("company_name", code)
            code_hint = f" ({code})" if code else ""
            name_en = state.get("company_name_en", "")
            en_hint = f" {name_en}" if name_en else ""
            query = f"{name}{en_hint}{code_hint} 财务分析 经营风险 行业展望 投资评级"
            async_session = get_async_session_factory()
            results = await search_rag(
                query=query, company_code=code, top_k=RAG_TOP_K_DEFAULT,
                session_factory=async_session, doc_type="report",
            )
            if not results and code:
                results = await search_rag(
                    query=query, company_code="", top_k=RAG_TOP_K_DEFAULT,
                    session_factory=async_session, doc_type="report",
                )
            if results:
                rag_parts = []
                for r in results:
                    rag_parts.append(
                        f"**[{r['doc_title']}]** (相关度: {r['score']:.0%})\n"
                        f"{r['content'][:RAG_CONTENT_TRUNCATE]}"
                    )
                rag_context = "\n\n---\n\n".join(rag_parts)
                state["rag_context"] = rag_context
        except Exception as e:
            logger.warning("rag_retrieval_skipped", error=str(e))

        prompt = build_report_prompt(state, retry_context)
        llm = get_llm_service()
        result = await llm.invoke("reviewer", [
            {"role": "system", "content": REPORT_GENERATION_SYSTEM},
            {"role": "user", "content": prompt},
        ])
        state["draft_report"] = result.get("content", "")

        # --- Fact check: compare report claims against source financial metrics ---
        raw_data = state.get("raw_data") or {}
        source_metrics = raw_data.get("financial_metrics", {})
        if state["draft_report"] and source_metrics:
            from agents.reviewer.fact_checker import verify_facts
            fact_errors = await verify_facts(
                state["draft_report"],
                state.get("company_code", ""),
                db_session=None,
                source_metrics=source_metrics,
            )
            if fact_errors:
                state["errors"].extend(fact_errors)
                logger.info("report_fact_check_issues", count=len(fact_errors))
            else:
                logger.info("report_fact_check_clean")

        logger.info("report_generator_node_done", length=len(state["draft_report"]))
    except Exception as e:
        logger.error("report_generator_error", error=str(e))
        state["errors"].append(f"报告生成失败: {str(e)}")
        if state.get("draft_report") is None:
            state["draft_report"] = f"报告生成异常: {str(e)}"

    return state
