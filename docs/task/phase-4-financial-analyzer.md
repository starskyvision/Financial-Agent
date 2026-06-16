# Phase 4 — 财务分析 Agent

**优先级**: P1　|　**前置**: Phase 3　|　**预计工时**: 2 天

## 目标

实现财务分析 Agent 节点，完成杜邦分解计算和同比异动检测，输出结构化分析结果和自然语言评述。

## 子任务

### 4.1 实现杜邦分解计算引擎

📁 `backend/agents/financial_analyzer/dupont.py`

- [ ] 实现 `def compute_dupont(metrics: dict) -> DupontResult`
- [ ] `DupontResult` 数据类结构：

  ```python
  class DupontResult(BaseModel):
      roe: float                          # ROE
      net_margin: float                   # 净利率 (=净利润/营收)
      asset_turnover: float               # 资产周转率 (=营收/总资产)
      equity_multiplier: float            # 权益乘数 (=总资产/净资产)
      is_valid: bool                      # 输入数据是否满足计算条件
      missing_metrics: list[str]           # 缺失的必要指标
  ```

- [ ] 输入数据校验：三项计算所需的指标（净利润、营收、总资产、净资产）全部存在才计算，否则 `is_valid=False`
- [ ] 计算结果保留 2 位小数
- [ ] 除零保护（资产周转率和权益乘数分母可能为 0）

**验收**: 给定茅台标准三季报数据 → ROE 与 Wind/同花顺发布值偏差 <1%

### 4.2 实现同比异动检测

📁 `backend/agents/financial_analyzer/anomaly.py`

- [ ] 实现 `async def detect_anomalies(code: str, current_metrics: dict, db_session) -> list[Anomaly]`
- [ ] 查询 MySQL `financial_data` 表中同公司上年同期数据
- [ ] `Anomaly` 结构：`{metric_name, current_value, yoy_value, change_pct, severity: "warning"|"critical"}`
- [ ] 判定阈值：
  - `change_pct > 30% AND change_pct <= 50%` → `severity="warning"`
  - `change_pct > 50%` → `severity="critical"`
- [ ] 无历史数据时返回空列表（不误报）

**验收**: 给定一组变动 40% 的指标 → 返回 1 条 warning 级别预警

### 4.3 实现财务分析 Prompt

📁 `backend/prompts/financial_analysis.md`

- [ ] 编写 System Prompt，要求 LLM 基于杜邦分解结果和异动数据生成分析评述
- [ ] 评述模板包含三段：
  1. 盈利概览（ROE 水平评价）
  2. 杜邦因子分析（哪个因子是主要驱动/拖累）
  3. 异常预警（如有异动，解释可能原因）
- [ ] 要求 LLM **不编造数据**——必须引用输入的 `dupont_result` 和 `anomalies` 中的具体数值
- [ ] Few-shot 包含正确引用和错误引用（标注为反面示例）

**验收**: Prompt 通过 LLM Playground 测试，生成的评述中数值与输入一致

### 4.4 实现财务分析 LangGraph 节点

📁 `backend/agents/financial_analyzer/node.py`

- [ ] 实现 `async def financial_analyzer_node(state: AgentState) -> AgentState`
- [ ] 从 `state["raw_data"]["financial_metrics"]` 读取指标
- [ ] 调用 `compute_dupont()` 和 `detect_anomalies()`
- [ ] 调用 `LLMService.invoke("financial_analyzer", ...)` 生成分析评述
- [ ] 写入 `state["financial_analysis"]`：
  ```python
  {
      "dupont_decomposition": DupontResult.model_dump(),
      "anomaly_flags": [Anomaly.model_dump(), ...],
      "narrative": "贵州茅台2024Q3 ROE为12.3%...",
      "analyst_confidence": "high" | "medium" | "low"  # 基于数据完整度
  }
  ```
- [ ] 节点异常不中断图——写入 `state["errors"]` 并设置 `financial_analysis=None`

**验收**: 作为 LangGraph 节点执行后 State 中 financial_analysis 包含 dupont + narrative

### 4.5 编写财务分析单元测试

📁 `backend/tests/agents/test_financial_analyzer.py`

- [ ] 测试杜邦分解计算正确性（标准数据→标准结果）
- [ ] 测试除零保护
- [ ] 测试缺失指标时 `is_valid=False`
- [ ] 测试异动检测阈值边界（29.9%→不报警，30.1%→warning）
- [ ] 测试无历史数据时返回空异常列表
- [ ] Mock LLM 调用，测试节点完整流程

**验收**: `pytest tests/agents/test_financial_analyzer.py` 全部通过

---

## 产出物

- [ ] `backend/agents/financial_analyzer/__init__.py`
- [ ] `backend/agents/financial_analyzer/dupont.py` — 杜邦分解引擎
- [ ] `backend/agents/financial_analyzer/anomaly.py` — 异动检测
- [ ] `backend/agents/financial_analyzer/node.py` — LangGraph 节点
- [ ] `backend/prompts/financial_analysis.md` — 分析 Prompt
- [ ] `backend/tests/agents/test_financial_analyzer.py` — 单元测试

*关联文档: [设计规格 §3.3](../superpowers/specs/2026-06-16-financial-agent-mvp-design.md#33-财务分析-agent)*
