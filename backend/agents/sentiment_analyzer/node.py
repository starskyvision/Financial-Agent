import json
import structlog
from state import AgentState
from services.llm_service import get_llm_service
from prompts.sentiment_analysis import SENTIMENT_ANALYSIS_SYSTEM

logger = structlog.get_logger()

MAX_NEWS_PER_BATCH = 30


async def sentiment_analyzer_node(state: AgentState) -> AgentState:
    logger.info("sentiment_analyzer_node_start", task_id=state.get("task_id"))

    raw_data = state.get("raw_data") or {}
    news_list = raw_data.get("news_headlines", [])

    if not news_list:
        state["sentiment_result"] = {
            "overall_sentiment": "neutral", "overall_score": 0.5,
            "positive_count": 0, "neutral_count": 0, "negative_count": 0,
            "key_topics": [], "summary": "无可用舆情数据", "details": [],
        }
        return state

    try:
        news_texts = []
        for n in news_list[:MAX_NEWS_PER_BATCH]:
            title = n.get("title", "")
            summary = n.get("summary", "")[:100]
            news_texts.append(f"- {title} | {summary}")
        news_block = "\n".join(news_texts)

        user_prompt = f"请分析以下 {len(news_texts)} 条新闻的情感倾向：\n\n{news_block}"

        llm = get_llm_service()
        result = await llm.invoke("sentiment_analyzer", [
            {"role": "system", "content": SENTIMENT_ANALYSIS_SYSTEM},
            {"role": "user", "content": user_prompt},
        ])

        content = result.get("content", "")
        if "{" in content and "}" in content:
            start = content.index("{")
            end = content.rindex("}") + 1
            content = content[start:end]

        data = json.loads(content)
        details = data.get("details", [])
        pos = sum(1 for d in details if d.get("sentiment") == "positive")
        neu = sum(1 for d in details if d.get("sentiment") == "neutral")
        neg = sum(1 for d in details if d.get("sentiment") == "negative")

        state["sentiment_result"] = {
            "overall_sentiment": data.get("overall_sentiment", "neutral"),
            "overall_score": data.get("overall_score", 0.5),
            "positive_count": pos, "neutral_count": neu, "negative_count": neg,
            "key_topics": data.get("key_topics", []),
            "summary": data.get("summary", ""), "details": details,
        }
        logger.info("sentiment_analyzer_node_done", overall=state["sentiment_result"]["overall_sentiment"])
    except Exception as e:
        logger.error("sentiment_analyzer_error", error=str(e))
        state["errors"].append(f"舆情分析失败: {str(e)}")
        state["sentiment_result"] = {
            "overall_sentiment": "neutral", "overall_score": 0.5,
            "positive_count": 0, "neutral_count": 0, "negative_count": 0,
            "key_topics": [], "summary": f"舆情分析异常: {str(e)}", "details": [],
        }

    return state
