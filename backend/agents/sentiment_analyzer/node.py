import json
import re
import structlog
from state import AgentState
from services.llm_service import get_llm_service
from prompts.sentiment_analysis import SENTIMENT_ANALYSIS_SYSTEM
from constants.metrics import MAX_NEWS_PER_BATCH, NEWS_SUMMARY_TRUNCATE, RAG_TOP_K_DEFAULT, RAG_CONTENT_TRUNCATE

logger = structlog.get_logger()


def _normalize_title(title: str) -> str:
    """Normalize a news title for deduplication: replace digits, dates, and
    monetary amounts with placeholders so that '连续18日回购82.43亿' and
    '连续17日回购77.42亿' collapse to the same canonical form."""
    norm = title
    norm = re.sub(r'\d+\.?\d*亿', '#亿', norm)         # 82.43亿 → #亿
    norm = re.sub(r'\d+\.?\d*万', '#万', norm)         # 111.80万 → #万
    norm = re.sub(r'\d+-\d+-\d+', '#DATE#', norm)     # 2026-06-09 → #DATE#
    norm = re.sub(r'\d+', '#', norm)                   # remaining numbers → #
    # Collapse temporal prefixes so "连续#日回购" and "#月#日回购" merge
    norm = re.sub(r'连续#日', '#日', norm)
    norm = re.sub(r'#月#日', '#日', norm)
    norm = re.sub(r'\s+', '', norm)                    # strip all whitespace
    return norm


def _deduplicate_news(news_list: list[dict], similarity_threshold: float = 0.70) -> list[dict]:
    """Remove near-duplicate news items that describe the same event with
    incrementally updated numbers (e.g. daily buyback counts).

    Uses SequenceMatcher on normalized titles to cluster similar items.
    Keeps the first occurrence from each cluster (latest by time).
    """
    from difflib import SequenceMatcher

    seen_norms: list[str] = []  # canonical forms of kept items
    deduped: list[dict] = []
    for item in news_list:
        title = item.get("title", "")
        norm = _normalize_title(title)
        if not norm:
            deduped.append(item)
            continue
        # Check against all already-kept normalized titles
        is_dup = False
        for kept in seen_norms:
            if SequenceMatcher(None, norm, kept).ratio() >= similarity_threshold:
                is_dup = True
                break
        if not is_dup:
            seen_norms.append(norm)
            deduped.append(item)
    if len(deduped) < len(news_list):
        logger.info("news_deduplicated", before=len(news_list), after=len(deduped))
    return deduped


async def _fetch_sentiment_rag(state: AgentState, company: str) -> str:
    """从知识库检索与公司相关的舆情/行业背景，辅助情感分析。"""
    try:
        from services.rag.search import search_rag
        from services.db_utils import get_async_session_factory

        code = state.get("company_code", "")
        name_en = state.get("company_name_en", "")
        # 中英双语 query：中文名 + 英文名（如有）+ 股票代码，覆盖中英文研报
        en_hint = f" {name_en}" if name_en else ""
        code_hint = f" ({code})" if code else ""
        query = f"{company}{en_hint}{code_hint} 舆情 新闻 行业动态 风险事件"
        session_factory = get_async_session_factory()
        results = await search_rag(
            query=query, company_code=code, top_k=3,
            session_factory=session_factory, doc_type="report",
        )
        # 若按 company_code 未命中，放宽条件再搜一次（研报可能用不同代码格式）
        if not results and code:
            results = await search_rag(
                query=query, company_code="", top_k=3,
                session_factory=session_factory, doc_type="report",
            )
        if results:
            parts = []
            for r in results:
                parts.append(
                    f"**[{r['doc_title']}]** (相关度: {r['score']:.0%})\n"
                    f"{r['content'][:RAG_CONTENT_TRUNCATE]}"
                )
            logger.info("sentiment_rag_context_fetched", company=company, docs=len(results))
            return "\n\n---\n\n".join(parts)
    except Exception as e:
        logger.warning("sentiment_rag_skipped", error=str(e))
    return ""


async def sentiment_analyzer_node(state: AgentState) -> AgentState:
    logger.info("sentiment_analyzer_node_start", task_id=state.get("task_id"))

    raw_data = state.get("raw_data") or {}
    news_list = raw_data.get("news_headlines", [])
    company = state.get("company_name") or state.get("company_code", "")

    if not news_list:
        logger.info("sentiment_analyzer_no_news", company=company)
        state["sentiment_result"] = {
            "overall_sentiment": "neutral", "overall_score": 0.5,
            "positive_count": 0, "neutral_count": 0, "negative_count": 0,
            "key_topics": [], "summary": "", "details": [],
        }
        return state

    # ── 预过滤：标题不含公司名或其简称 → 排除大盘综述/其他公司新闻 ──
    # company 已由 preprocessor 标准化（如"阿里"→"阿里巴巴"），
    # 取其前2-4字符作为简称匹配新闻标题中常见的缩略形式（如"阿里"、"阿里巴巴-W"）
    code = state.get("company_code", "")
    _parts = [company] if company else []
    if code:
        _parts.append(code)                            # e.g. "09988"
    if len(company) >= 2:
        _parts.append(company[:2])                     # "阿里", "腾讯"
    if len(company) >= 3:
        _parts.append(company[:3])                     # "阿里巴"
    _filtered = [n for n in news_list if any(p in n.get("title", "") for p in _parts if p)]
    if _filtered:
        logger.info("sentiment_news_filtered", kept=len(_filtered), dropped=len(news_list)-len(_filtered))
        news_list = _filtered

    # ── 去重：同主题连续报道（如"连续N日回购"）只保留最新一条 ──
    news_list = _deduplicate_news(news_list)

    try:
        llm = get_llm_service()
        news_texts = []
        for n in news_list[:MAX_NEWS_PER_BATCH]:
            title = n.get("title", "")
            summary = n.get("summary", "")[:NEWS_SUMMARY_TRUNCATE]
            pub_time = n.get("published_at", "")
            url = n.get("url", "")
            extra = ""
            if pub_time:
                extra += f" [发布时间: {pub_time}]"
            if url:
                extra += f" [链接: {url}]"
            news_texts.append(f"- {title} | {summary}{extra}")
        news_block = "\n".join(news_texts)

        # 拉取 RAG 知识库上下文：行业背景 / 历史舆情 / 风险事件
        rag_context = await _fetch_sentiment_rag(state, company)

        user_prompt = (
            f"目标公司: {company}\n"
            f"请分析以下 {len(news_texts)} 条新闻的情感倾向。\n"
            f"⚠️ 只分析与 {company} 直接相关的新闻。\n"
            f"排除以下类型的新闻：仅提及公司名称的大盘/行业综述、南向/北向资金流动摘要、其他公司为主体的新闻中顺便提及 {company}。\n"
            f"如果一条新闻的主体不是 {company}，不要将其计入 details。\n"
        )
        if rag_context:
            user_prompt += (
                f"\n参考研报（来自知识库，必须引用）:\n{rag_context}\n\n"
                f"**必须在 summary 中引用上述研报信息**，标注 [来源: 知识库]。"
                f"结合研报中的行业背景和风险分析，判断当前新闻的实际影响程度。\n"
            )
        user_prompt += f"\n{news_block}"

        result = await llm.invoke("sentiment_analyzer", [
            {"role": "system", "content": SENTIMENT_ANALYSIS_SYSTEM},
            {"role": "user", "content": user_prompt},
        ], response_format="json_object")

        content = result.get("content", "")
        if "{" in content and "}" in content:
            start = content.index("{")
            end = content.rindex("}") + 1
            content = content[start:end]

        data = json.loads(content)
        details = data.get("details", [])
        # A: 按情感极端度排序 — 强利好/强利空优先，中性靠后
        details.sort(key=lambda d: abs(d.get("score", 0.5) - 0.5), reverse=True)
        pos = sum(1 for d in details if d.get("sentiment") == "positive")
        neu = sum(1 for d in details if d.get("sentiment") == "neutral")
        neg = sum(1 for d in details if d.get("sentiment") == "negative")

        # Normalize key_topics: accept both old ["str"] and new [{"topic":"","description":""}]
        raw_topics = data.get("key_topics", [])
        if raw_topics and isinstance(raw_topics[0], str):
            raw_topics = [{"topic": t, "description": ""} for t in raw_topics]

        state["sentiment_result"] = {
            "overall_sentiment": data.get("overall_sentiment", "neutral"),
            "overall_score": data.get("overall_score", 0.5),
            "positive_count": pos, "neutral_count": neu, "negative_count": neg,
            "key_topics": raw_topics,
            "summary": data.get("summary", ""), "details": details,
        }
        logger.info("sentiment_analyzer_node_done",
                    overall=state["sentiment_result"]["overall_sentiment"])
    except Exception as e:
        logger.error("sentiment_analyzer_error", error=str(e))
        state["errors"].append(f"舆情分析失败: {str(e)}")
        state["sentiment_result"] = {
            "overall_sentiment": "neutral", "overall_score": 0.5,
            "positive_count": 0, "neutral_count": 0, "negative_count": 0,
            "key_topics": [], "summary": f"舆情分析异常: {str(e)}", "details": [],
        }

    return state
