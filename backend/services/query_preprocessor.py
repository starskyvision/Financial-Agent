"""
查询预处理器 — 在 LLM 调用前对用户输入做规则化改写。

设计原则：
  - 零延迟：纯规则匹配，无 LLM/网络调用
  - 可插拔：每个预处理步骤独立，可单独启用/禁用
  - 可扩展：新增规则只需在对应链表中加一条
  - 泛用性：所有入口（/chat、/tasks、RAG search）统一调用

用法:
    from services.query_preprocessor import preprocess
    cleaned = preprocess(user_message)
"""

from __future__ import annotations

import asyncio
import re
import structlog
from datetime import datetime

from services.llm_service import get_llm_service

logger = structlog.get_logger()

# ── Async: RAG 检索上下文（用于改写） ──

async def _retrieve_context(query: str, top_k: int = 3) -> list[dict]:
    """调用 RAG 检索引擎，返回 top-k 文档片段列表。

    失败时返回空列表（不抛异常），上层降级处理。
    """
    try:
        from services.rag.search import search_rag

        # Use the shared async session factory if available
        try:
            from services.db_utils import get_async_session_factory
            session_factory = get_async_session_factory()
        except Exception:
            session_factory = None

        results = await search_rag(
            query=query,
            company_code="",
            top_k=top_k,
            session_factory=session_factory,
            doc_type="report",  # 仅搜真实研报，排除 Kaggle 假公司 ID
        )
        return results or []
    except Exception as exc:
        logger.warning("rag_retrieve_failed", error=str(exc))
        return []


def _should_llm_rewrite(retrieved: list[dict], threshold: float) -> bool:
    """判断是否需要触发 LLM 改写。

    Returns True if:
      - 无检索结果（query 太模糊，知识库无匹配）
      - top-1 相似度 < threshold（语义关联弱）
    """
    if not retrieved:
        return True
    top_score = retrieved[0].get("score", 0) if retrieved else 0
    return top_score < threshold


# ── LLM 改写 ──

class QueryRewriteError(Exception):
    """查询改写失败——向用户返回提示，不降级到原 query。"""


_REWRITE_SYSTEM_PROMPT = """你是一个金融查询改写助手。用户的问题可能简短模糊。基于知识库中检索到的参考信息，将用户问题改写为精确、具体、包含关键实体（股票代码、指标名、时间）的查询。

规则：
1. 保留用户原意，仅补充缺失的关键信息
2. 如果检索信息不足以判断，不要编造
3. 直接输出改写后的查询，不要加解释
4. 输出长度不超过 100 字

示例：
原问题: 茅台怎么样
参考信息: 贵州茅台(600519)2024Q3 ROE=10.1% 净利率=52.2%
改写: 分析贵州茅台(600519)2024Q3的盈利能力和财务表现"""


async def _llm_rewrite_query(
    original: str,
    retrieved: list[dict],
    timeout: float | None = None,
) -> str:
    """用 LLM 改写模糊查询。

    Args:
        original: 原始用户输入
        retrieved: RAG 检索结果列表
        timeout: LLM 调用超时（秒）

    Returns:
        改写后的查询字符串

    Raises:
        QueryRewriteError: LLM 调用失败或返回空结果
    """
    if timeout is None:
        from constants.metrics import LLM_REWRITE_TIMEOUT
        timeout = LLM_REWRITE_TIMEOUT
    # 拼接检索片段
    doc_parts: list[str] = []
    for i, doc in enumerate(retrieved[:3], 1):  # up to 3 docs in LLM prompt context
        content = doc.get("content", "")[:500]
        title = doc.get("doc_title", "")
        header = f"[文档{i}]" + (f" {title}" if title else "")
        doc_parts.append(f"{header}\n{content}")
    doc_text = "\n\n---\n\n".join(doc_parts) if doc_parts else "（无参考信息）"

    user_prompt = (
        f"原问题: {original}\n\n"
        f"知识库参考信息:\n{doc_text}\n\n"
        f"请改写上述问题。"
    )

    try:
        llm = get_llm_service()
        result = await asyncio.wait_for(
            llm.invoke("default", [
                {"role": "system", "content": _REWRITE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]),
            timeout=timeout,
        )
        rewritten = (result.get("content", "") or "").strip()

        if not rewritten or len(rewritten) < 4:
            raise QueryRewriteError(
                "问题不够明确，请补充股票代码或公司名称，"
                "例如'分析茅台2024Q3的盈利能力'"
            )

        logger.info("query_rewritten", original=original[:60], rewritten=rewritten[:80])
        return rewritten

    except QueryRewriteError:
        raise
    except asyncio.TimeoutError:
        logger.error("llm_rewrite_timeout", original=original[:60])
        raise QueryRewriteError(
            "问题不够明确，请补充股票代码或公司名称，"
            "例如'分析茅台2024Q3的盈利能力'"
        )
    except Exception as exc:
        logger.error("llm_rewrite_failed", original=original[:60], error=str(exc))
        raise QueryRewriteError(
            "问题不够明确，请补充股票代码或公司名称，"
            "例如'分析茅台2024Q3的盈利能力'"
        )


# ══════════════════════════════════════════════════
# 规则链：按顺序应用，每步返回改写后的字符串
# ══════════════════════════════════════════════════


# ── 1. 基础清洗 ──

def _normalize_whitespace(text: str) -> str:
    """合并连续空白，去除首尾空格。"""
    return re.sub(r"\s+", " ", text).strip()


def _normalize_punctuation(text: str) -> str:
    """全角标点转半角（保留中文语境）。"""
    mapping = {
        "，": ",", "。": ".", "！": "!", "？": "?",
        "；": ";", "：": ":", "（": "(", "）": ")",
        "“": '"', "”": '"', "‘": "'", "’": "'",
    }
    for full, half in mapping.items():
        text = text.replace(full, half)
    return text


# ── 2. 相对日期 → 绝对日期 ──

def _resolve_relative_dates(text: str, now: datetime | None = None) -> str:
    """将中文相对时间表达替换为绝对日期格式。"""
    if now is None:
        now = datetime.now()

    y = now.year
    m = now.month
    cur_q = (m - 1) // 3 + 1
    prev_q = cur_q - 1 if cur_q > 1 else 4
    prev_q_year = y if cur_q > 1 else y - 1

    rules = [
        # (原文模式, 替换为)
        ("前年", f"{y-2}年"),
        ("去年", f"{y-1}年"),
        ("今年", f"{y}年"),
        ("明年", f"{y+1}年"),
        ("上半年", f"{y}H1"),
        ("下半年", f"{y}H2"),
        ("上季度", f"{prev_q_year}Q{prev_q}"),
        ("本季度", f"{y}Q{cur_q}"),
        ("下季度", f"{y}Q{cur_q+1 if cur_q < 4 else 1}"),
        ("一季度", "Q1"),
        ("二季度", "Q2"),
        ("三季度", "Q3"),
        ("四季度", "Q4"),
        ("第一季度", "Q1"),
        ("第二季度", "Q2"),
        ("第三季度", "Q3"),
        ("第四季度", "Q4"),
        ("中报", "H1"),
        ("年报", ""),   # 年报无需季度后缀
    ]

    result = text
    for old, new in rules:
        if old in result:
            result = result.replace(old, new)

    # ── "X月份" → absolute YYYY-MM (resolve to most recent occurrence) ──
    result = re.sub(
        r'(\d{1,2})\s*月份',
        lambda m: _resolve_month(int(m.group(1)), now),
        result,
    )

    return result


def _resolve_month(month: int, now: datetime) -> str:
    """Resolve 'X月份' to the most recent occurrence of that month."""
    if not 1 <= month <= 12:
        return f"{month}月份"
    y = now.year
    # If the target month is after current month, it was last year
    if month > now.month:
        y -= 1
    return f"{y}-{month:02d}"


# ── 3. 股票别名 → 正式简称 ──

# 常见别名映射（可后续从配置文件或数据库加载）
_STOCK_ALIASES: dict[str, str] = {
    "茅台": "贵州茅台",
    "比亚迪": "比亚迪",
    "宁德": "宁德时代",
    "宁德时代": "宁德时代",
    "企鹅": "腾讯控股",
    "鹅厂": "腾讯控股",
    "宇宙行": "工商银行",
    "平安": "中国平安",
    "格力": "格力电器",
    "美的": "美的集团",
    "万科": "万科A",
    "招商银行": "招商银行",
    "兴业银行": "兴业银行",
    "中石油": "中国石油",
    "中石化": "中国石化",
    "中海油": "中国海油",
    "中移动": "中国移动",
    "中电信": "中国电信",
    "中联通": "中国联通",
    "神华": "中国神华",
    "长江电力": "长江电力",
    "五粮液": "五粮液",
    "隆基": "隆基绿能",
    "药明": "药明康德",
    "恒瑞": "恒瑞医药",
    "猪场": "网易",
    "菊厂": "华为",
    "蓝厂": "中国平安",
    "猫厂": "阿里巴巴",
    "狗厂": "京东",
}


def _normalize_stock_names(text: str) -> str:
    """常见股票别名替换为正式名称，帮助 LLM 准确匹配。"""
    result = text
    for alias, official in _STOCK_ALIASES.items():
        if alias in result and official not in result:
            result = result.replace(alias, official)
    return result


# ── 4. 数值单位标准化 ──

_UNIT_NORMALIZE: list[tuple[str, str]] = [
    (r"(\d+)个亿", r"\1亿"),
    (r"(\d+)万亿", r"\1万亿"),
    (r"(\d+)\s*万亿元", r"\1万亿"),
    (r"(\d+)\s*亿元人民币", r"\1亿"),
]


def _normalize_units(text: str) -> str:
    """统一数值 + 单位表达。"""
    result = text
    for pattern, replacement in _UNIT_NORMALIZE:
        result = re.sub(pattern, replacement, result)
    return result


# ── 3.5. 检索结果实体注入 ──

# Metrics to extract from retrieved documents
_EXTRACT_METRICS = [
    "ROE", "ROA", "净利率", "毛利率", "资产负债率", "产权比率",
    "营收", "净利润", "每股经营现金流", "权益乘数",
]

# Regex for report dates like "2024-03-31" or "2025-12-31"
_REPORT_DATE_PATTERN = re.compile(r'(\d{4}-\d{2}-\d{2})')


def _inject_retrieved_entities(text: str, retrieved: list[dict]) -> str:
    """从 RAG 检索结果中提取关键实体并注入原 query 末尾。

    提取: 股票代码、指标名、报告期（最多 5 个实体）。
    若 text 中已含该实体则跳过，避免重复。
    """
    if not retrieved:
        return text

    entities: list[str] = []

    for doc in retrieved:
        content = doc.get("content", "")

        # 提取股票代码
        code = str(doc.get("company_code", ""))
        if code and code not in text and code not in entities:
            entities.append(code)

        # 提取指标名
        for metric in _EXTRACT_METRICS:
            if metric in content and metric not in text and metric not in entities:
                entities.append(metric)

        # 提取报告期
        dates = _REPORT_DATE_PATTERN.findall(content)
        for d in dates:
            if d not in text and d not in entities:
                entities.append(d)

        if len(entities) >= 5:
            break

    if entities:
        return f"{text}（补充信息: {', '.join(entities[:5])}）"
    return text


# ── 5. 查询意图强化 ──

# 关键词 → 意图提示词（追加到 query 末尾帮助 LLM 判断）
_INTENT_HINTS: list[tuple[list[str], str]] = [
    (["盈利能力", "财务状况", "偿债能力", "现金流"], "financial_analysis"),
    (["股价", "价格", "PE", "PB", "市值", "涨跌幅", "行情"], "simple_query"),
    (["新闻", "舆情", "最新动态", "消息", "公告"], "sentiment_analysis"),
    (["报告", "全面分析", "综合分析"], "comprehensive"),
]


def _append_intent_hint(text: str) -> str:
    """基于关键词在 query 末尾追加隐式意图标记（仅当无明确冲突时）。"""
    scores: dict[str, int] = {}
    for keywords, intent in _INTENT_HINTS:
        scores[intent] = sum(1 for kw in keywords if kw in text)

    if not scores or max(scores.values()) == 0:
        return text

    # 取最高分意图
    top = max(scores, key=scores.get)  # type: ignore[arg-type]
    # 仅当最高分 ≥ 2 且无平局时才追加
    if scores[top] >= 2 and list(scores.values()).count(scores[top]) == 1:
        # 在 query 末尾追加隐式意图标记，帮助 classifier 判断
        hint = f"\n[意图倾向: {top}]"
        return text + hint

    return text


# ══════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════

# 预处理管道：按顺序执行
_PIPELINE = [
    ("normalize_whitespace", _normalize_whitespace),
    ("resolve_dates", _resolve_relative_dates),
    ("normalize_names", _normalize_stock_names),
    ("normalize_units", _normalize_units),
    ("normalize_punctuation", _normalize_punctuation),
]


def preprocess(text: str, steps: list[str] | None = None) -> str:
    """对用户查询做规则预处理。

    Args:
        text: 原始用户输入
        steps: 指定要执行的步骤名列表，None 表示全部执行。
               可选值: normalize_whitespace, resolve_dates, normalize_names,
                       normalize_units, normalize_punctuation, append_intent_hint

    Returns:
        处理后的字符串
    """
    result = text
    for name, func in _PIPELINE:
        if steps is None or name in steps:
            try:
                before = result
                result = func(result)
                if result != before:
                    logger.debug("preprocess_step", step=name,
                                 before=before[:60], after=result[:60])
            except Exception as exc:
                logger.warning("preprocess_step_error", step=name, error=str(exc))
    if result != text:
        logger.info("query_preprocessed", original=text[:80], cleaned=result[:80])
    return result


# ── 异步 RAG 增强管线 ──

async def preprocess_with_rag(
    text: str,
    threshold: float | None = None,
    top_k: int | None = None,
) -> str:
    """对用户查询执行检索增强的预处理。

    管线顺序:
      1. 同步规则预处理（日期、别名、空白）
      2. RAG 检索 top-k 文档
      3. 规则实体注入
      4. 置信度检查 → LLM 改写（如需要）

    Args:
        text: 原始用户输入
        threshold: 触发 LLM 改写的相似度阈值，默认 RAG_REWRITE_THRESHOLD
        top_k: RAG 检索文档数，默认 RAG_REWRITE_TOP_K

    Returns:
        处理后的查询字符串

    Raises:
        QueryRewriteError: LLM 改写失败且不应降级
    """
    from constants.metrics import RAG_REWRITE_THRESHOLD, RAG_REWRITE_TOP_K

    if threshold is None:
        threshold = RAG_REWRITE_THRESHOLD
    if top_k is None:
        top_k = RAG_REWRITE_TOP_K

    # Step 1: Rule preprocessing (sync)
    cleaned = preprocess(text, steps=[
        "normalize_whitespace", "resolve_dates", "normalize_names",
    ])

    # Step 2: RAG retrieval
    retrieved = await _retrieve_context(cleaned, top_k=top_k)

    # Step 3: Entity injection
    injected = _inject_retrieved_entities(cleaned, retrieved)

    # Step 4: Confidence gate -> LLM rewrite
    if _should_llm_rewrite(retrieved, threshold):
        rewritten = await _llm_rewrite_query(cleaned, retrieved)
        logger.info("query_rag_rewrite", original=text[:60],
                    injected=injected[:60], rewritten=rewritten[:60])
        return rewritten

    logger.info("query_rag_entity_inject", original=text[:60],
                num_docs=len(retrieved), result=injected[:80])
    return injected
