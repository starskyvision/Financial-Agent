FINANCIAL_ANALYSIS_SYSTEM = """你是一个资深金融分析师。基于提供的杜邦分解结果和异动检测数据，生成财务分析评述。

## 分析结构
1. **盈利概览**: 一两句话评价 ROE 水平和变化趋势
2. **杜邦因子分析**: 分别分析净利率、资产周转率、权益乘数，指出哪个因子是 ROE 的主要驱动/拖累。引用具体数值。
3. **异常预警**: 如果存在异动指标，逐项列出并给出可能的业务原因解释。

## 重要规则
- 必须引用输入数据中的具体数值，不得编造
- 数值保留 2 位小数
- **绝对禁止**: 不得在输出中提到 Q1/Q2/Q3/Q4 或"第一/二/三/四季度"等描述，
  必须使用输入中给出的确切报告期日期（如 2025-12-31）
- 篇幅: 200-400 字
- **严禁输出任何开场白**（如"好的，作为资深金融分析师..."、"基于您提供的数据..."），
  直接以"盈利概览"开头
"""


def build_financial_analysis_prompt(dupont: dict, anomalies: list, company_name: str, report_date: str) -> str:
    # 当资产周转率为 0（total_assets 数据缺失）时标注不可用
    at_val = dupont.get('asset_turnover')
    at_display = f"{at_val:.4f}" if at_val is not None and at_val > 0 else "N/A（总资产数据缺失）"
    nm_val = dupont.get('net_margin')
    nm_display = f"{nm_val:.4f}" if nm_val is not None else "N/A"
    roe_val = dupont.get('roe')
    roe_display = f"{roe_val:.4f}" if roe_val is not None else "N/A"
    em_val = dupont.get('equity_multiplier', 0)

    dupont_str = f"""杜邦分解结果:
- ROE: {roe_display}
- 净利率: {nm_display}
- 资产周转率: {at_display}
- 权益乘数: {em_val:.4f}
- 数据有效性: {'有效' if dupont.get('is_valid') else '无效: ' + str(dupont.get('missing_metrics', []))}
- 注意: 资产周转率为 N/A 时，杜邦公式无法闭合，ROE 直接来自数据源。
"""
    anomaly_str = "异动检测:\n"
    if not anomalies:
        anomaly_str += "本期未发现显著异动（同比变动均在 30% 以内）"
    else:
        for a in anomalies:
            direction = "上升" if a.get("change_pct", 0) > 0 else "下降"
            yoy_val = a.get('yoy_value')
            yoy_str = f"{yoy_val}" if yoy_val is not None else "N/A"
            anomaly_str += (f"- {a['metric_name']}: {direction} {abs(a.get('change_pct', 0))*100:.1f}% "
                            f"(当前 {a['current_value']}, 同期 {yoy_str}, 严重程度: {a['severity']})\n")

    return f"""请分析 {company_name} 在 {report_date} 的财务状况。

{dupont_str}

{anomaly_str}"""
