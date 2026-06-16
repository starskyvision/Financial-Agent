# 金融多智能体协作系统

**投研辅助智能 Copilot**：基于 LangGraph 多 Agent 协作，支持结构化财报分析、舆情解读与自动报告生成，具备自我反思校验机制，有效降低金融数据推理中的事实幻觉。

## 能力

- 多 Agent 协作推理（数据收集 → 财务分析 → 舆情解读 → 校验总结）
- 结构化财报分析（杜邦分解、现金流异动检测）
- 舆情情感判断（新闻与论坛情绪解读）
- 自我反思与事实核对（校验 Agent 动态路由重写）
- 异步长任务处理（规划-执行-观察解耦，支持中断与进度查询）
- 工具调用防幻觉（Few-shot + 格式校验层，防止生成不存在的指标代码）

## 技术栈

FastAPI · LangGraph · Milvus · Redis · Qwen2.5-14B · DeepSeek-V3 · Wind 金融终端 API · Docker

## 快速开始

```
# 1. 复制环境配置文件
cp backend/.env.example backend/.env      # 填模型 API Key 与数据库连接信息

# 2. 启动基础设施与后端 API
# 方式 A：直接构建并启动所有容器
docker compose up -d --build

# 方式 B：如遇网络中断，可以分步拉取依赖镜像，然后再启动
docker compose pull
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

- 架构：[docs/architecture.md](docs/architecture.md)
- 数据契约（schema 真相源）：[docs/data-contracts.md](docs/data-contracts.md)
- Agent 状态流转：[docs/agent-workflow.md](docs/agent-workflow.md)
- API：[docs/api.md](docs/api.md) ｜ 部署：[docs/deploy.md](docs/deploy.md)
- 给 AI 协作的指引：[CLAUDE.md](CLAUDE.md)

## 项目结构

```
├── backend/
│   ├── agents/                 # 四个专职 Agent
│   │   ├── data_collector/     # 数据收集 Agent（Wind API、PDF 解析）
│   │   ├── financial_analyzer/ # 财务分析 Agent（杜邦分解、异动检测）
│   │   ├── sentiment_analyzer/ # 舆情解读 Agent（情感分析）
│   │   └── reviewer/           # 校验总结 Agent（事实核对、报告生成）
│   ├── services/               # 公共服务
│   │   ├── task_queue/         # Redis 异步任务队列
│   │   └── retrieval/          # Milvus 向量检索
│   ├── prompts/                # LLM 提示词模板
│   ├── db/                     # 数据库初始化 SQL
│   │   └── init.sql
│   ├── main.py                 # FastAPI 入口
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── src/
│       ├── views/              # 页面组件（Chat / Report / Dashboard）
│       └── api/                # API 调用层
├── docs/                       # 项目文档
│   ├── architecture.md
│   ├── data-contracts.md
│   ├── agent-workflow.md
│   ├── api.md
│   └── deploy.md
├── docker-compose.yml
├── CLAUDE.md
└── readme.md
```

---

## 🛠️ 项目成员开发任务指南 (2日周期 TodoList)

当前**项目基础设施编排**、**LangGraph 状态图骨架**以及**数据库初始化 SQL** 均已全部开发完成，并经语法和配置验证通过。

项目成员需完成以下任务，完成核心业务逻辑对接：

### 🏁 基础设施准备 (全员/运维)

- 复制 `backend/.env.example` 为 `backend/.env`，填写实际的 `LLM_API_KEY`、`QWEN_API_BASE`、`DEEPSEEK_API_KEY` 和 `MILVUS_URI`。
- 启动本地 Docker 编排：`docker compose up -d --build`，确认 Milvus、Redis 全部容器正常运行。
- 在 `backend/` 目录下执行 `pip install -r requirements.txt` 安装依赖。

### 📁 任务 1：数据收集 Agent (`backend/agents/data_collector`)

- **Wind API 对接**：在 `data_collector` 逻辑中，封装 Wind 金融终端 API 客户端，支持结构化抓取财报、公告原文及行情数据。
- **PDF 解析器**：编写 PDF 解析模块，提取研报中的表格、财务指标和正文段落，写入 MySQL `documents` 表。
- **数据归一化入库**：将采集的原始数据按 `company_code`、`report_date` 维度归一化写入 MySQL `financial_data` 表。

### 📁 任务 2：财务分析 Agent (`backend/agents/financial_analyzer`)

- **杜邦分解计算**：编写财务指标计算引擎，支持 ROE 杜邦分解（净利率 × 资产周转率 × 权益乘数）。
- **现金流异动检测**：实现同比/环比现金流变动检测逻辑，标记异常波动并生成预警信号。
- **Function Calling Schema**：为每个计算函数定义严格的 JSON Schema，包含 Few-shot 示例和输出格式校验层，防止模型生成不存在的指标代码。

### 📁 任务 3：舆情解读 Agent (`backend/agents/sentiment_analyzer`)

- **新闻情绪分析**：调用 LLM 配合 `prompts/sentiment_analysis.md` 提示词，对新闻文本进行情感三分类（积极/中性/消极）及强度打分。
- **论坛舆情聚合**：抓取主流财经论坛讨论，按话题聚合后生成舆情摘要。
- **情绪时间序列**：将分析结果写入 Redis 时序缓存，供前端展示情绪走势图。

### 📁 任务 4：校验与总结 Agent (`backend/agents/reviewer`)

- **事实核对**：在初步结论生成后，触发校验节点比对关键数据与 MySQL 源表。若发现矛盾，通过 LangGraph 条件边动态路由至重写节点。
- **报告草稿生成**：使用 `prompts/report_generation.md` 提示词，整合各 Agent 输出，生成结构化的投研报告（含数据表格与引用标注）。
- **自反思循环**：实现最多 3 轮的"生成 → 校验 → 重写"反思循环，确保关键数据引用错误率控制在 5% 以内。

### 📁 任务 5：异步任务与状态管理 (`backend/services/task_queue`)

- **Redis 任务队列**：基于 Redis 实现异步任务队列，将 Agent 的"规划-执行-观察"循环解耦为独立任务。
- **进度查询与中断**：提供任务状态查询接口（pending/running/done/failed），支持用户随时中断或重试任务。
- **SSE 流式推送**：通过 FastAPI EventSourceResponse 流式推送报告生成进度与中间结果。

### 📁 任务 6：前端仪表盘与 API 联调 (`frontend/src`)

- **接口联调**：将各页面的 Mock 方法替换为真实的 Axios 请求（任务提交、进度轮询、报告查看）。
- **报告渲染**：在 `Report.vue` 中渲染结构化投研报告，支持表格、图表和引用角标展示。
- **可观测仪表盘**：在 `Dashboard.vue` 中展示任务队列状态、Agent 调用链路和系统健康指标。
