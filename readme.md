# 🏦 金融多智能体协作系统

> **一句话介绍**：这是一个"AI 投研助手"——你问它一个金融问题（比如"分析一下茅台的盈利能力"），它会自动调用多个 AI 智能体协作完成分析，然后给你一份专业的研究报告。

---

## 📖 阅读指南

本文档用最通俗的语言，带你从零开始了解并运行这个项目。无论你是：
- 🎓 **学生**：想学习 AI Agent 开发、LangGraph 框架
- 💼 **金融从业者**：想搭建自己的智能投研工具
- 👨‍💻 **开发者**：想了解多智能体系统的工程实践

都能在这里找到你需要的信息。**预计阅读时间：15 分钟**。

---

## 🤔 这个项目解决了什么问题？

传统券商/资管研究员每天的工作是这样的：

| 痛点 | 现实情况 | 本项目的解决方案 |
|------|---------|----------------|
| 📰 **信息过载** | 研究员每天要看上百份研报、公告、新闻 | **意图路由**——你问简单问题就简单回答（秒级），问复杂问题才启动全流程分析 |
| 🧠 **逻辑推理弱** | 传统工具只会罗列数据，不会像人一样关联分析 | **校验 Agent + 反思循环**——AI 会自己检查报告里的数据有没有算错，最多自查 3 轮 |

**举个例子**：你对系统说"茅台 ROE 为什么下降了？"

传统工具只会给你一堆数字。而这个系统会：
1. 先理解你的意图（哦，你要做财务分析）
2. 去拉茅台的最新财报数据
3. 用杜邦分析法把 ROE 拆成三层，找到底是净利率还是周转率出了问题
4. 同时去搜茅台的新闻，看有没有负面舆情
5. 最后把所有发现写成一份有条理的报告，**并自己核对一遍数据有没有引用错误**

---

## 🏗️ 系统是怎么工作的？（白话版）

### 整体架构：就像一条流水线

想象一个工厂流水线，原材料（你的问题）从一头进去，成品（分析报告）从另一头出来：

```
你的问题
    ↓
┌─────────────────┐
│  🧭 意图分类器    │  ← "你想干嘛？" 把问题分成 4 类
└────────┬────────┘
         ↓
┌─────────────────┐
│  📡 数据收集员    │  ← "我去找数据" 从 AKShare 等数据源拉取
└────────┬────────┘
         ↓
    ┌────┴────┐
    ↓         ↓         ↓
┌────────┐ ┌────────┐ ┌──────────┐
│💰财务   │ │📰舆情   │ │📝综合     │  ← 根据意图选择性执行
│ 分析师  │ │ 分析师  │ │ 全流程    │
└───┬────┘ └───┬────┘ └────┬─────┘
    ↓         ↓         ↓
┌─────────────────────────────┐
│  ✅ 校验员 + 反思循环         │  ← "数据对不对？" 最多自查 3 遍
└─────────────┬───────────────┘
              ↓
         📊 最终报告
```

### 四个智能体各干什么？

| 智能体 | 就像... | 具体工作 |
|--------|---------|---------|
| 🧭 **意图分类器** | 医院的分诊台 | 判断你的问题是闲聊、查数据、财务分析还是舆情分析 |
| 📡 **数据收集员** | 图书馆管理员 | 去 AKShare（免费金融数据源）帮你找财报、新闻、公告 |
| 💰 **财务分析师** | 会计师 | 用杜邦分析法拆解 ROE，检测财务指标有没有异常波动 |
| 📰 **舆情分析师** | 公关顾问 | 读新闻标题和摘要，判断市场情绪是乐观还是悲观 |
| ✅ **校验员** | 校对编辑 | 逐项核对报告里的数字和原始数据是否一致，偏差超 1% 就打回重写 |

### 双通道设计：快问快答 vs 深度报告

| | 🚀 快速通道 `/chat` | 📝 深度通道 `/tasks` |
|---|---|---|
| **适合场景** | "茅台 PE 多少？" | "给我出一份茅台的综合投研报告" |
| **响应时间** | 几秒钟（流式输出） | 几分钟（后台异步执行） |
| **执行链路** | 按需调用 1-2 个 Agent | 全流程：数据→财务→舆情→校验→反思 |
| **返回方式** | SSE 流式打字效果 | 轮询任务状态，完成后取报告 |

---

## 🛠️ 技术栈（用人话解释）

| 技术 | 干什么用的 | 为什么选它 |
|------|-----------|-----------|
| **Python 3.11+** | 后端编程语言 | AI/数据领域最主流的语言，库最全 |
| **FastAPI** | Web 框架（接收请求） | 快、自带 API 文档、支持异步 |
| **LangGraph 1.2+** | AI Agent 编排框架 | 像画流程图一样编排多个 AI，支持条件分支和循环 |
| **LangChain 1.3+** | LLM 应用开发框架 | 封装了各种 LLM 调用、工具定义 |
| **DeepSeek-V3** | 大语言模型（AI 大脑） | 国产模型，性价比高，金融领域表现好 |
| **PostgreSQL 16 + pgvector** | 数据库 + 向量搜索 | 一个数据库同时存业务数据和 AI 向量，不用多维护一套 |
| **Redis 7** | 缓存 + 消息队列 | 存临时数据、协调后台任务 |
| **Celery 5.6** | 异步任务队列 | 深度报告太慢了不能让人等着，扔后台慢慢跑 |
| **AKShare** | 免费金融数据源 | 开源免费，覆盖 A 股/港股/期货等 |
| **BGE-M3** | 文本向量化模型 | 把文字转成数学向量，实现语义搜索（RAG） |
| **Vue 3 + Vite** | 前端框架 | 轻量、好学，适合中小型项目 |
| **Docker Compose** | 一键部署 | 不用手动装数据库、Redis，一条命令全搞定 |

---

## 🚀 从零开始：5 步跑起来

### 准备工作（你电脑上需要有的）

| 软件 | 版本要求 | 怎么检查有没有装好 |
|------|---------|------------------|
| **Docker Desktop** | 24.0+ | 打开终端输入 `docker --version` |
| **Git** | 任意版本 | 终端输入 `git --version` |
| **Python**（可选，本地开发才需要） | 3.11+ | 终端输入 `python --version` |
| **Node.js**（可选，本地前端才需要） | 18+ | 终端输入 `node --version` |

> 💡 **如果你是 Windows 用户**：推荐使用 Git Bash 作为终端。安装 Docker Desktop 后记得重启电脑。
>
> 💡 **如果你是 Mac 用户**：Docker Desktop 安装后，在"设置 → Resources"里建议给 Docker 分配至少 4GB 内存。

---

### 第一步：下载代码

打开终端，找个你喜欢的位置：

```bash
# 克隆项目到本地
git clone git@github.com:starskyvision/Financial-Agent.git

# 进入项目目录
cd Financial-Agent
```

---

### 第二步：配置 API 密钥（最重要！）

这个项目需要调用 DeepSeek 的 AI 模型，所以你需要一个 API Key：

1. 去 [DeepSeek 开放平台](https://platform.deepseek.com/) 注册账号
2. 在"API Keys"页面创建一个新的 Key，复制下来
3. 在项目里创建配置文件：

```bash
# 用示例文件创建你自己的配置
cp backend/.env.example backend/.env
```

4. 用任意文本编辑器（记事本、VS Code 等）打开 `backend/.env` 文件
5. 修改下面这行，把 `your_deepseek_api_key_here` 替换成你刚才复制的 Key：

```properties
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

6. 其他配置保持默认即可，保存文件。

> ⚠️ **重要提示**：
> - DeepSeek API 是按使用量收费的，但价格很便宜（约 1 元/百万 token）
> - 这个 Key 不要上传到 GitHub！`.env` 文件已经在 `.gitignore` 里了
> - 如果你想更安全，可以把 `API_KEY` 也改成自己的密码，防止别人乱调你的接口

---

### 第三步：启动所有服务

在项目根目录（`Financial-Agent/`）下执行：

```bash
# 启动所有服务（第一次会比较慢，要下载镜像）
docker compose up -d --build
```

这个命令会启动 6 个服务：

| 服务名称 | 功能 | 内部端口 |
|---------|------|---------|
| **postgres** | PostgreSQL 16 数据库 + pgvector 向量扩展 | 15432 |
| **redis** | Redis 缓存和任务队列 | 16379 |
| **api** | FastAPI 后端服务 | 8000 |
| **worker** | Celery 后台任务工人 | - |
| **beat** | Celery 定时任务调度器 | - |
| **frontend** | Vue 前端页面（Nginx 托管） | 80 |

等它跑完，检查一下是否都正常：

```bash
# 健康检查
curl http://localhost:8000/api/v1/health
```

如果看到类似这样的返回就成功了：

```json
{
  "status": "healthy",
  "postgres": "connected",
  "redis": "connected",
  "pgvector": "connected",
  "version": "1.0.0"
}
```

---

### 第四步：初始化数据库

```bash
# 创建数据库表结构
docker compose exec api alembic upgrade head
```

> 📚 **这步做了什么？** 它会创建所有需要的数据库表，包括财务数据表、文档表、向量索引等。就像在 Excel 里新建了一个工作簿并设置好表头。

---

### 第五步：访问系统

现在打开浏览器：

| 地址 | 看到什么 |
|------|---------|
| [http://localhost](http://localhost) | 🎨 **前端界面**——可以直接聊天提问 |
| [http://localhost:8000/docs](http://localhost:8000/docs) | 📋 **API 文档**——Swagger 自动生成的接口文档，可以直接在网页上测试 API |
| [http://localhost:8000](http://localhost:8000) | 🏠 **首页**——快捷链接汇总 |

> 🎉 **恭喜！系统已经跑起来了！** 在前端输入框里试试问：`分析贵州茅台的财务状况` 或者 `最近关于腾讯的新闻怎么说`

---

## 💻 开发者模式（修改代码时用）

如果你要改代码，用 Docker 每次 rebuild 太慢了。这时可以本地启动：

```bash
# 1. 只启动基础设施（数据库 + Redis）
docker compose up -d postgres redis

# 2. 安装 Python 依赖
cd backend
pip install -r requirements.txt

# 3. 启动后端（修改代码会自动重启）
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 4. 另开一个终端，启动前端
cd frontend
npm install
npm run dev
```

- 后端代码改了 → FastAPI 自动重启（`--reload`）
- 前端代码改了 → Vite 热更新（浏览器自动刷新）

---

## 📡 API 接口速查

### 1. 快速对话（Chat）

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key" \
  -d '{"message": "分析贵州茅台的盈利能力"}'
```

返回 SSE 流式数据，像打字机一样逐行输出。

### 2. 提交深度分析任务（Tasks）

```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key" \
  -d '{"company_code": "600519", "report_date": "2026-03-31"}'
```

返回 `{"task_id": "abc123", "status": "pending"}`

### 3. 查询任务进度

```bash
curl http://localhost:8000/api/v1/tasks/abc123
```

### 4. 获取完成的报告

```bash
curl http://localhost:8000/api/v1/reports/abc123
```

### 5. 健康检查

```bash
curl http://localhost:8000/api/v1/health
```

---

## 📂 项目结构详解

```
Financial-Agent/
│
├── backend/                          # 📦 后端代码（Python）
│   ├── agents/                       # 🤖 各个 AI 智能体
│   │   ├── intent_classifier/        #    🧭 意图分类器——理解用户想问什么
│   │   │   └── classifier.py         #       分类逻辑 + Prompt
│   │   ├── data_collector/           #    📡 数据收集员——从数据源拉数据
│   │   │   └── node.py               #       LangGraph 节点实现
│   │   ├── financial_analyzer/       #    💰 财务分析师——杜邦分解 + 异动检测
│   │   │   ├── node.py               #       LangGraph 节点实现
│   │   │   └── dupont.py             #       杜邦分析计算引擎
│   │   ├── sentiment_analyzer/       #    📰 舆情分析师——情感判断
│   │   │   └── node.py               #       LangGraph 节点实现
│   │   ├── reviewer/                 #    ✅ 校验员——事实核对 + 报告生成
│   │   │   ├── router.py             #       反思循环路由控制
│   │   │   └── report_generator.py   #       结构化报告生成
│   │   └── output_node.py            #    📤 输出节点——汇总各 Agent 结果
│   │
│   ├── services/                     # 🔧 公共服务（被多个 Agent 共用）
│   │   ├── data_sources/             #    数据源适配层
│   │   │   └── adapter.py            #      统一接口（AKShare/Tushare/Wind）
│   │   ├── task_queue/               #    异步任务队列
│   │   │   ├── celery_app.py         #      Celery 配置
│   │   │   └── manager.py            #      任务提交/查询管理
│   │   ├── rag/                      #    向量检索（RAG）
│   │   │   ├── __init__.py           #      pgvector 检索 + BGE-M3 嵌入
│   │   │   └── search.py             #      语义搜索实现
│   │   ├── circuit_breaker.py        #    熔断器——防止下游服务挂了拖死整个系统
│   │   ├── query_preprocessor.py     #    查询预处理——用 RAG 改写模糊问题
│   │   └── llm_service.py            #    LLM 调用服务
│   │
│   ├── prompts/                      # 📝 提示词模板
│   │   ├── intent_classifier.py      #    意图分类的 System Prompt
│   │   ├── financial_analysis.py     #    财务分析的 Few-shot 示例
│   │   ├── sentiment_analysis.py     #    舆情分析的指令
│   │   └── report_generation.py      #    报告生成的结构要求
│   │
│   ├── middleware/                    # 🛡️ 中间件
│   │   ├── auth.py                   #    API Key 认证
│   │   └── rate_limit.py             #    频率限制（防滥用）
│   │
│   ├── state.py                      # 📋 全局状态定义（Agent 间传递的数据结构）
│   ├── graph_routes.py               # 🔀 条件路由（决定下一步走哪个 Agent）
│   ├── main.py                       # 🚪 FastAPI 入口（所有 HTTP 接口）
│   ├── requirements.txt              # 📦 Python 依赖清单
│   ├── Dockerfile                    # 🐳 后端 Docker 镜像
│   └── .env.example                  # ⚙️ 环境配置模板
│
├── frontend/                         # 🎨 前端代码（Vue 3 + TypeScript）
│   ├── src/
│   │   ├── views/
│   │   │   └── Chat.vue              #    聊天页面（主要交互界面）
│   │   ├── api/
│   │   │   └── chat.ts               #    API 调用封装
│   │   └── router/
│   │       └── index.ts              #    页面路由
│   ├── package.json                  #    前端依赖
│   └── Dockerfile                    #    🐳 前端 Docker 镜像（Nginx）
│
├── docs/                             # 📚 文档
│   ├── architecture.md               #    系统架构设计
│   ├── agent-workflow.md             #    Agent 工作流详解
│   ├── api.md                        #    API 接口文档
│   ├── data-contracts.md             #    数据契约定义
│   ├── deploy.md                     #    生产部署指南
│   └── process-management.md         #    进程管理说明
│
├── docker-compose.yml                # 🐳 一键启动所有服务
├── CLAUDE.md                         # 🤖 AI 协作指引（给 AI 助手看的项目说明）
└── readme.md                         # 📖 你现在看的这个文件
```

---

## 🔄 Agent 工作流详解

### 意图分类——系统的"大脑门"

用户的任何问题，首先经过意图分类器，被分为 5 种类型：

| 意图 | 例子 | 会走哪些 Agent |
|------|------|--------------|
| 💬 **chitchat**（闲聊） | "你好"、"今天天气怎么样" | AI 直接回复，不调用任何 Agent |
| 📊 **simple_query**（简单查询） | "茅台 PE 多少" | 数据收集 → 直接输出 |
| 💰 **financial_analysis**（财务分析） | "分析茅台的盈利能力" | 数据收集 → 财务分析 → 输出 |
| 📰 **sentiment_analysis**（舆情分析） | "最近茅台有什么新闻" | 数据收集 → 舆情分析 → 输出 |
| 📝 **comprehensive**（综合研报） | "出一份茅台的完整投研报告" | 全流程：数据→财务→舆情→校验→反思→报告 |

### 条件路由——智能的"交通指挥"

系统有 3 个路由决策点，根据当前状态决定下一步去哪里：

```
入口路由（graph_routes.py）
    ↓
1️⃣ 数据收集后：
   - simple_query → 直接输出
   - financial_analysis → 去财务分析
   - sentiment_analysis → 去舆情分析
   - comprehensive → 去财务分析（然后再去舆情）
    ↓
2️⃣ 财务分析后：
   - financial_analysis → 输出（快速通道到此结束）
   - comprehensive → 继续去舆情分析
    ↓
3️⃣ 舆情分析后：
   - sentiment_analysis → 输出（快速通道到此结束）
   - comprehensive → 进入报告生成 + 反思循环
```

### 反思循环——AI 的"自我检查"

这是 comprehensive 模式特有的机制。校验 Agent 生成报告后，会逐项核对：

```
报告生成 → 事实核对 → 发现错误？
                         ├─ 没有错误 → ✅ 输出最终报告
                         └─ 有错误 + 重试次数 < 3 → 🔄 重写报告 → 再核对
                             └─ 重试次数 ≥ 3 → ⚠️ 强制输出（标注"自动校验未完全通过"）
```

---

## 🔧 常用命令速查

```bash
# ========== Docker 相关 ==========
docker compose up -d              # 启动所有服务
docker compose down               # 停止所有服务
docker compose ps                 # 查看各服务状态
docker compose logs api           # 查看后端日志
docker compose logs worker        # 查看 Celery Worker 日志
docker compose restart api        # 重启后端服务

# ========== 数据库相关 ==========
docker compose exec postgres psql -U financial_agent -d financial_agent
# 进入数据库命令行（\dt 查看所有表，\q 退出）

# ========== 后端开发 ==========
cd backend
pip install -r requirements.txt   # 安装依赖
uvicorn main:app --reload         # 启动开发服务器
pytest                            # 运行测试（如果有）

# ========== 前端开发 ==========
cd frontend
npm install                       # 安装依赖
npm run dev                       # 启动开发服务器（默认 http://localhost:5173）
npm run build                     # 生产构建
```

---

## 🐛 常见问题排查

### Q1: `docker compose up -d --build` 报错怎么办？

**A:** 最常见的原因是端口被占用：

```bash
# Windows 查看端口占用
netstat -ano | findstr :8000
netstat -ano | findstr :15432
netstat -ano | findstr :16379

# 如果端口被占用，修改 docker-compose.yml 中的端口映射
# 比如把 "8000:8000" 改成 "8001:8000"
```

### Q2: 前端页面打不开？

**A:** 检查几个点：
1. Docker 里 frontend 服务是否在运行：`docker compose ps frontend`
2. 如果本地启动了 Vite 前端，容器里的会被覆盖，用 `http://localhost:5173` 访问
3. 看看浏览器控制台有没有红色报错（F12 → Console）

### Q3: API 返回 401 或 403 错误？

**A:** 这是认证问题。两种解决办法：
- 请求时带上 `X-API-Key` 头（值是你 `.env` 里设的 `API_KEY`）
- 开发模式下，在 `.env` 里把 `API_KEY` 设为空（`API_KEY=`）

### Q4: DeepSeek API 调用失败？

**A:** 检查：
1. API Key 是否正确复制（`echo $DEEPSEEK_API_KEY`）
2. 账户里有没有余额（去 DeepSeek 开放平台→账户管理查看）
3. 网络能不能访问 `https://api.deepseek.com`（`curl -I https://api.deepseek.com`）

### Q5: 数据库连接失败（health check 里 postgres 显示 disconnected）？

**A:**
```bash
# 重启 postgres 容器
docker compose restart postgres

# 等 10 秒让它初始化完成
sleep 10

# 再试
curl http://localhost:8000/api/v1/health
```

### Q6: 想完全从头开始（删掉所有数据）？

**A:**
```bash
docker compose down -v   # -v 会删除数据卷（数据库、Redis 数据全清空）
docker compose up -d --build  # 重新构建启动
docker compose exec api alembic upgrade head  # 重新建表
```

### Q7: 本地开发时 Python 依赖装不上？

**A:** 注意版本约束：
- `redis` 必须是 `5.0.0 ~ 5.2.1`（Celery 5.6 不兼容 Redis 6.x/8.x）
- Python 版本必须是 3.11 或更高
- Windows 用户如果 `pgvector` 装不上，可以用 Docker 跑后端（`docker compose up api`）

### Q8: 之前跑过旧版本，升级后出问题？

**A:**
```bash
git pull                          # 拉最新代码
docker compose down               # 停掉
docker compose build --no-cache   # 无缓存重构建
docker compose up -d              # 启动
docker compose exec api alembic upgrade head  # 数据库迁移
```

---

## 🎯 功能特性一览

### ✅ 已实现

- [x] **意图路由**：5 种意图自动分类（闲聊/简单查询/财务/舆情/综合），按需调度 Agent
- [x] **多 Agent 协作**：4 个专职 Agent + 条件边动态路由，不浪费算力
- [x] **杜邦分解**：ROE 三级拆解（净利率 × 资产周转率 × 权益乘数）
- [x] **异动检测**：同比变化超 30% 黄色预警，超 50% 红色预警
- [x] **舆情分析**：新闻情感三分类（积极/中性/消极）+ 0~1 强度打分
- [x] **反思校验**：报告数据与源表比对，偏差 >1% 触发重写，最多 3 轮
- [x] **异步任务**：深度报告扔后台执行，可查询进度，不阻塞其他请求
- [x] **SSE 流式输出**：对话模式下像打字机一样逐字输出，体验流畅
- [x] **可插拔数据源**：Adapter 抽象层，默认 AKShare，预留 Tushare/Wind 接口
- [x] **熔断降级**：下游服务异常时自动熔断，防止雪崩
- [x] **RAG 增强检索**：基于 BGE-M3 + pgvector 的语义搜索，提升数据覆盖
- [x] **查询预处理**：模糊问题通过向量检索自动补全股票代码/公司名称
- [x] **频率限制**：每 IP 每分钟最多 60 次请求（可配置）
- [x] **API Key 认证**：可选的身份认证，保护接口不被滥用
- [x] **容器化部署**：Docker Compose 一键启动全部 6 个服务
- [x] **健康检查**：`/api/v1/health` 返回数据库、Redis、pgvector、Celery 的连接状态

### 🚧 规划中

- [ ] 前端 Dashboard 页面（任务队列监控、Agent 调用链路可视化）
- [ ] 前端 Report 页面（结构化投研报告渲染，含表格和引用标注）
- [ ] Tushare / Wind 数据源适配器实现
- [ ] 用户历史记录持久化
- [ ] 多用户会话管理
- [ ] 单元测试 + 集成测试全覆盖
- [ ] 监控告警（Prometheus + Grafana）
- [ ] Qwen 模型作为备选降级方案

---

## 📚 更多文档

| 文档 | 内容 |
|------|------|
| [系统架构设计](docs/architecture.md) | 架构图、核心组件说明 |
| [Agent 工作流](docs/agent-workflow.md) | Agent 状态流转、路由规则详解 |
| [API 接口文档](docs/api.md) | 所有接口的请求/响应格式 |
| [数据契约](docs/data-contracts.md) | 数据库表结构、字段定义 |
| [部署指南](docs/deploy.md) | 生产环境部署的完整流程 |
| [设计规格](docs/superpowers/specs/2026-06-16-financial-agent-mvp-design.md) | MVP 版本完整设计文档 |
| [AI 协作指引](CLAUDE.md) | 给 AI 助手看的项目上下文 |

---

## 🤝 贡献指南

如果你想参与开发，请遵循以下约定：

- **Python 3.11+**，类型注解尽量完整
- **异步优先**：所有 I/O 操作使用 `async/await`
- **LangGraph StateGraph**：Agent 间通过 `TypedDict` State 传递数据
- **数据源 Adapter 模式**：新增数据源只需实现 3 个方法
- **Function Calling Schema**：工具函数必须定义严格 JSON Schema
- **错误处理**：Agent 节点异常不中断整个图，通过 `errors` 字段传递
- **版本约束**：修改依赖前检查 `requirements.txt` 中的兼容性注释（特别是 `redis<=5.2.1`）

---

## 📄 开源协议

MIT License

---

> 💡 **最后的话**：这个项目的目标是让金融研究变得更高效。如果你有任何问题或建议，欢迎提 Issue。如果你觉得项目对你有帮助，请给一个 ⭐ Star！
