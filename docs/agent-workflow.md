# Agent 状态流转

## LangGraph StateGraph 流转图

```
START
  │
  ▼
┌──────────┐
│ 数据收集   │  结构化抓取 Wind / PDF 解析
│  Agent    │  → State.raw_data
└────┬─────┘
     │
     ▼
┌──────────┐
│ 财务分析   │  杜邦分解 / 现金流异动检测
│  Agent    │  → State.financial_metrics
└────┬─────┘
     │
     ▼
┌──────────┐
│ 舆情解读   │  新闻情感 / 论坛聚合
│  Agent    │  → State.sentiment_result
└────┬─────┘
     │
     ▼
┌──────────┐
│ 校验总结   │  事实核对 / 报告草稿生成
│  Agent    │  → State.draft_report
└────┬─────┘
     │
     ▼
  ┌─────────────────┐
  │ 条件边判断        │
  │ errors 非空       │
  │ AND retry < 3?   │
  └────┬───────┬─────┘
       │YES    │NO
       ▼       ▼
   ┌──────┐  ┌──────┐
   │ 重写  │  │ 输出  │
   │ 节点  │  │ 节点  │
   └──┬───┘  └──────┘
      │
      └──→ 回到校验总结 Agent（retry_count += 1）
```

## 反思循环说明

1. 校验 Agent 将 draft_report 中的关键数据与 MySQL `financial_data` 源表逐项比对
2. 若发现矛盾（如报告中的 ROE 与源数据偏差 >1%），将差异写入 `State.errors`
3. 条件边检测到 `errors` 非空且 `retry_count < 3`，路由至重写节点
4. 重写节点将错误信息注入 prompt，要求 LLM 修正后重新生成
5. 最多 3 轮反思，超过后强制输出并在报告中标注"自动校验未完全通过"段落
