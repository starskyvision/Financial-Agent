# 金融多智能体协作系统

**投研辅助智能 Copilot**：基于 LangGraph 1.2+ 多 Agent 协作，采用**意图路由 + 双通道**架构，解决传统投顾系统两大痛点——

- **信息过载**：研究员日均需阅读上百份研报/公告 → 意图分类按需调度 Agent，简单查询秒级响应，避免全链路空转
- **逻辑推理弱**：无法动态关联宏观数据、财报指标与市场情绪 → 校验 Agent + 白盒反思循环，确保关键数据引用准确

## 交互模式

| 通道 | 接口 | 场景 | 响应 |
|------|------|------|------|
| 快速对话 | `POST /chat` | "茅台PE多少""分析XX盈利能力" | SSE 流式，秒级 |
| 深度报告 | `POST /tasks` | 综合投研分析，含杜邦分解+舆情+反思 | 异步，分钟级 |

## 能力

- **意图路由** — 理解用户问题后选择性调度 Agent，简单查询不跑全链路
- **多 Agent 协作** — 数据收集 → 财务分析 → 舆情解读 → 校验总结，条件边按需跳转
- **结构化财报分析** — 杜邦分解（ROE 三级拆解）、现金流同比异动检测
- **舆情情感判断** — 新闻情感三分类（积极/中性/消极）+ 强度打分
- **自我反思校验** — 报告关键数据与源表逐项比对，偏差 >1% 触发重写（最多 3 轮）
- **异步长任务** — Celery + Redis 解耦，支持中断与进度查询
- **可插拔数据源** — Adapter 抽象层，默认 AKShare，预留 Wind / Tushare 接口
- **工具调用防幻觉** — Few-shot + JSON Schema 校验层，防止生成不存在的指标代码

## 技术栈

FastAPI 0.115+ · LangGraph 1.2+ · LangChain 1.3+ · Milvus 2.4 · Celery 5.6 · Redis · MySQL 8.0 · DeepSeek-V3 · AKShare · Docker

## 快速开始

```bash
# 1. 复制环境配置文件
cp backend/.env.example backend/.env      # 填入 DEEPSEEK_API_KEY 与数据库连接信息

# 2. 启动基础设施与后端 API
docker compose up -d --build

# 3. 安装后端依赖（本地调试）
cd backend && pip install -r requirements.txt

# 4. 启动 FastAPI 服务
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- 后端 API：http://localhost:8000/docs
- Milvus 管理台：http://localhost:9091
- Redis Insight：http://localhost:8001

## 文档

- 设计规格：[docs/superpowers/specs/2026-06-16-financial-agent-mvp-design.md](docs/superpowers/specs/2026-06-16-financial-agent-mvp-design.md)
- 系统架构：[docs/architecture.md](docs/architecture.md)
- 数据契约：[docs/data-contracts.md](docs/data-contracts.md)
- Agent 状态流转：[docs/agent-workflow.md](docs/agent-workflow.md)
- API：[docs/api.md](docs/api.md) ｜ 部署：[docs/deploy.md](docs/deploy.md)
- AI 协作指引：[CLAUDE.md](CLAUDE.md)

## 项目结构

```
├── backend/
│   ├── agents/                  # 专职 Agent
│   │   ├── intent_classifier/   # 意图分类 — 入口节点，区分快/慢通道
│   │   ├── data_collector/      # 数据收集 — 数据源 Adapter 抽象层
│   │   ├── financial_analyzer/  # 财务分析 — 杜邦分解、异动检测
│   │   ├── sentiment_analyzer/  # 舆情解读 — 情感分析
│   │   └── reviewer/            # 校验总结 — 事实核对、反思循环、报告生成
│   ├── services/
│   │   ├── data_sources/        # 数据源抽象层（AKShare / Tushare / Wind 预留）
│   │   ├── task_queue/          # Celery + Redis 异步任务队列
│   │   └── retrieval/           # Milvus 向量检索
│   ├── prompts/                 # LLM 提示词模板
│   ├── db/                      # 数据库初始化 SQL
│   ├── main.py                  # FastAPI 入口（/chat + /tasks 双路由）
│   ├── requirements.txt         # 带兼容性约束的版本锁定
│   └── .env.example
├── frontend/
│   └── src/
│       ├── views/               # Chat / Report / Dashboard
│       └── api/                 # API 调用层
├── docs/
│   └── superpowers/specs/       # 设计规格
├── docker-compose.yml
├── CLAUDE.md
└── readme.md
```

---

## 🛠️ 项目成员开发任务指南

当前**基础设施编排**、**LangGraph 状态图骨架**及**数据库初始化 SQL** 已就绪。项目成员需完成以下核心业务逻辑：

### 🏁 基础设施准备

- 复制 `backend/.env.example` 为 `backend/.env`，填写 `DEEPSEEK_API_KEY`、`QWEN_API_BASE`（备选）和 `MILVUS_URI`
- 启动 Docker 编排：`docker compose up -d --build`，确认 Milvus、Redis、MySQL 全部正常运行
- 在 `backend/` 下执行 `pip install -r requirements.txt`（注意 redis<=5.2.1 约束）

### 📁 任务 1：数据源抽象层 + 数据收集 Agent (`backend/agents/data_collector/` + `backend/services/data_sources/`)

- **Adapter 接口**：实现 `DataSourceAdapter` 协议（`fetch_financials` / `fetch_news` / `fetch_documents`），所有数据源实现此接口
- **AKShare 适配器**：对接 AKShare 免费数据源，支持 A 股财务指标、公告标题拉取
- **PDF 解析器**：PyMuPDF + pdfplumber 提取研报表格和正文，写入 MySQL `documents` 表
- **数据归一化入库**：按 `company_code` + `report_date` 维度写入 `financial_data` 表

### 📁 任务 2：意图分类器 (`backend/agents/intent_classifier/`)

- **结构化路由**：Prompt + LLM 输出四种意图（simple_query / financial_analysis / sentiment_analysis / comprehensive）
- **实体提取**：自动抽取 `company_code`、`report_date`、关注指标
- **条件边集成**：与 LangGraph 条件边对接，驱动后续 Agent 选择调度

### 📁 任务 3：财务分析 Agent (`backend/agents/financial_analyzer/`)

- **杜邦分解**：ROE = 净利率 × 资产周转率 × 权益乘数，逐级拆解到三级因子
- **异动检测**：同比变化超 30% 自动标记预警
- **Function Calling Schema**：每个计算函数严格 JSON Schema + Few-shot，防幻觉

### 📁 任务 4：舆情解读 Agent (`backend/agents/sentiment_analyzer/`)

- **新闻情感分析**：LLM 批量处理新闻标题+摘要，情感三分类 + 强度打分
- **情绪时间序列**：写入 Redis `sentiment:{code}:{date}`，供前端展示走势

### 📁 任务 5：校验总结 Agent (`backend/agents/reviewer/`)

- **事实核对**：报告关键数据与 MySQL `financial_data` 源表逐项比对，偏差 >1% 触发重写
- **反思循环**：最多 3 轮"生成 → 校验 → 重写"，通过条件边动态路由
- **报告生成**：整合各 Agent 输出，生成结构化 Markdown 报告（含数据表格+引用标注）

### 📁 任务 6：异步任务队列 (`backend/services/task_queue/`)

- **Celery + Redis**：将 comprehensive 意图的 Agent 全链路解耦为异步任务
- **进度查询**：`GET /api/v1/tasks/{task_id}` 返回 pending/running/done/failed
- **SSE 流式推送**：`GET /api/v1/tasks/{task_id}/stream` 推送 Agent 进度与中间结果

### 📁 任务 7：前端接口联调 (`frontend/src/`)

- **Chat 页面**：对接 `POST /chat` SSE 流式接口，支持 Markdown 实时渲染
- **Report 页面**：渲染结构化投研报告，含表格、图表和引用角标
- **Dashboard**：任务队列状态、Agent 调用链路和系统健康指标
