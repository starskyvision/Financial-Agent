FETCH_FINANCIALS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_financials",
        "description": "拉取指定股票在指定报告期的财务指标数据",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "company_code": {"type": "string", "description": "A股6位数字股票代码，如 600519"},
                "report_date": {"type": "string", "description": "报告期日期，格式 YYYY-MM-DD"},
                "metrics": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "revenue", "net_profit", "roe", "roa",
                            "gross_margin", "net_margin", "operating_cashflow",
                            "free_cashflow", "total_assets", "total_liabilities",
                            "asset_turnover", "equity_multiplier"
                        ]
                    },
                    "description": "需要拉取的指标列表"
                }
            },
            "required": ["company_code", "metrics"]
        }
    }
}
