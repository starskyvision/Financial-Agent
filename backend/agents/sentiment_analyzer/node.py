import json
import structlog
from state import AgentState
from services.llm_service import get_llm_service
from prompts.sentiment_analysis import SENTIMENT_ANALYSIS_SYSTEM
from constants.metrics import MAX_NEWS_PER_BATCH, NEWS_SUMMARY_TRUNCATE

logger = structlog.get_logger()


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
    _parts = [company]
    if len(company) >= 3:
        _parts.append(company[:2])  # "阿里", "腾讯", "百度"
    if len(company) >= 4:
        _parts.append(company[:3])
    _filtered = [n for n in news_list if any(p in n.get("title", "") for p in _parts)]
    if _filtered:
        logger.info("sentiment_news_filtered", kept=len(_filtered), dropped=len(news_list)-len(_filtered))
        news_list = _filtered

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
        user_prompt = (
            f"目标公司: {company}\n"
            f"请分析以下 {len(news_texts)} 条新闻的情感倾向。\n"
            f"⚠️ 只分析与 {company} 直接相关的新闻。\n"
            f"排除以下类型的新闻：仅提及公司名称的大盘/行业综述、南向/北向资金流动摘要、其他公司为主体的新闻中顺便提及 {company}。\n"
            f"如果一条新闻的主体不是 {company}，不要将其计入 details。\n\n"
            f"{news_block}"
        )

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
