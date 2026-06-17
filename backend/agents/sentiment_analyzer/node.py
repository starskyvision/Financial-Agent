import json
import structlog
from state import AgentState
from services.llm_service import get_llm_service
from prompts.sentiment_analysis import SENTIMENT_ANALYSIS_SYSTEM

logger = structlog.get_logger()

MAX_NEWS_PER_BATCH = 30

SENTIMENT_KNOWLEDGE_PROMPT = """你是一个金融舆情分析师。请基于你对 {company} 近期公开信息的了解，给出该公司当前的舆情概况。

要求：
1. 列出 3-5 个近期关键舆情主题（如财报、新产品、政策影响、行业动态等）
2. 判断整体舆情倾向（positive/neutral/negative）
3. 给出 1-2 句话的总结
4. 在总结中明确标注：本分析基于公开信息，非实时数据

输出 JSON:
{{"overall_sentiment": "positive|neutral|negative", "overall_score": 0.6, "key_topics": ["topic1"], "summary": "...(注明基于公开信息)", "details": []}}
"""


async def sentiment_analyzer_node(state: AgentState) -> AgentState:
    logger.info("sentiment_analyzer_node_start", task_id=state.get("task_id"))

    raw_data = state.get("raw_data") or {}
    news_list = raw_data.get("news_headlines", [])
    company = state.get("company_name") or state.get("company_code", "")

    try:
        llm = get_llm_service()

        if news_list:
            # 有新闻数据：分析实际新闻
            news_texts = []
            for n in news_list[:MAX_NEWS_PER_BATCH]:
                title = n.get("title", "")
                summary = n.get("summary", "")[:100]
                news_texts.append(f"- {title} | {summary}")
            news_block = "\n".join(news_texts)
            user_prompt = f"请分析以下 {len(news_texts)} 条新闻的情感倾向：\n\n{news_block}"
            system_prompt = SENTIMENT_ANALYSIS_SYSTEM
        else:
            # 无新闻数据：基于 LLM 知识生成舆情概况
            user_prompt = f"请分析 {company} 的近期舆情概况。"
            system_prompt = SENTIMENT_KNOWLEDGE_PROMPT.replace("{company}", company)

        result = await llm.invoke("sentiment_analyzer", [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ], response_format="json_object")

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
