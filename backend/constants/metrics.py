"""
共享指标映射 — 所有模块的单一真相源。

中文列名 → 内部 metric 名的映射集中在此处，
避免 akshare_adapter / output_node / fact_checker 中的重复定义。

所有硬编码指标列表和格式分类必须集中在此文件中定义。
"""

# ============================================================
# A 股列名 → metric 名（stock_financial_abstract_ths）
# ============================================================
A_SHARE_COLUMN_MAP = {
    "净利润": "net_profit",
    "营业总收入": "revenue",
    "净资产收益率-摊薄": "roe",
    "净资产收益率": "roe",
    "总资产收益率": "roa",
    "销售毛利率": "gross_margin",
    "销售净利率": "net_margin",
    "每股经营现金流": "operating_cashflow_per_share",
    "资产负债率": "debt_ratio",
    "产权比率": "equity_ratio",
}

# ============================================================
# 港股列名 → metric 名（stock_financial_hk_analysis_indicator_em）
# ============================================================
HK_COLUMN_MAP = {
    "OPERATE_INCOME": "revenue",
    "HOLDER_PROFIT": "net_profit",
    "ROE_AVG": "roe",
    "ROA": "roa",
    "GROSS_PROFIT_RATIO": "gross_margin",
    "NET_PROFIT_RATIO": "net_margin",
    "DEBT_ASSET_RATIO": "debt_ratio",
    "BPS": "book_value_per_share",
    "BASIC_EPS": "eps",
    "PER_NETCASH_OPERATE": "operating_cashflow_per_share",
}

# ============================================================
# 面向用户的指标中文标签
# ============================================================
METRIC_LABELS = {
    "revenue": "营收(亿)",
    "net_profit": "净利润(亿)",
    "roe": "ROE",
    "roa": "ROA",
    "gross_margin": "毛利率",
    "net_margin": "净利率",
    "debt_ratio": "资产负债率",
    "equity_ratio": "产权比率",
    "operating_cashflow_per_share": "每股经营现金流",
    "book_value_per_share": "每股净资产",
    "eps": "每股收益",
    "dividend_per_share": "每股股息",
    "dividend_yield": "股息率",
    "revenue_yoy": "营收同比",
}

# ============================================================
# 指标显示格式分类
# ============================================================
PERCENT_FORMAT_METRICS = {
    "roe", "roa", "gross_margin", "net_margin", "debt_ratio",
    "dividend_yield", "revenue_yoy",
}

# ============================================================
# 指标拉取列表 — data_collector 按意图拉取的指标集
# ============================================================
SIMPLE_QUERY_METRICS = ["revenue", "net_profit"]

DEFAULT_METRICS_FETCH = [
    "revenue", "net_profit", "roe", "gross_margin",
    "net_margin", "operating_cashflow_per_share",
    "debt_ratio", "equity_ratio",
]

# ============================================================
# 事实核对用：报告中的中文指标名 → metric 名
# ============================================================
FACT_CHECK_MAP = {
    "ROE": "roe",
    "ROA": "roa",
    "净利润": "net_profit",
    "营收": "revenue",
    "净利率": "net_margin",
    "毛利率": "gross_margin",
    "经营现金流": "operating_cashflow_per_share",
    "现金流": "operating_cashflow_per_share",
    "每股经营现金流": "operating_cashflow_per_share",
    "资产负债率": "debt_ratio",
}


# NOTE: is_percent_metric / is_billion_metric removed — callers use
# PERCENT_FORMAT_METRICS directly. See akshare_adapter.py for parse helpers.

# ============================================================
# 共享阈值与限制常量（所有模块单一真相源）
# ============================================================

# Dupont 分析
ROE_DEVIATION_TOLERANCE = 0.05  # ROE 公式闭合偏差 > 5% 标记不一致

# 异常检测
ANOMALY_MEDIUM_CONFIDENCE_THRESHOLD = 3  # 超过此数量的异常 → medium 置信度

# 数据拉取
MAX_NEWS_FETCH = 30       # AKShare 单次最多拉取新闻条数
NEWS_MAX_LENGTH = 200     # 新闻摘要截断长度
MAX_NEWS_PER_BATCH = 30   # 舆情分析单批最多处理的新闻数
NEWS_SUMMARY_TRUNCATE = 100  # 舆情分析中摘要截断长度

# RAG 检索
RAG_TOP_K_DEFAULT = 5     # RAG 检索默认 top-k
RAG_CONTENT_TRUNCATE = 2000  # RAG 检索结果内容截断长度（完整段落）

# 输出格式化
OUTPUT_NEWS_DETAIL_LIMIT = 5  # 输出节点最多展示的新闻明细数

# 意图分类
MAX_HISTORY_TURNS = 4     # 意图分类携带的历史轮数

# 检索增强改写
RAG_REWRITE_THRESHOLD = 0.5   # top-1 相似度低于此值触发 LLM 改写
RAG_REWRITE_TOP_K = 3         # 检索增强所用的文档数
LLM_REWRITE_TIMEOUT = 3.0     # LLM 改写超时（秒）
