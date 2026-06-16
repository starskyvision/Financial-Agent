FINANCIAL_ANALYSIS_SYSTEM = """你是一个资深金融分析师。基于提供的杜邦分解结果和异动检测数据，生成财务分析评述。

## 分析结构
1. **盈利概览**: 一两句话评价 ROE 水平和变化趋势
2. **杜邦因子分析**: 分别分析净利率、资产周转率、权益乘数，指出哪个因子是 ROE 的主要驱动/拖累。引用具体数值。
3. **异常预警**: 如果存在异动指标，逐项列出并给出可能的业务原因解释。

## 重要规则
- 必须引用输入数据中的具体数值，不得编造
- 数值保留 2 位小数
- 篇幅: 200-400 字
"""


def build_financial_analysis_prompt(dupont: dict, anomalies: list, company_name: str, report_date: str) -> str:
    dupont_str = f"""杜邦分解结果:
- ROE: {dupont['roe']}
- 净利率: {dupont['net_margin']}
- 资产周转率: {dupont['asset_turnover']}
- 权益乘数: {dupont['equity_multiplier']}
- 数据有效性: {'有效' if dupont.get('is_valid') else '无效: ' + str(dupont.get('missing_metrics', []))}
"""
    anomaly_str = "异动检测:\n"
    if not anomalies:
        anomaly_str += "本期未发现显著异动（同比变动均在 30% 以内）"
    else:
        for a in anomalies:
            direction = "上升" if a.get("change_pct", 0) > 0 else "下降"
            anomaly_str += (f"- {a['metric_name']}: {direction} {abs(a.get('change_pct', 0))*100:.1f}% "
                            f"(当前 {a['current_value']}, 同期 {a.get('yoy_value')}, 严重程度: {a['severity']})\n")

    return f"""请分析 {company_name} 在 {report_date} 的财务状况。

{dupont_str}

{anomaly_str}"""
