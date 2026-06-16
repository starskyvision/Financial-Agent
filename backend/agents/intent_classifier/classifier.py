import json
import structlog
from state import IntentResult
from services.llm_service import get_llm_service
from prompts.intent_classifier import INTENT_CLASSIFIER_SYSTEM

logger = structlog.get_logger()

NAME_TO_CODE = {
    "茅台": "600519", "贵州茅台": "600519",
    "五粮液": "000858",
    "宁德时代": "300750", "宁德": "300750",
    "比亚迪": "002594",
    "平安": "601318", "中国平安": "601318",
    "招商银行": "600036", "招行": "600036",
    "万科": "000002", "万科A": "000002",
    "美的": "000333", "美的集团": "000333",
    "格力": "000651", "格力电器": "000651",
    "腾讯": "00700", "腾讯控股": "00700",
    "阿里巴巴": "09988", "阿里": "09988",
    "百度": "09888",
    "京东": "09618",
    "小米": "01810", "小米集团": "01810",
    "网易": "09999",
}


async def classify_intent(message: str, history: list[dict] | None = None) -> IntentResult:
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
        intent_result = IntentResult(
            intent=data.get("intent", "comprehensive"),
            company_code=data.get("company_code", ""),
            company_name=data.get("company_name", ""),
            report_date=data.get("report_date", ""),
            metric_names=data.get("metric_names", []),
        )

        if not intent_result.company_code and intent_result.company_name:
            intent_result.company_code = NAME_TO_CODE.get(intent_result.company_name, "")

        logger.info("intent_classified", intent=intent_result.intent,
                    code=intent_result.company_code)
        return intent_result
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning("intent_parse_error", error=str(e))
        return IntentResult(intent="comprehensive", company_code="")
