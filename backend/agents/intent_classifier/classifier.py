import json
import structlog
from state import IntentResult
from constants.metrics import MAX_HISTORY_TURNS
from services.llm_service import get_llm_service
from prompts.intent_classifier import INTENT_CLASSIFIER_SYSTEM

logger = structlog.get_logger()

# AKShare 全量 A 股列表缓存（首次使用时加载，后续复用）
_stock_list_cache: list[dict] | None = None


def _load_stock_list() -> list[dict]:
    """加载全量 A 股列表，缓存复用"""
    global _stock_list_cache
    if _stock_list_cache is not None:
        return _stock_list_cache
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        _stock_list_cache = [
            {"code": str(row["code"]), "name": str(row["name"])}
            for _, row in df.iterrows()
        ]
        logger.info("stock_list_loaded", count=len(_stock_list_cache))
    except Exception as e:
        logger.warning("stock_list_load_failed", error=str(e))
        _stock_list_cache = []
    return _stock_list_cache


def _search_stock_code(name: str) -> str:
    """在 A 股列表中按名称模糊搜索股票代码"""
    if not name:
        return ""
    try:
        stocks = _load_stock_list()
        name_lower = name.strip().lower()
        # 精确匹配
        for s in stocks:
            if s["name"].lower() == name_lower:
                return s["code"]
        # 模糊匹配：包含关键词
        matches = [s for s in stocks if name_lower in s["name"].lower()]
        if len(matches) == 1:
            return matches[0]["code"]
        # 多个匹配或 0 个：返回空
        if matches:
            logger.info("stock_search_ambiguous", name=name, matches=len(matches))
    except Exception as e:
        logger.warning("stock_search_error", name=name, error=str(e))
    return ""


# 关键词强制路由：LLM 可能误判，关键词兜底
_FINANCE_KEYWORDS = ["盈利能力", "财务状况", "偿债能力", "现金流分析", "利润率"]
_COMPREHENSIVE_KEYWORDS = ["出份报告", "写份报告", "生成报告", "全面分析", "综合分析"]


def _keyword_override(llm_intent: str, message: str) -> str:
    """关键词兜底：避免 LLM 将简单财务分析误判为 comprehensive。"""
    msg = message.lower()
    has_finance = any(kw in msg for kw in _FINANCE_KEYWORDS)
    has_report = any(kw in msg for kw in _COMPREHENSIVE_KEYWORDS)

    if has_finance and not has_report and llm_intent == "comprehensive":
        logger.info("intent_keyword_override", from_intent="comprehensive", to="financial_analysis")
        return "financial_analysis"
    return llm_intent


async def classify_intent(message: str, history: list[dict] | None = None) -> IntentResult:
    """LLM 分类意图 + 提取实体，规则预处理 + 关键词兜底 + AKShare 搜索兜底股票代码"""
    # 第零层：规则预处理 + RAG 查询改写（相对日期、股票别名、单位标准化、知识库实体注入、低置信度 LLM 改写）
    from services.query_preprocessor import preprocess_with_rag, QueryRewriteError
    try:
        message = await preprocess_with_rag(message)
    except QueryRewriteError:
        raise  # propagate to main.py for user-facing error response

    llm = get_llm_service()
    messages = [{"role": "system", "content": INTENT_CLASSIFIER_SYSTEM}]
    if history:
        messages.extend(history[-MAX_HISTORY_TURNS:])
    messages.append({"role": "user", "content": message})

    result = await llm.invoke("intent_classifier", messages, response_format="json_object")

    try:
        content = result.get("content", "")
        if "{" in content and "}" in content:
            start = content.index("{")
            end = content.rindex("}") + 1
            content = content[start:end]

        data = json.loads(content)
        intent = data.get("intent", "comprehensive")
        # ── 关键词兜底（LLM 可能误判 comprehensive） ──
        intent = _keyword_override(intent, message)

        code = data.get("company_code", "")
        name = data.get("company_name", "")

        # 美股 ticker（1-5 位字母）→ 保留，不做数字校验
        # 非数字非字母代码（异常输入）→ 清空，走搜索兜底
        if code and not code.isdigit() and not code.isalpha():
            logger.info("invalid_code_discarded", code=code)
            code = ""

        # Layer 2: LLM 没给出 code 或给了非数字 code → AKShare 搜索兜底
        if not code and name:
            searched = _search_stock_code(name)
            if searched:
                code = searched
                logger.info("stock_code_resolved_by_search", name=name, code=code)

        intent_result = IntentResult(
            intent=intent,
            company_code=code,
            company_name=name,
            report_date=data.get("report_date", ""),
            metric_names=data.get("metric_names", []),
            query_type=data.get("query_type", ""),
            query_target=data.get("query_target", ""),
        )

        logger.info("intent_classified", intent=intent_result.intent,
                    code=code or "(none)", name=name or "(none)")
        return intent_result
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning("intent_parse_error", error=str(e))
        # ── 异常兜底：检查关键词决定降级策略 ──
        fallback = _keyword_override("comprehensive", message)
        return IntentResult(intent=fallback, company_code="")
