# Phase 10 — 测试 · 文档 · 交付

**优先级**: P2　|　**前置**: Phase 9　|　**预计工时**: 1 天

## 目标

完成全系统集成验证，更新项目文档，修复发现的问题，交付可运行的 MVP。

## 子任务

### 10.1 全链路验收测试

- [ ] **Test Case 1 — 简单查询**：
  ```
  /chat → "茅台最新营收是多少"
  预期: SSE intent=simple_query, chunk 包含营收数值, done 在 3s 内
  ```

- [ ] **Test Case 2 — 财务分析**：
  ```
  /chat → "分析一下600519在2024Q3的盈利能力"
  预期: SSE 包含杜邦分解结果 (ROE/净利率/周转率/权益乘数), done 在 10s 内
  ```

- [ ] **Test Case 3 — 舆情查询**：
  ```
  /chat → "贵州茅台最近有什么新闻"
  预期: SSE 包含 sentiment_label + key_topics, done 在 8s 内
  ```

- [ ] **Test Case 4 — 异步综合报告**：
  ```
  POST /tasks → company_code=600519
  轮询 GET /tasks/{id} → status: pending → running → done
  GET /reports/{id} → 7 段完整报告
  全程 < 5 分钟
  ```

- [ ] **Test Case 5 — 反思循环**：
  ```
  预埋错误数据 → 提交 comprehensive 任务
  预期: 报告中数据被修正（errors 从 >0 变为 0），retry_count ≤ 3
  ```

- [ ] **Test Case 6 — 降级行为**：
  ```
  模拟数据源不可用 → 提交请求
  预期: 返回友好提示而非 5xx 错误，报告标注"数据暂不可用"
  ```

**验收**: 6 个 Test Case 全部通过

### 10.2 文档更新

- [ ] 更新 [README.md](../../readme.md) 中与实际代码不一致的部分
- [ ] 补充 [docs/architecture.md](../architecture.md) — 架构图改为双通道版本
- [ ] 补充 [docs/agent-workflow.md](../agent-workflow.md) — 增加意图路由流程图
- [ ] 补充 [docs/api.md](../api.md) — 新增 `/chat` 接口文档
- [ ] 补充 [docs/deploy.md](../deploy.md) — 增加 Celery worker 启动命令
- [ ] 在 [CLAUDE.md](../../CLAUDE.md) 中标注 MVP 实际完成状态

**验收**: `grep -r "TODO" docs/ backend/` 无遗留 TODO（除预留扩展点外）

---

## 交付检查清单

- [ ] `docker compose up -d --build` 一键启动全栈
- [ ] `pytest` 全量测试通过（覆盖率≥70%）
- [ ] 6 个端到端 Test Case 全部通过
- [ ] 文档与代码一致
- [ ] `git tag v0.1.0-mvp` 打标签
- [ ] README 中"快速开始"可执行

---

*关联文档: [README 开发任务指南](../../readme.md), [设计规格](../superpowers/specs/2026-06-16-financial-agent-mvp-design.md)*
