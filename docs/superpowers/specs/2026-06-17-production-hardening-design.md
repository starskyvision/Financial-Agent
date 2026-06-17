# 金融多智能体系统 — 生产化上线设计

**日期**: 2026-06-17
**状态**: 已确认
**目标**: 将 MVP 从"开发可运行"提升到"生产可上线"，目标环境为内部工具（50-500 人内网），1-2 月周期。

---

## 一、总体目标与范围

### 一期范围（本次）

| 维度 | 内容 |
|------|------|
| **基础设施** | MySQL + Milvus + etcd + MinIO（5 容器）→ PostgreSQL + pgvector（1 容器） |
| **安全** | API Key 认证 + IP 白名单 + 密钥不入库 |
| **可靠性** | 请求限流 + 外部 API 熔断 + Alembic 迁移 + Redis AOF 持久化 |
| **可观测性** | 结构化日志 + Docker 日志轮转 + 增强健康检查 |
| **CI/CD** | GitHub Actions 自动测试 → 构建 → 部署 → 回滚 |
| **前端** | 生产构建 + Nginx 静态托管 + 认证头 |
| **RAG** | 研报检索增强生成：BGE-M3 embedding + pgvector 检索 + LLM 上下文注入 |

### 不做的事

- K8s、多租户、SSO、微服务拆分
- Prometheus/Alertmanager（预留接口，不强制启用）
- 全链路压测（给出压测方案，上线前执行）

---

## 二、目标架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Nginx (反向代理 + 前端静态)                     │
│  /api/* → api:8000        / → 前端静态        /health → 健康检查   │
└────────────┬────────────────────────────┬─────────────────────────┘
             ▼                            ▼
┌────────────────────────┐   ┌─────────────────────────┐
│   FastAPI (uvicorn)    │   │   前端 (Vite 构建)       │
│   /chat /tasks /reports│   │   Nginx 容器托管 dist/    │
│   /rag/search          │   │   Chat / Report / Admin  │
└───────┬────────────────┘   └─────────────────────────┘
        │
┌───────▼─────────────────────────────────────────────────────────┐
│                     LangGraph StateGraph                         │
│  意图分类 → 数据收集 → 财务分析 → 舆情解读 → [RAG检索] → 报告生成  │
│                                                     │            │
│                                               反思循环 (≤3轮)     │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                       公共服务层                                  │
│  ┌──────────────┐ ┌──────────────┐ ┌───────────────────────────┐ │
│  │ LLM 服务      │ │ 数据源适配器  │ │ RAG 服务                   │ │
│  │ DeepSeek/Qwen │ │ AKShare      │ │ embedder / chunker        │ │
│  │ + 熔断器      │ │ + 超时重试    │ │ retriever / ingester      │ │
│  └──────────────┘ └──────────────┘ └──────────┬────────────────┘ │
│                                                │                  │
│  ┌──────────────┐ ┌────────────────────────────▼────────────────┐ │
│  │ Redis         │ │ PostgreSQL + pgvector                       │ │
│  │ 任务队列+缓存  │ │ financial_data / documents (含向量) / tasks │ │
│  │ AOF 持久化    │ │                                             │ │
│  └──────────────┘ └─────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

**关键变化**：
- 5 容器 → 2 容器（PostgreSQL + Redis），移除 MySQL、Milvus、etcd、MinIO
- 新增 `services/rag/` 模块（6 文件）
- 新增安全中间件（认证 + 限流）、熔断器、Alembic 迁移
- 新增 Nginx 反向代理 + 前端静态容器

---

## 三、基础设施变更

### 3.1 数据库迁移：MySQL → PostgreSQL + pgvector

**容器变化**：

```yaml
# docker-compose.yml
移除:
  mysql:    image: mysql:8.0
  milvus:   image: milvusdb/milvus:v2.5.0
  etcd:     image: quay.io/coreos/etcd:v3.5.5
  minio:    image: minio/minio:latest

新增:
  postgres:
    image: pgvector/pgvector:pg16
    ports: ["5432:5432"]
    environment:
      POSTGRES_USER: financial_agent
      POSTGRES_PASSWORD: ${PG_PASSWORD}
      POSTGRES_DB: financial_agent
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./backend/db/init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U financial_agent"]
      interval: 10s
      timeout: 5s
      retries: 5
```

**SQL 方言对照**：

| MySQL | PostgreSQL |
|-------|-----------|
| `BIGINT AUTO_INCREMENT` | `BIGSERIAL` |
| `ENUM('pending','running','done','failed')` | `VARCHAR(16) CHECK (status IN ('pending','running','done','failed'))` |
| `DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` | `TIMESTAMPTZ DEFAULT now()` + 更新触发器 |
| `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4` | 不需要（PG 天然 UTF-8） |
| `COMMENT '描述'` | `COMMENT ON COLUMN table.column IS '描述'` |
| — | `CREATE EXTENSION IF NOT EXISTS vector;` |
| — | `embedding vector(1024)` |
| — | `CREATE INDEX ON docs USING hnsw (embedding vector_cosine_ops);` |

**代码变更**：

| 文件 | 改动 |
|------|------|
| `db/init.sql` | ~60 行重写（DDL 方言转换 + pgvector 扩展 + 注释） |
| `db/models.py` | 恢复 Document 模型，FinancialData 调整为 PG 兼容，+10 行 |
| `main.py` 健康检查 | `pymysql.connect()` → `psycopg2.connect()`，~10 行 |
| `docker-compose.yml` | 替换数据库编排，~20 行 |
| `.env.example` | `MYSQL_*` 5 个环境变量 → `DATABASE_URL` 1 个 |
| `requirements.txt` | `aiomysql`/`pymysql` → `asyncpg`/`psycopg2-binary`；新增 `pgvector` |

### 3.2 容器编排全貌

最终 `docker-compose.yml` 包含 6 个服务：

```yaml
services:
  nginx:      # 反向代理 + 前端静态文件
  api:        # FastAPI (uvicorn) — 后端 API
  worker:     # Celery worker — 异步任务执行
  beat:       # Celery beat — 定时任务调度（RAG 文档拉取）
  postgres:   # PostgreSQL 16 + pgvector — 财务数据 + 文档向量
  redis:      # Redis 7 — 任务队列 + 缓存（AOF 持久化）
```

可选（取消注释启用）：

```yaml
  # grafana:    # Grafana — 仪表盘
  # loki:       # Loki — 日志聚合
```

### 3.3 Redis 持久化

```yaml
redis:
  image: redis:7-alpine
  command: redis-server --appendonly yes --save 900 1 300 10 60 10000
  volumes:
    - redis_data:/data
```

AOF 日志 + RDB 快照双重保障。

### 3.4 数据库迁移（Alembic）

```bash
pip install alembic
cd backend && alembic init migrations
```

初始迁移包含 `financial_data` / `documents` / `tasks` 三张表（PG 语法）。后续变更流程：

```bash
# 修改 models.py → 自动生成迁移
alembic revision --autogenerate -m "add xyz column"
# 审查生成的迁移脚本 → 应用
alembic upgrade head
```

---

## 四、RAG 模块设计

### 4.1 文件结构

```
backend/services/rag/
├── __init__.py        # 对外暴露 search() / index_document() / index_batch() / delete()
├── config.py          # CHUNK_SIZE=500, OVERLAP=50, TOP_K=5, EMBEDDING_DIM=1024
├── embedder.py        # BGE-M3 本地模型封装（sentence-transformers）
├── chunker.py         # 按段落边界切块 + 滑动窗口重叠
├── retriever.py       # pgvector 查询：cosine 相似度 + company_code/doc_type 过滤
├── ingester.py        # 编排管道：获取 → 切块 → 向量化 → 入库
└── tasks.py           # Celery 定时任务：每日凌晨拉取最新研报
```

### 4.2 Embedding 模型

- 模型：BGE-M3（BAAI/bge-m3），1024 维
- 加载方式：本地路径加载（模型文件通过宿主机卷挂载，不打进镜像）
- 推理：CPU 模式，~50 篇/分钟
- 首次启动模型已在本地，无需下载

```python
# embedder.py
from sentence_transformers import SentenceTransformer
import os

MODEL_PATH = os.getenv("BGE_M3_PATH", "/models/bge-m3")

class Embedder:
    def __init__(self):
        self.model = SentenceTransformer(MODEL_PATH)
        self.dim = 1024

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()
```

### 4.3 数据流

**定时拉取路径**：

```
Celery Beat (每日 02:00)
  │
  ▼
AKShare stock_research_report_em() → 最近 7 天研报摘要
  │
  ▼
ingester.index_batch(documents)
  ├─► chunker: 500 字/块，50 字重叠，段落边界对齐
  ├─► embedder: BGE-M3 → 1024 维向量
  └─► retriever: INSERT INTO documents (..., embedding) VALUES (..., $1)
```

**实时检索路径**：

```
report_generator_node 报告生成前
  │
  ▼
query = f"{company_name} 财务分析 风险 展望"
  │
  ▼
search(query, company_code=code, top_k=5)
  ├─► embedder.embed(query)
  └─► SELECT content, doc_title, 1 - (embedding <=> $1) AS score
      FROM documents WHERE company_code = $2
      ORDER BY embedding <=> $1 LIMIT 5
  │
  ▼
build_report_prompt(state, rag_context=formatted_results)
  │
  ▼
LLM 生成报告（prompt 中包含参考研报上下文）
```

### 4.4 核心接口

```python
async def search(query: str, company_code: str = "", doc_type: str = "",
                 top_k: int = 5) -> list[dict]:
    """语义检索。返回 [{"content": "...", "doc_title": "...", "score": 0.92}]"""

async def index_document(content: str, company_code: str, doc_type: str,
                         doc_title: str = "", content_zh: str = "") -> list[int]:
    """单篇文档入库。切片 → 向量化 → 写入。返回 chunk id 列表。"""

async def index_batch(documents: list[dict]) -> int:
    """批量入库。返回入库 chunk 总数。"""

async def delete_by_company(company_code: str) -> int:
    """删除某公司所有文档切片，用于数据刷新。"""
```

### 4.5 LLM 集成

修改 `prompts/report_generation.py` 的 `build_report_prompt`，新增 `rag_context` 参数：

```python
def build_report_prompt(state, retry_context="", rag_context=""):
    # ... 现有 prompt 构建逻辑 ...

    if rag_context:
        prompt += f"""
### 参考研报（来自知识库）
{rag_context}

基于以上参考信息与分析数据生成投研报告。引用参考研报信息时，
在正文中以 [来源: xxx研报] 标注。
"""
    return prompt
```

`report_generator_node` 中调用检索：

```python
from services.rag import search

results = await search(
    query=f"{company_name} 财务分析 风险 行业展望",
    company_code=company_code,
    top_k=5,
)
if results:
    rag_context = "\n\n".join(
        f"**[{r['doc_title']}]** (相关度: {r['score']:.0%})\n{r['content'][:300]}"
        for r in results
    )
prompt = build_report_prompt(state, retry_context, rag_context=rag_context)
```

### 4.6 文档源

- 主要来源：`ak.stock_research_report_em()` — 东方财富免费研报摘要
- 扩展预留：用户 PDF 上传接口（`POST /api/v1/documents/upload`），后续按需实现

### 4.7 pgvector 性能边界

- 10 万向量以内：HNSW 索引 + cosine 查询，延迟 <10ms
- 10 万-100 万：HNSW 依然有效，需调大 `maintenance_work_mem`
- 100 万+：考虑回迁 Milvus（内部工具 5 年内达不到）

---

## 五、安全与可靠性

### 5.1 API 认证

新增 `middleware/auth.py`：静态 API Key + 可选 IP 白名单。

```python
API_KEY = os.getenv("API_KEY", "")
IP_WHITELIST = [ip.strip() for ip in os.getenv("IP_WHITELIST", "").split(",") if ip.strip()]

async def auth_middleware(request: Request, call_next):
    client_ip = request.client.host
    if IP_WHITELIST and client_ip not in IP_WHITELIST:
        return JSONResponse(status_code=403, content={"error": "ip not allowed"})
    if request.url.path in ("/api/v1/health", "/"):
        return await call_next(request)
    key = request.headers.get("X-API-Key", "")
    if API_KEY and key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid api key")
    return await call_next(request)
```

前端在请求拦截器中统一注入 `X-API-Key` 头。

### 5.2 密钥管理

- `.env` 加入 `.gitignore`，确保不入库
- 只提交 `.env.example` 模板（所有值为占位符）
- CI/CD 中生产密钥通过 GitHub Secrets 注入
- 敏感变量清单：`DEEPSEEK_API_KEY`、`PG_PASSWORD`、`API_KEY`

### 5.3 请求限流

新增 `middleware/rate_limit.py`：Redis 滑动窗口，按 API Key 分桶。

- 默认：每个 Key 每分钟 60 次请求
- 可通过 `RATE_LIMIT` 环境变量调整
- LLM 调用入口额外限制：每分钟 30 次（保护 API 配额）

### 5.4 外部 API 熔断

新增 `services/circuit_breaker.py`：标准三态熔断器。

```python
class CircuitBreaker:
    STATE_CLOSED = "closed"        # 正常
    STATE_OPEN = "open"            # 熔断中，拒绝请求
    STATE_HALF_OPEN = "half_open"  # 试探性放行一个请求

    def __init__(self, name: str, failure_threshold: int = 5,
                 recovery_timeout: int = 30):
        ...
```

应用范围：
- AKShare 适配器（每个 API 调用包一个 breaker）
- DeepSeek LLM 调用（`llm_service.py` 中启用）

熔断时降级行为：
- AKShare 熔断 → 返回空数据 + `errors` 追加 "数据源暂时不可用"
- LLM 熔断 → 返回预设的降级回复 + fallback 到 Qwen

### 5.5 数据库迁移

Alembic 管理所有 schema 变更，替代手写 SQL 文件：

```
backend/migrations/
├── env.py
├── versions/
│   └── 001_initial.py   # 初始迁移：financial_data + documents + tasks
```

CI 中增加 `alembic check` 确保迁移无遗漏。

---

## 六、可观测性

### 6.1 日志

```
FastAPI/Celery → structlog (JSON 格式) → stdout
                                            │
                          Docker json-file 驱动 → 宿主机轮转
                          max-size: 50m, max-file: 5
```

关键日志点：
- 每个 Agent 节点进入/退出（含 state 摘要）
- LLM 调用（延迟、token 消耗、模型）
- 熔断器状态变更
- Celery 任务生命周期
- 健康检查失败

### 6.2 健康检查

`GET /api/v1/health` 返回：

```json
{
  "status": "healthy",
  "postgres": "connected",
  "redis": "connected",
  "uptime_seconds": 86400,
  "version": "1.0.0"
}
```

Docker 健康检查：

```yaml
api:
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
    interval: 30s
    timeout: 5s
    retries: 3
```

### 6.3 Grafana + Loki（可选）

在 `docker-compose.yml` 中以注释形式提供配置。团队需要时可取消注释启用：
- Loki：采集 JSON 格式日志
- Grafana：预置健康仪表盘 + 日志搜索面板

### 6.4 告警（最小方案）

不上 Prometheus + Alertmanager。依赖现有机制：
- Celery 任务失败 → `task:{id}:events` 发布 `failed` 事件 → 前端红色标记
- 熔断器打开 → `logger.error("circuit_breaker_open")` → 后续可接 Webhook
- PostgreSQL 断连 → 健康检查 unhealthy → CI/CD 流程可配置通知

---

## 七、CI/CD 与部署

### 7.1 容器化产物

**后端** (`backend/Dockerfile`)：Python 3.11-slim，`uvicorn main:app`，BGE-M3 通过卷挂载。

**前端** (`frontend/Dockerfile`)：多阶段构建（Node build → Nginx 托管）。

### 7.2 CI/CD 流水线

GitHub Actions（`.github/workflows/deploy.yml`）：

```
合入 master
  │
  ▼
[1] 后端测试 (pytest --cov)
  │ 失败 → 阻断，通知 PR 作者
  ▼
[2] Lint 检查 (ruff check)
  │
  ▼
[3] 构建镜像 (docker compose build)
  │
  ▼
[4] 推送到服务器 (rsync compose 文件 + 源码)
  │
  ▼
[5] 重启服务 (ssh docker compose up -d --force-recreate)
  │
  ▼
[6] 健康检查 (curl /api/v1/health)
  │ 失败 → 自动回滚 (docker compose up -d 上一个镜像 tag)
  ▼
部署完成
```

### 7.3 环境区分

```
.env.development    # 本地：DEBUG=true,   RELOAD=true
.env.staging        # 预发：DEBUG=false,  测试数据库
.env.production     # 生产：DEBUG=false,  API_KEY=xxx
```

部署时通过 `DEPLOY_ENV` 选择对应文件。生产 `.env` 通过 GitHub Secrets 注入，不入库。

### 7.4 部署检查清单

每次上线前验证：

```
□ 所有测试通过（pytest --cov）
□ Alembic 迁移无冲突（alembic check）
□ 健康检查返回 healthy
□ tasks 队列无积压（Redis LLEN celery）
□ 磁盘 > 20%（df -h）
□ pg_dump 备份最近 24h 内成功
□ 回滚脚本可用（记录上一个镜像 tag）
```

---

## 八、前端生产化

### 8.1 改动点

| 文件 | 改动 | 行数 |
|------|------|------|
| `src/api/chat.ts` | 添加 `X-API-Key` 请求头 + `VITE_API_BASE` 环境变量 | ~5 |
| `src/api/reports.ts` | 同上 | ~5 |
| `src/api/dashboard.ts` | 同上 | ~5 |
| `vite.config.ts` | 新增 `build` 配置（outDir, sourcemap, manualChunks） | ~10 |
| `nginx.conf` | **新增** — 反向代理 + 静态文件托管 | ~20 |
| `Dockerfile` | **新增** — 多阶段构建 | ~15 |
| `.env.production` | **新增** — 生产环境变量模板 | ~3 |

### 8.2 Vite 构建配置

```typescript
build: {
  outDir: 'dist',
  assetsDir: 'assets',
  sourcemap: false,
  rollupOptions: {
    output: {
      manualChunks: {
        vendor: ['vue', 'vue-router'],
        marked: ['marked'],
      }
    }
  }
}
```

### 8.3 Nginx 关键配置

```nginx
# SSE 流式代理 — 必须关闭缓冲
location /api/ {
    proxy_pass http://api:8000;
    proxy_read_timeout 300s;
    proxy_buffering off;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}

# Vue SPA fallback
location / {
    try_files $uri $uri/ /index.html;
}
```

---

## 九、文件变更总清单

### 新增文件（17 个）

```
backend/
├── Dockerfile
├── middleware/
│   ├── __init__.py
│   ├── auth.py
│   └── rate_limit.py
├── services/
│   ├── circuit_breaker.py
│   └── rag/
│       ├── __init__.py
│       ├── config.py
│       ├── embedder.py
│       ├── chunker.py
│       ├── retriever.py
│       ├── ingester.py
│       └── tasks.py
└── migrations/              # alembic init 自动生成

frontend/
├── Dockerfile
├── nginx.conf
└── .env.production

根目录/
└── .github/workflows/deploy.yml
```

### 修改文件（11 个）

```
backend/db/init.sql                              # MySQL DDL → PostgreSQL + pgvector
backend/db/models.py                             # 恢复 Document 模型, PG 兼容调整
backend/main.py                                  # 健康检查 pymysql→psycopg2, 注册中间件
backend/docker-compose.yml                       # mysql+milvus+etcd+minio → postgres
backend/.env.example                             # MYSQL_* 5变量 → DATABASE_URL
backend/requirements.txt                         # 驱动更换, 新增 pgvector/sentence-transformers
backend/prompts/report_generation.py             # 新增 rag_context 参数
backend/agents/reviewer/report_generator.py      # 调用 search() 注入 RAG 上下文
frontend/vite.config.ts                          # build 配置
frontend/src/api/chat.ts                         # 认证头 + 环境变量
frontend/src/api/reports.ts                      # 同上
frontend/src/api/dashboard.ts                    # 同上
```

### 删除内容

```
容器: mysql, milvus, etcd, minio (docker-compose.yml)
依赖: aiomysql, pymysql (requirements.txt)
```

---

## 十、预估工作量

| 模块 | 人天 | 关键交付 |
|------|------|---------|
| PostgreSQL + pgvector 迁移 | 2 | init.sql 重写, models 恢复, 健康检查, compose 重排 |
| RAG 模块 | 8 | 6 个 Python 文件 + LLM prompt 集成 + Celery 定时任务 |
| 安全中间件 | 1 | auth.py + rate_limit.py + 前端注入 |
| 熔断器 | 0.5 | circuit_breaker.py + AKShare/LLM 接入 |
| Alembic 迁移 | 0.5 | 初始化 + 初始迁移脚本 |
| CI/CD | 1 | GitHub Actions deploy.yml |
| 容器化 | 1 | 后端 Dockerfile + compose 最终编排 |
| 前端生产化 | 1.5 | Dockerfile + nginx.conf + 构建配置 + API 层改造 |
| 日志 + 部署脚本 | 1 | structlog 调优 + 轮转配置 + 部署检查清单 |
| 集成测试 | 2 | RAG 端到端 + 健康检查 + SSE 流式 + Auth |
| **合计** | **18.5** | **≈ 4 周（1 人）或 2 周（2 人）** |

---

## 十一、风险与对策

| 风险 | 概率 | 影响 | 对策 |
|------|------|------|------|
| AKShare 接口不稳定 | 中 | 定时文档拉取失败 | 熔断器 + 重试 + 降级空数据告警 |
| BGE-M3 内存超预期 | 低 | 首次加载 OOM | 模型加载后打印内存占用，必要时设 `max_seq_length=256` |
| pgvector HNSW 索引构建慢 | 低 | 首次 1万+ 文档变慢 | 离线批量构建索引，上线前预热 |
| DeepSeek API 限频 | 中 | LLM 调用排队超时 | 限流器 + 熔断器 + Qwen 回退 |
| 数据库迁移失败 | 低 | CI 阻塞 | `alembic check` 在 CI 中先执行，失败不部署 |

---

## 十二、上线后第一周观察项

```
□ API 错误率 < 1%
□ LLM 调用延迟 P95 < 10s
□ RAG 检索延迟 < 500ms
□ Celery 任务失败率 < 5%
□ PostgreSQL 连接池无溢出
□ Redis 内存 < 70%
□ 磁盘使用增速 < 1%/天
□ 每日备份成功
```
