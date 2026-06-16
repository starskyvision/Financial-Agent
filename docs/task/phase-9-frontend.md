# Phase 9 — 前端联调

**优先级**: P2　|　**前置**: Phase 8　|　**预计工时**: 1.5 天

## 目标

将前端 Mock 方法替换为真实 API 调用，实现 Chat 对话页面、Report 报告渲染和 Dashboard 仪表盘。

## 子任务

### 9.1 Chat 页面 — SSE 对接

📁 `frontend/src/views/Chat.vue`
📁 `frontend/src/api/chat.ts`

- [ ] 封装 `postChat(message: string, conversationId?: string)` API 函数
- [ ] 使用 `EventSource` 或 `fetch` + `ReadableStream` 消费 SSE 流
- [ ] SSE 事件处理：
  ```
  intent  → 显示意图标签（如"正在进行财务分析..."）
  progress → 显示当前 Agent 名称 + 进度条
  chunk   → 流式追加 Markdown 文本到对话气泡
  done    → 显示来源引用 + 总耗时
  ```
- [ ] 支持 Markdown 实时渲染（`marked` + `highlight.js` 代码高亮）
- [ ] 对话历史：内存维护 `messages[]` 数组（无需后端持久化）
- [ ] 输入框支持 Shift+Enter 换行，Enter 发送

**验收**: 输入"分析茅台Q3 ROE" → 流式显示分析结果，格式正确

### 9.2 Report 页面 — 结构渲染

📁 `frontend/src/views/Report.vue`
📁 `frontend/src/api/reports.ts`

- [ ] 封装 `getReport(taskId: string)` API 函数
- [ ] 报告内容按 7 段结构渲染（标题、摘要、财务、异动、舆情、风险、免责）
- [ ] 表格渲染：杜邦分解结果以 HTML Table 展示
- [ ] 引用角标：`[^{{id}}]` 格式渲染为上标角标
- [ ] 报告未就绪时轮询状态（间隔 3s），就绪后停止轮询
- [ ] 支持从 Chat 页面跳转到 Report（携带 `task_id` 参数）

**验收**: 传入已完成 task_id → 渲染完整报告，表格和引用正确

### 9.3 Dashboard 页面 — 可观测性

📁 `frontend/src/views/Dashboard.vue`
📁 `frontend/src/api/dashboard.ts`

- [ ] 封装 `getHealth()` API 函数
- [ ] 组件：
  - **服务状态卡片**：Milvus / Redis / MySQL 连接状态（绿色/红色指示灯）
  - **任务队列统计**：pending / running / done / failed 数量（调用 `/tasks` 分页接口）
  - **Agent 调用热力图**：各 Agent 的成功率、平均耗时（SSE 事件聚合）
- [ ] 自动刷新：每 10s 轮询一次健康状态

**验收**: Dashboard 显示四个服务的实时状态，任务计数正确

---

## 产出物

- [ ] `frontend/src/api/chat.ts` — Chat API 封装
- [ ] `frontend/src/api/reports.ts` — Report API 封装
- [ ] `frontend/src/api/dashboard.ts` — Dashboard API 封装
- [ ] `frontend/src/views/Chat.vue` — 对话页面
- [ ] `frontend/src/views/Report.vue` — 报告页面
- [ ] `frontend/src/views/Dashboard.vue` — 仪表盘

*关联文档: [设计规格 API §6](../superpowers/specs/2026-06-16-financial-agent-mvp-design.md#六api-设计), [README 任务 6](../../readme.md#-任务-6前端仪表盘与-api-联调-frontendsrc)*
