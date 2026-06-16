# 金融多智能体协作系统 — 任务分解

> 基于 [2026-06-16 设计规格](../superpowers/specs/2026-06-16-financial-agent-mvp-design.md)
> 总预计工时：10 个阶段，共 48 个子任务

---

## 依赖关系图

```
Phase 0  基础设施确认 ─────────────────────────────────────┐
                                                          │
Phase 1  数据源抽象层 ────┐                                │
                          ▼                                │
Phase 2  意图分类器 ──┐  Phase 3  数据收集 Agent           │
                     │        │        │                  │
                     │        ▼        ▼                  │
                     │  Phase 4  财务分析  Phase 5  舆情解读
                     │        │        │                  │
                     │        ▼        ▼                  │
                     │  Phase 6  校验总结 Agent             │
                     │        │                           │
                     │        ▼                           │
                     ├──→ Phase 8  FastAPI + LangGraph ◄──┤
                     │        │                           │
                     │        ▼                    Phase 7 任务队列
                     └──→ Phase 9  前端联调               │
                                                          │
                          Phase 10 测试 · 文档 · 交付 ◄────┘
```

## 阶段总览

| 阶段 | 名称 | 子任务数 | 优先级 | 前置依赖 |
|------|------|---------|--------|---------|
| [Phase 0](phase-0-infra.md) | 基础设施确认 | 4 | P0 | — |
| [Phase 1](phase-1-data-source.md) | 数据源抽象层 | 5 | P0 | Phase 0 |
| [Phase 2](phase-2-intent-classifier.md) | 意图分类器 Agent | 4 | P0 | Phase 0 |
| [Phase 3](phase-3-data-collector.md) | 数据收集 Agent | 5 | P0 | Phase 1 |
| [Phase 4](phase-4-financial-analyzer.md) | 财务分析 Agent | 5 | P1 | Phase 3 |
| [Phase 5](phase-5-sentiment-analyzer.md) | 舆情解读 Agent | 5 | P1 | Phase 3 |
| [Phase 6](phase-6-reviewer.md) | 校验总结 Agent | 6 | P1 | Phase 4, 5 |
| [Phase 7](phase-7-task-queue.md) | 异步任务队列 | 4 | P1 | Phase 0 |
| [Phase 8](phase-8-api-graph.md) | FastAPI + LangGraph 编排 | 5 | P0 | Phase 2, 3, 4, 5, 6, 7 |
| [Phase 9](phase-9-frontend.md) | 前端联调 | 3 | P2 | Phase 8 |
| [Phase 10](phase-10-test-deliver.md) | 测试 · 文档 · 交付 | 2 | P2 | Phase 9 |

## 角色分配建议

| 角色 | 负责阶段 | 技能要求 |
|------|---------|---------|
| 后端工程师 A | Phase 1, 3, 7 | Python 异步编程、API 对接、Redis/Celery |
| 后端工程师 B | Phase 4, 5, 6 | 金融会计基础、LangGraph、Prompt 工程 |
| 后端工程师 C | Phase 2, 8 | LangGraph 条件边、FastAPI SSE、StateGraph 编排 |
| 前端工程师 | Phase 9 | Vue3、SSE EventSource、Markdown 渲染 |
| 全员 | Phase 0, 10 | Docker、文档、测试 |

---

*文档版本: v1.0 | 生成日期: 2026-06-16*
