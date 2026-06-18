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
    """在 A 股列表中按名称搜索股票代码——精确→包含→模糊匹配三级兜底。"""
    if not name:
        return ""
    try:
        stocks = _load_stock_list()
        name_lower = name.strip().lower()

        # L1: 精确匹配
        for s in stocks:
            if s["name"].lower() == name_lower:
                return s["code"]

        # L2: 包含匹配（子串）
        matches = [s for s in stocks if name_lower in s["name"].lower()]
        if len(matches) == 1:
            return matches[0]["code"]
        if len(matches) > 1:
            logger.info("stock_search_ambiguous", name=name, matches=len(matches))
            return ""   # 多个匹配，不冒险

        # L3: difflib 模糊匹配（相似度 >= 0.6 且唯一匹配）
        from difflib import SequenceMatcher
        scored = [
            (s, SequenceMatcher(None, name_lower, s["name"].lower()).ratio())
            for s in stocks
        ]
        scored = [(s, r) for s, r in scored if r >= 0.6]
        scored.sort(key=lambda x: x[1], reverse=True)

        if len(scored) == 1:
            logger.info("stock_search_fuzzy", name=name,
                        matched=scored[0][0]["name"], score=round(scored[0][1], 2))
            return scored[0][0]["code"]
        if len(scored) > 1:
            # 第一名与第二名差距 > 0.15 才采纳
            if scored[0][1] - scored[1][1] > 0.15:
                logger.info("stock_search_fuzzy", name=name,
                            matched=scored[0][0]["name"], score=round(scored[0][1], 2))
                return scored[0][0]["code"]
            logger.info("stock_search_fuzzy_ambiguous", name=name,
                        top=[(s["name"], round(r, 2)) for s, r in scored[:3]])
    except Exception as e:
        logger.warning("stock_search_error", name=name, error=str(e))
    return ""



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

        # ── 窄兜底：LLM 对报告类表达偶尔漏判 ──
        _REPORT_WORDS = ["报告", "研报", "投研"]
        _REPORT_PATTERNS = ["出报告", "出个报告", "出份报告", "写报告", "写个报告",
                           "出一份报告", "生成报告", "生成一份报告",
                           "给我一份报告", "给我报告", "给份报告", "来份报告",
                           "一份报告", "一份", "做个报告", "做一份报告"]
        has_report = any(p in message for p in _REPORT_PATTERNS)
        # 兜底："一份XX的报告" → "一份" 和 "报告" 都在
        if not has_report:
            has_report = ("一份" in message) and any(w in message for w in _REPORT_WORDS)
        if intent != "comprehensive" and has_report:
            logger.info("intent_report_override", from_intent=intent, to="comprehensive")
            intent = "comprehensive"

        code = data.get("company_code", "")
        name = data.get("company_name", "")

        # 中概股 US ticker → 优先 HK 代码（AKShare 港股数据更全）
        _DUAL_LISTED_MAP: dict[str, str] = {
            "BIDU": "09888", "JD": "09618", "NTES": "09999",
            "BABA": "09988", "BILI": "09626", "NIO": "09866",
        }
        code = _DUAL_LISTED_MAP.get(code.upper(), code) if code else code

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
        return IntentResult(intent="comprehensive", company_code="")
