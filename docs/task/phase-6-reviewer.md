# Phase 6 — 校验总结 Agent

**优先级**: P1　|　**前置**: Phase 4, Phase 5　|　**预计工时**: 2.5 天

## 目标

实现校验总结 Agent 节点，完成报告生成、事实核对和反思循环，针对 comprehensive 意图输出高质量投研报告。

## 子任务

### 6.1 实现报告生成 Prompt

📁 `backend/prompts/report_generation.md`

- [ ] 编写 System Prompt，定义报告输出结构：
  1. **标题** — `{公司名}（{股票代码}）投研分析报告`
  2. **核心摘要** — 3~5 句总结核心发现
  3. **财务分析** — 杜邦分解结果 + 因子解读
  4. **异动预警** — 如有异常指标，列出并分析原因
  5. **舆情研判** — 近期新闻情绪总结 + 关键主题
  6. **风险提示** — 基于数据和舆情的风险因子
  7. **免责声明** — "本报告由 AI 自动生成，仅供参考，不构成投资建议"
- [ ] 要求 LLM 在报告中对每个关键数字标注来源（如"来源：2024Q3 财报"）
- [ ] Few-shot 包含完整报告示例
- [ ] Token 限制：生成预留 8K tokens

**验收**: Prompt 通过 LLM Playground 测试，输出符合 7 段结构

### 6.2 实现报告生成节点

📁 `backend/agents/reviewer/report_generator.py`

- [ ] 实现 LangGraph 节点函数 `async def report_generator_node(state: AgentState) -> AgentState`
- [ ] 整合三个上游输出：
  - `state["raw_data"]` → 报告中的数据引用
  - `state["financial_analysis"]` → 财务分析段落
  - `state["sentiment_result"]` → 舆情研判段落
- [ ] 调用 `LLMService.invoke("reviewer", ...)` 生成报告
- [ ] 报告写入 `state["draft_report"]`
- [ ] 节点异常时写入 `state["errors"]` 并保留上次有效草稿

**验收**: 传入完整的 raw_data + financial_analysis + sentiment_result → draft_report 包含 7 段结构

### 6.3 实现事实核对模块

📁 `backend/agents/reviewer/fact_checker.py`

- [ ] 实现 `async def verify_facts(report: str, company_code: str, db_session) -> list[str]`
- [ ] **纯 Python 逻辑，不经过 LLM**（防止用幻觉校验幻觉）
- [ ] 步骤 1 — 从报告中正则提取数值断言：
  ```python
  # 匹配模式如 "ROE为12.3%" "营收达到123.45亿元" "净利润56.78亿元"
  pattern = r'(ROE|ROA|营收|净利润|毛利率|净利率|现金流)[^\d]*(\d+\.?\d*)\s*(%|亿元|万元)?'
  ```
- [ ] 步骤 2 — 查询 MySQL `financial_data` 表中对应指标源数据
- [ ] 步骤 3 — 计算偏差：`abs(report_value - source_value) / source_value`
- [ ] 步骤 4 — 偏差 >1% → 生成错误描述：
  ```python
  f"{metric_name}: 报告值 {report_value}，源数据 {source_value}，偏差 {deviation:.1%}"
  ```
- [ ] 若无匹配的源数据指标，返回提示而非错误（"指标 XX 无源数据可供校验"）

**验收**: 给定一份含已知错误的报告 → `verify_facts()` 返回正确的错误列表

### 6.4 实现重写节点

📁 `backend/agents/reviewer/rewriter.py`

- [ ] 实现 LangGraph 节点函数 `async def rewriter_node(state: AgentState) -> AgentState`
- [ ] 将 `state["errors"]` 注入 Prompt：
  ```
  "以下数据与源数据库不匹配，请修正后重新生成报告：
   - ROE: 报告值 12.3%，源数据 11.8%
   - ..."
  ```
- [ ] 调用与 `report_generator_node` 相同的 LLM 配置重新生成
- [ ] 更新 `state["draft_report"]`，`state["retry_count"] += 1`
- [ ] 清空 `state["errors"]`（下一轮事实核对会重新检查）

**验收**: 重写后再次调用 `verify_facts`，错误数量减少

### 6.5 实现反思循环条件边

📁 `backend/agents/reviewer/router.py`

- [ ] 实现 `def route_after_review(state: AgentState) -> str`
- [ ] 条件逻辑：
  ```python
  if state["errors"] and state["retry_count"] < 3:
      return "rewriter"        # 还有错误且未达上限 → 重写
  else:
      return "output"          # 无错误或已达上限 → 输出
  ```
- [ ] 达到上限时在报告末尾追加 `⚠️ 自动校验未完全通过` 段落，包含未解决问题列表

**验收**: errors 非空 + retry=1 → 返回 rewriter；errors 空 → 返回 output

### 6.6 编写校验总结单元测试

📁 `backend/tests/agents/test_reviewer.py`

- [ ] 测试 `verify_facts` 正确提取数值并与源数据比对
- [ ] 测试偏差 ≤1% 时不报错，偏差 >1% 时报错
- [ ] 测试报告中无可提取数字时返回空 errors
- [ ] Mock LLM 调用，测试完整"生成→校验→重写"循环
- [ ] 测试 3 轮后强制输出 + 附录标识
- [ ] 测试 `route_after_review` 的各种条件组合

**验收**: `pytest tests/agents/test_reviewer.py` 全部通过

---

## 产出物

- [ ] `backend/prompts/report_generation.md` — 报告生成 Prompt
- [ ] `backend/agents/reviewer/__init__.py`
- [ ] `backend/agents/reviewer/report_generator.py` — 报告生成节点
- [ ] `backend/agents/reviewer/fact_checker.py` — 事实核对模块
- [ ] `backend/agents/reviewer/rewriter.py` — 重写节点
- [ ] `backend/agents/reviewer/router.py` — 反思循环条件边
- [ ] `backend/tests/agents/test_reviewer.py` — 单元测试

*关联文档: [设计规格 §3.5](../superpowers/specs/2026-06-16-financial-agent-mvp-design.md#35-校验总结-agent仅-comprehensive-通道), [设计规格 §7 条件边规则](../superpowers/specs/2026-06-16-financial-agent-mvp-design.md#七langgraph-条件边规则)*
