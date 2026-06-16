REPORT_GENERATION_SYSTEM = """你是一个资深投研报告撰写专家。基于提供的财务分析结果和舆情数据，生成结构化的投研报告。

## 报告结构（严格按此顺序）

### 1. 标题
{公司名}（{股票代码}）投研分析报告

### 2. 核心摘要
3-5 句话总结核心发现，覆盖财务表现和舆情概况。

### 3. 财务分析
- 杜邦分解：ROE={X}，分解为净利率={X} × 资产周转率={X} × 权益乘数={X}
- 因子解读：哪个因子是主要驱动/拖累
- 所有数值引用必须标注来源

### 4. 异动预警
如有异常指标，逐项列出具体数值、变动幅度和可能原因。

### 5. 舆情研判
- 整体情感倾向 + 关键主题
- 代表性新闻列举（2-3 条）

### 6. 风险提示
基于财务数据和舆情分析的潜在风险因子（3-5 条）

### 7. 免责声明
> 本报告由 AI 自动生成，仅供参考，不构成投资建议。

## 重要规则
- 所有关键数字必须附带来源标注
- 不得编造任何数值
- 篇幅: 800-1500 字
"""


def build_report_prompt(state: dict, retry_context: str = "") -> str:
    code = state.get("company_code", "")
    name = state.get("company_name", code)
    fin = state.get("financial_analysis") or {}
    sent = state.get("sentiment_result") or {}
    dupont = fin.get("dupont_decomposition", {})
    anomalies = fin.get("anomaly_flags", [])
    narrative = fin.get("narrative", "")

    prompt = f"""请为 {name}（{code}）生成一份投研分析报告。

## 输入数据

### 财务分析结果
{narrative}

### 杜邦分解数据
- ROE: {dupont.get('roe', 'N/A')}
- 净利率: {dupont.get('net_margin', 'N/A')}
- 资产周转率: {dupont.get('asset_turnover', 'N/A')}
- 权益乘数: {dupont.get('equity_multiplier', 'N/A')}

### 异动检测
"""
    if anomalies:
        for a in anomalies:
            prompt += f"- {a.get('metric_name')}: 变动 {a.get('change_pct', 0)*100:.1f}%（严重程度: {a.get('severity')}）\n"
    else:
        prompt += "未发现显著异动\n"

    prompt += f"""
### 舆情分析
- 整体情感: {sent.get('overall_sentiment', 'N/A')}
- 关键主题: {', '.join(sent.get('key_topics', []))}
- 总结: {sent.get('summary', 'N/A')}
"""
    if retry_context:
        prompt += f"\n## 修正要求\n{retry_context}\n"
    return prompt
