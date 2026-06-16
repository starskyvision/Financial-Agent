"""
共享指标映射 — 所有模块的单一真相源。

中文列名 → 内部 metric 名的映射集中在此处，
避免 akshare_adapter / output_node / fact_checker 中的重复定义。
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

ABSOLUTE_FORMAT_METRICS = {
    "revenue", "net_profit",
}

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
    "现金流": "operating_cashflow",
}


def is_percent_metric(name: str) -> bool:
    return name in PERCENT_FORMAT_METRICS


def is_billion_metric(name: str) -> bool:
    return name in ABSOLUTE_FORMAT_METRICS
