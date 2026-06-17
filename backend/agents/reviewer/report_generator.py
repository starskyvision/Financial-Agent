import os
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
        # Clear previous cycle's fact-check errors
        state["errors"] = [e for e in state.get("errors", []) if not e.startswith((
            "ROE:", "ROA:", "净利润:", "营收:", "净利率:", "毛利率:", "现金流:",
            "经营现金流:", "资产负债率:", "每股经营现金流:",
        ))]

        retry_context = ""
        if state.get("errors") and state.get("retry_count", 0) > 0:
            retry_context = "以下数据在上次报告中与源数据不匹配，请修正：\n" + "\n".join(
                f"  - {e}" for e in state["errors"]
            )

        # --- RAG 检索：报告生成前从知识库搜索相关研报 ---
        rag_context = ""
        try:
            from services.rag.search import search_rag
            from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
            from sqlalchemy.orm import sessionmaker

            db_url = os.getenv("DATABASE_URL", "")
            if db_url:
                sync_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
                engine = create_async_engine(sync_url, echo=False)
                async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
                code = state.get("company_code", "")
                name = state.get("company_name", code)
                query = f"{name} 财务分析 经营风险 行业展望 投资评级"
                results = await search_rag(
                    query=query, company_code=code, top_k=5,
                    session_factory=async_session,
                )
                if results:
                    rag_parts = []
                    for r in results:
                        rag_parts.append(
                            f"**[{r['doc_title']}]** (相关度: {r['score']:.0%})\n"
                            f"{r['content'][:300]}"
                        )
                    rag_context = "\n\n---\n\n".join(rag_parts)
                    state["rag_context"] = rag_context
                await engine.dispose()
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
