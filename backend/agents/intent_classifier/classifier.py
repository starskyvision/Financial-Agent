import json
import structlog
from state import IntentResult
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


async def classify_intent(message: str, history: list[dict] | None = None) -> IntentResult:
    """LLM 分类意图 + 提取实体，AKShare 搜索兜底股票代码"""
    llm = get_llm_service()
    messages = [{"role": "system", "content": INTENT_CLASSIFIER_SYSTEM}]
    if history:
        messages.extend(history[-4:])
    messages.append({"role": "user", "content": message})

    result = await llm.invoke("intent_classifier", messages)

    try:
        content = result.get("content", "")
        if "{" in content and "}" in content:
            start = content.index("{")
            end = content.rindex("}") + 1
            content = content[start:end]

        data = json.loads(content)
        code = data.get("company_code", "")
        name = data.get("company_name", "")

        # Layer 2: LLM 没给出 code 但给了 name → AKShare 搜索兜底
        if not code and name:
            searched = _search_stock_code(name)
            if searched:
                code = searched
                logger.info("stock_code_resolved_by_search", name=name, code=code)

        intent_result = IntentResult(
            intent=data.get("intent", "comprehensive"),
            company_code=code,
            company_name=name,
            report_date=data.get("report_date", ""),
            metric_names=data.get("metric_names", []),
        )

        logger.info("intent_classified", intent=intent_result.intent,
                    code=code or "(none)", name=name or "(none)")
        return intent_result
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning("intent_parse_error", error=str(e))
        return IntentResult(intent="comprehensive", company_code="")
