REPORT_GENERATION_SYSTEM = """你是一个资深投研报告撰写专家。基于提供的财务分析结果和舆情数据，生成结构化的投研报告。

## 报告结构（严格按此顺序）

### 1. 标题
{公司名}（{股票代码}）投研分析报告

### 2. 核心摘要
3-5 句话总结核心发现，覆盖财务表现和舆情概况。

### 3. 财务分析
- 杜邦分解：ROE={X}，分解为净利率={X} × 资产周转率={X} × 权益乘数={X}
- 因子解读：哪个因子是主要驱动/拖累

### 4. 异动预警
如有异常指标，逐项列出具体数值、变动幅度和可能原因。

### 5. 舆情研判
- 整体情感倾向 + 关键主题
- 代表性新闻列举（2-3 条，含发布时间和原文链接）

### 6. 风险提示
基于财务数据和舆情分析的潜在风险因子（3-5 条）

### 7. 数据来源
在报告末尾列出所有数据来源：
- 财务数据: AKShare (https://akshare.akfamily.xyz)
- 新闻舆情: 东方财富 (https://www.eastmoney.com)

### 8. 免责声明
> 本报告由 AI 自动生成，仅供参考，不构成投资建议。

## ⚠️ 数据来源强制规则（违反将导致报告不合格）

**每项数据后必须使用以下 EXACT 标签之一，不能自创来源名：**
- 财务指标 → 标注 `[来源: AKShare]`
- 新闻/舆情 → 标注 `[来源: 东方财富]`
- 知识库研报 → 标注 `[来源: 知识库]`

**禁止使用 "杜邦分解数据"、"财务分析结果"、"异动检测"、"舆情分析" 等作为来源名！**

## 重要规则
- 所有关键数字必须附带上述 EXACT 来源标签
- 不得编造任何数值
- 如有新闻原文链接，必须在文中保留
- 篇幅: 800-2000 字

## 🚫 严禁事项
- **严禁输出任何开场白、客套话或元评论**，如"好的，作为资深分析师..."、"基于您提供的数据..."、"我已收到修正要求..."等
- **严禁在报告前后添加任何解释说明**，直接以标题"# {公司名}（{股票代码}）投研分析报告"开头
- **修正轮次中严禁提及"上一轮报告"、"修正要求"等内部流程用语**
- 报告必须是独立完整的最终版本，读者不应感知到任何生成或修正过程
"""


def build_report_prompt(state: dict, retry_context: str = "") -> str:
    code = state.get("company_code", "")
    name = state.get("company_name", code)
    fin = state.get("financial_analysis") or {}
    sent = state.get("sentiment_result") or {}
    dupont = fin.get("dupont_decomposition", {})
    anomalies = fin.get("anomaly_flags", [])
    narrative = fin.get("narrative", "")

    # 格式化杜邦数据——资产周转率为 0 时标注不可用，防止 LLM 幻觉
    at_val = dupont.get('asset_turnover', 0)
    at_display = f"{at_val:.4f}" if at_val and at_val > 0 else "N/A（总资产数据缺失，不可用）"
    nm_val = dupont.get('net_margin', 0)
    nm_display = f"{nm_val:.4f}" if nm_val and nm_val > 0 else "N/A"
    roe_val = dupont.get('roe', 0)
    roe_display = f"{roe_val:.4f}" if roe_val and roe_val > 0 else "N/A"
    em_val = dupont.get('equity_multiplier', 0)
    em_display = f"{em_val:.4f}" if em_val and em_val > 0 else "N/A"

    # 确定数据来源标签和报告期
    raw_data = state.get("raw_data") or {}
    data_sources = raw_data.get("data_sources", ["AKShare"])
    source_label = "、".join(data_sources)
    fin_metrics = raw_data.get("financial_metrics", {})
    report_date = fin_metrics.get("_report_date", "") or state.get("report_date", "")

    prompt = f"""请为 {name}（{code}）生成一份投研分析报告。"""

    if report_date:
        prompt += f"\n**数据所属报告期: {report_date}**\n"

    prompt += f"""
## 数据来源声明
本报告所有财务数据均来自 **{source_label}**，舆情数据来自东方财富新闻。
请在报告中每项关键数据后标注数据来源，格式如：
- "ROE = 1.63% [来源: AKShare]"
- "净利率 52.2% 为行业领先 [来源: AKShare]"
- "舆情整体偏正面 [来源: 东方财富]"
**不得编造任何数值，不确定的数据标注"[待核实]"。**
**报告中必须明确标注数据所属报告期（如"2024-12-31年报"）。**

## 输入数据

### 财务分析结果（数据来源: {source_label}）
{narrative}

### 杜邦分解数据（数据来源: {source_label}）
- ROE: {roe_display}
- 净利率: {nm_display}
- 资产周转率: {at_display}
- 权益乘数: {em_display}

**重要提示**：当资产周转率显示为 N/A 时，说明总资产数据缺失，杜邦公式 ROE = 净利率 × 资产周转率 × 权益乘数 无法闭合。
请勿编造资产周转率数值，也不要基于缺失数据做"资产周转率低"之类的判断。
ROE 直接来自数据源，分析时应聚焦净利率和权益乘数两个有效因子。

### 异动检测（数据来源: {source_label}）
"""

    if anomalies:
        for a in anomalies:
            prompt += f"- {a.get('metric_name')}: 变动 {a.get('change_pct', 0)*100:.1f}%（严重程度: {a.get('severity')}）\n"
    else:
        prompt += "未发现显著异动\n"

    # 兼容 key_topics 新旧格式：旧 ["str"] / 新 [{"topic":"","description":""}]
    raw_topics = sent.get('key_topics', [])
    if raw_topics and isinstance(raw_topics[0], dict):
        topic_strs = [t.get("topic", "") for t in raw_topics if t.get("topic")]
    else:
        topic_strs = [str(t) for t in raw_topics]

    prompt += f"""
### 舆情分析（数据来源: 东方财富新闻）
- 整体情感: {sent.get('overall_sentiment', 'N/A')}
- 关键主题: {', '.join(topic_strs) if topic_strs else 'N/A'}
- 总结: {sent.get('summary', 'N/A')}
"""
    # --- 全量新闻列表（LLM 自主筛选最具代表性的 2-3 条） ---
    raw_data = state.get("raw_data") or {}
    all_news = raw_data.get("news_headlines", [])
    if all_news:
        prompt += "\n### 全部新闻列表（共 " + str(len(all_news)) + " 条，含情感标签）\n"
        prompt += "请从中选取 **2-3 条最具代表性** 的新闻写入报告（优先选择情感极端、与公司核心业务相关的），并标注发布时间和原文链接：\n\n"
        for n in all_news[:30]:
            title = n.get("title", "")
            pub_time = n.get("published_at", "")[:16] if n.get("published_at") else ""
            url = n.get("url", "")
            time_str = f" ({pub_time})" if pub_time else ""
            link_str = f" {url}" if url else ""
            prompt += f"- {title}{time_str}{link_str}\n"

    # --- RAG 上下文注入 ---
    rag_context = state.get("rag_context", "")
    if rag_context:
        prompt += f"""
### 参考研报（来自知识库）
{rag_context}

基于以上参考信息与分析数据生成投研报告。引用参考研报信息时，
在正文中以 [来源: xxx研报] 标注出处。
"""

    if retry_context:
        prompt += f"\n## 修正要求\n{retry_context}\n"

    # --- 重写轮次：注入上次修正后的报告作为参考 ---
    draft = state.get("draft_report", "")
    if draft and state.get("retry_count", 0) > 0:
        prompt += f"\n## 上一轮修正后的报告（请基于此版本修正，而非从头生成）\n{draft}\n"
        prompt += "\n请基于上述修正要求，对上轮报告进行针对性修改后输出完整报告。\n"

    return prompt
