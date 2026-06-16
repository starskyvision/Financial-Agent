# CLAUDE.md — 金融多智能体协作系统

## 项目概述

这是一个基于 LangGraph 的金融投研多智能体协作系统，服务于券商自营及资管团队。系统通过四个专职 Agent（数据收集、财务分析、舆情解读、校验总结）协作完成投研报告生成。

## 技术栈

- **后端**: FastAPI (Python 3.11+)
- **Agent 框架**: LangGraph（StateGraph 状态机）
- **大模型**: Qwen2.5-14B（本地）、DeepSeek-V3（校验）
- **向量库**: Milvus 2.4
- **缓存/队列**: Redis 7
- **数据库**: MySQL 8.0
- **容器化**: Docker Compose

## 项目结构

```
├── backend/
│   ├── agents/              # 四个专职 Agent
│   │   ├── data_collector/  # 数据收集 Agent（Wind API、PDF 解析）
│   │   ├── financial_analyzer/ # 财务分析 Agent（杜邦分解、异动检测）
│   │   ├── sentiment_analyzer/ # 舆情解读 Agent（情感分析）
│   │   └── reviewer/        # 校验总结 Agent（事实核对、报告生成）
│   ├── services/            # 公共服务
│   │   ├── task_queue/      # Redis 异步任务队列
│   │   └── retrieval/       # Milvus 向量检索
│   ├── prompts/             # LLM 提示词模板
│   ├── db/                  # 数据库初始化 SQL
│   ├── main.py              # FastAPI 入口
│   └── requirements.txt
├── frontend/                # Vue3 前端
│   └── src/
│       ├── views/           # 页面组件
│       └── api/             # API 调用层
├── docs/                    # 项目文档
├── docker-compose.yml
└── CLAUDE.md                # 本文件
```

## 开发约定

- **Python 3.11+**，类型注解使用完整
- **异步优先**：所有 I/O 操作使用 `async/await`
- **LangGraph StateGraph**：Agent 间通过 TypedDict State 传递数据
- **Function Calling Schema**：所有工具函数必须定义严格 JSON Schema + Few-shot 示例
- **错误处理**：Agent 节点异常不中断整个图，通过 State 中的 `errors` 字段传递
- **日志**：使用 `structlog`，关键节点记录 State 快照

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
