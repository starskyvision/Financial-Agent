# CLAUDE.md — 金融多智能体协作系统

## 项目概述

基于 LangGraph 1.2+ 的金融投研多智能体协作系统，服务于券商自营及资管团队。系统通过**意图分类 + 条件路由**驱动四个专职 Agent（数据收集、财务分析、舆情解读、校验总结）协作，提供**双通道交互**：

- **快速通道** `/chat` — 对话式 Copilot，SSE 流式返回，简单查询秒级响应
- **异步通道** `/tasks` — 深度投研报告生成，含事实核对与反思循环

核心解决传统投顾系统两大痛点：**信息过载**（意图路由按需调用 Agent，简单问题不走全链路）与**逻辑推理弱**（校验 Agent + 反思循环确保数据引用准确）。

> 完整设计规格见 [docs/superpowers/specs/2026-06-16-financial-agent-mvp-design.md](docs/superpowers/specs/2026-06-16-financial-agent-mvp-design.md)

## 技术栈

- **后端**: FastAPI 0.115+ (Python 3.11+)
- **Agent 框架**: LangGraph 1.2+ / LangChain 1.3+（StateGraph 状态机 + 条件边路由）
- **大模型**: DeepSeek-V3（主力，云端 API）/ Qwen（备选降级），后续按需下沉本地
- **数据源**: AKShare（MVP 默认），Adapter 抽象层预留 Wind / Tushare 接口
- **向量库**: Milvus 2.4 / pymilvus 2.4.x
- **队列/缓存**: Celery 5.6 + Redis 5.0~5.2.1（**禁止升 Redis 8.x，Celery 不兼容**）
- **数据库**: MySQL 8.0
- **容器化**: Docker Compose

## 项目结构

```
├── backend/
│   ├── agents/                # 专职 Agent 节点
│   │   ├── intent_classifier/ # 意图分类（入口节点，区分快/慢通道）
│   │   ├── data_collector/    # 数据收集 Agent（数据源抽象层）
│   │   ├── financial_analyzer/# 财务分析 Agent（杜邦分解、异动检测）
│   │   ├── sentiment_analyzer/# 舆情解读 Agent（情感分析）
│   │   └── reviewer/          # 校验总结 Agent（事实核对、报告生成）
│   ├── services/              # 公共服务
│   │   ├── data_sources/      # 数据源 Adapter 抽象层
│   │   ├── task_queue/        # Celery + Redis 异步任务队列
│   │   └── retrieval/         # Milvus 向量检索
│   ├── prompts/               # LLM 提示词模板
│   ├── db/                    # 数据库初始化 SQL
│   ├── main.py                # FastAPI 入口（/chat + /tasks 双路由）
│   └── requirements.txt       # 带兼容性约束的版本锁定
├── frontend/                  # Vue3 前端
│   └── src/
│       ├── views/             # 页面组件（Chat / Report / Dashboard）
│       └── api/               # API 调用层
├── docs/                      # 项目文档
│   └── superpowers/
│       └── specs/             # 设计规格
├── docker-compose.yml
├── CLAUDE.md                  # 本文件
└── readme.md
```

## 架构要点

### Agent 编排（意图路由 + 双通道）

```
用户输入 → 意图分类 → ┌─ simple_query       → 数据收集 → 直接输出
                      ├─ financial_analysis → 数据收集 → 财务分析 → 输出
                      ├─ sentiment_analysis → 数据收集 → 舆情解读 → 输出
                      └─ comprehensive      → 全管道 → 校验 → 反思循环 → 报告
```

### 条件边规则（3 个路由点）

1. **入口路由**：所有意图先进入数据收集
2. **数据收集后**：根据 `intent` 分发到输出/财务/舆情/全管道
3. **财务分析后**：快速通道直接输出，comprehensive 继续走舆情→校验

### 反思循环（仅 comprehensive）

- `retry_count < 3 AND errors 非空` → 重写节点 → 回到校验总结
- `retry_count >= 3 OR errors 为空` → 输出节点
- 强制输出时标注"自动校验未完全通过"

## 开发约定

- **Python 3.11+**，类型注解使用完整
- **异步优先**：所有 I/O 操作使用 `async/await`
- **LangGraph StateGraph**：Agent 间通过 TypedDict State 传递数据，条件边控制路由
- **数据源 Adapter 模式**：所有数据采集通过 `DataSourceAdapter` 协议接口，新增数据源只需实现 3 个方法（`fetch_financials` / `fetch_news` / `fetch_documents`）
- **Function Calling Schema**：所有工具函数必须定义严格 JSON Schema + Few-shot 示例
- **错误处理**：Agent 节点异常不中断整个图，通过 State 中的 `errors` 字段传递
- **日志**：使用 `structlog`，关键节点记录 State 快照
- **版本约束**：修改依赖前必须检查 [requirements.txt](backend/requirements.txt) 中的兼容性注释

## 常用命令

```bash
# 启动基础设施
docker compose up -d

# 安装后端依赖
cd backend && pip install -r requirements.txt

# 启动后端（开发模式）
cd backend && uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 启动前端
cd frontend && npm install && npm run dev
```
