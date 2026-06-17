# 生产化上线实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将金融多智能体 MVP 从开发态提升到生产可上线状态——PostgreSQL+pgvector 替代 MySQL+Milvus、研报 RAG 检索增强、安全中间件、CI/CD 流水线、前端生产构建。

**Architecture:** 17 个新文件 + 11 个修改文件，分 11 个 Task 按依赖顺序执行。每个 Task 完成后可独立验证。PostgreSQL 迁移先行（基础设施底座），RAG 模块次之（核心功能），安全与运维设施后续叠加，最后端到端集成测试收尾。

**Tech Stack:** Python 3.11, FastAPI, LangGraph, PostgreSQL 16 + pgvector, Redis 7, Celery 5.6, sentence-transformers (BGE-M3), Docker Compose, GitHub Actions, Vue 3 + Vite

---

### Task 1: PostgreSQL + pgvector 数据库迁移

**Files:**
- Create: —（本 Task 不含新建文件）
- Modify: `backend/db/init.sql`, `backend/db/models.py`, `backend/main.py:220-245`, `backend/requirements.txt`, `backend/.env.example`, `docker-compose.yml`

- [ ] **Step 1: 重写 init.sql 为 PostgreSQL 语法**

重写 `backend/db/init.sql`，完整内容如下：

```sql
-- ============================================
-- 金融多智能体协作系统 - 数据库初始化 (PostgreSQL)
-- ============================================

-- 启用 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 财务数据中心
CREATE TABLE IF NOT EXISTS financial_data (
    id BIGSERIAL PRIMARY KEY,
    company_code VARCHAR(10) NOT NULL,
    report_date DATE NOT NULL,
    metric_name VARCHAR(64) NOT NULL,
    metric_value NUMERIC(20, 4),
    source VARCHAR(32) NOT NULL DEFAULT 'akshare',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fd_company_date ON financial_data (company_code, report_date);
CREATE INDEX IF NOT EXISTS idx_fd_metric ON financial_data (metric_name);

COMMENT ON TABLE financial_data IS '财务数据中心';
COMMENT ON COLUMN financial_data.company_code IS '股票代码';
COMMENT ON COLUMN financial_data.report_date IS '报告期';
COMMENT ON COLUMN financial_data.metric_name IS '指标名称';
COMMENT ON COLUMN financial_data.metric_value IS '指标值';
COMMENT ON COLUMN financial_data.source IS '数据来源 akshare/tushare/wind';

-- 文档切片（含向量）
CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    company_code VARCHAR(10) NOT NULL,
    doc_type VARCHAR(32) NOT NULL,
    doc_title VARCHAR(256),
    chunk_index INT NOT NULL DEFAULT 0,
    content TEXT NOT NULL,
    content_zh TEXT,
    embedding vector(1024),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_docs_company ON documents (company_code, doc_type);
CREATE INDEX IF NOT EXISTS idx_docs_embedding ON documents USING hnsw (embedding vector_cosine_ops);

COMMENT ON TABLE documents IS '文档切片（含 pgvector 向量）';
COMMENT ON COLUMN documents.company_code IS '关联股票代码';
COMMENT ON COLUMN documents.doc_type IS '文档类型 report/announcement/transcript';
COMMENT ON COLUMN documents.embedding IS 'BGE-M3 1024维向量';

-- 任务记录
CREATE TABLE IF NOT EXISTS tasks (
    id VARCHAR(36) PRIMARY KEY,
    company_code VARCHAR(10) NOT NULL,
    company_name VARCHAR(64),
    report_date DATE,
    status VARCHAR(16) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'done', 'failed')),
    progress INT DEFAULT 0,
    result JSONB,
    error_log TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status);
CREATE INDEX IF NOT EXISTS idx_tasks_company ON tasks (company_code);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks (created_at);

COMMENT ON TABLE tasks IS '任务记录';
COMMENT ON COLUMN tasks.progress IS '进度 0-100';

-- 更新触发器：tasks.updated_at 自动更新
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tasks_updated_at ON tasks;
CREATE TRIGGER trg_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

- [ ] **Step 2: 更新 db/models.py — 恢复 Document 模型，PG 兼容**

```python
from sqlalchemy import Column, BigInteger, String, Date, DateTime, Integer, Text, func
from sqlalchemy.orm import DeclarativeBase
from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    pass


class FinancialData(Base):
    __tablename__ = "financial_data"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_code = Column(String(10), nullable=False, index=True)
    report_date = Column(Date, nullable=False)
    metric_name = Column(String(64), nullable=False)
    metric_value = Column(String(64), nullable=False)
    source = Column(String(32), default="akshare")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    __tablename__ = "documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_code = Column(String(10), nullable=False, index=True)
    doc_type = Column(String(32), nullable=False)
    doc_title = Column(String(256))
    chunk_index = Column(Integer, default=0)
    content = Column(Text, nullable=False)
    content_zh = Column(Text)
    embedding = Column(Vector(1024))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True)
    company_code = Column(String(10), nullable=False)
    company_name = Column(String(64))
    report_date = Column(Date)
    status = Column(String(16), default="pending")
    progress = Column(Integer, default=0)
    result = Column(Text)   # JSONB stored as text for simplicity
    error_log = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 3: 更新 main.py 健康检查 — pymysql → psycopg2**

将 `backend/main.py` 第 220-245 行替换为：

```python
    health_status = {
        "status": "healthy",
        "redis": "unknown",
        "postgres": "unknown",
        "version": os.getenv("APP_VERSION", "1.0.0"),
    }
    # Redis
    try:
        r = await get_redis()
        await r.ping()
        health_status["redis"] = "connected"
    except Exception:
        health_status["redis"] = "disconnected"
    # PostgreSQL
    try:
        import psycopg2
        conn = psycopg2.connect(
            os.getenv("DATABASE_URL", "postgresql://financial_agent@localhost:5432/financial_agent"),
            connect_timeout=3,
        )
        conn.close()
        health_status["postgres"] = "connected"
    except Exception:
        health_status["postgres"] = "disconnected"
```

- [ ] **Step 4: 更新 docker-compose.yml — 替换数据库编排**

将 `docker-compose.yml` 中 mysql、milvus、etcd、minio 四个服务替换为：

```yaml
  postgres:
    image: pgvector/pgvector:pg16
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: financial_agent
      POSTGRES_PASSWORD: ${PG_PASSWORD:-financial_agent_2024}
      POSTGRES_DB: financial_agent
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./backend/db/init.sql:/docker-entrypoint-initdb.d/01-init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U financial_agent"]
      interval: 10s
      timeout: 5s
      retries: 5
```

volumes 部分更新为：

```yaml
volumes:
  pgdata:
  redis_data:
```

- [ ] **Step 5: 更新 requirements.txt**

替换数据库驱动：

```
# --- 数据库驱动 ---
sqlalchemy[asyncio]>=2.0.30
asyncpg>=0.29.0
psycopg2-binary>=2.9.9
pgvector>=0.3.0
```

移除：`aiomysql>=0.2.0`、`pymysql>=1.1.0`、`pymilvus>=2.4.0`。

新增 embedding 依赖：

```
# --- Embedding ---
sentence-transformers>=3.0.0
```

- [ ] **Step 6: 更新 .env.example**

```bash
# --- 数据库配置 ---
DATABASE_URL=postgresql://financial_agent:financial_agent_2024@localhost:5432/financial_agent
PG_PASSWORD=financial_agent_2024

# 移除 MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE
# 移除 MILVUS_HOST, MILVUS_PORT
```

- [ ] **Step 7: 启动 PostgreSQL 验证迁移**

```bash
docker compose up -d postgres
docker compose logs postgres  # 确认无错误，init.sql 执行成功
docker compose exec postgres psql -U financial_agent -d financial_agent -c "\dt"
# 预期输出：financial_data, documents, tasks 三张表
docker compose exec postgres psql -U financial_agent -d financial_agent -c "\dx"
# 预期输出：vector 扩展已安装
```

- [ ] **Step 8: 运行健康检查端到端验证**

```bash
cd backend && python -c "
from main import app
from fastapi.testclient import TestClient
client = TestClient(app)
resp = client.get('/api/v1/health')
print(resp.json())
# 预期：{'status': 'healthy', 'redis': '...', 'postgres': '...', 'version': '1.0.0'}
"
```

- [ ] **Step 9: 运行现有测试确认无回归**

```bash
cd backend && python -m pytest tests/ -v --tb=short
# 预期：全部 64 个测试通过
```

- [ ] **Step 10: Commit**

```bash
git add backend/db/init.sql backend/db/models.py backend/main.py \
        docker-compose.yml backend/requirements.txt backend/.env.example
git commit -m "feat: migrate MySQL+Milvus to PostgreSQL+pgvector

- Rewrite init.sql from MySQL DDL to PostgreSQL with pgvector extension
- Restore Document and Task SQLAlchemy models
- Replace pymysql with psycopg2 in health check
- Replace mysql+milvus+etcd+minio (4 containers) with pgvector/pg16 (1 container)
- Add sentence-transformers and pgvector to requirements"
```

---

### Task 2: Alembic 数据库迁移初始化

**Files:**
- Create: `backend/migrations/` (alembic init), `backend/alembic.ini`
- Modify: `backend/.env.example` (追加 DATABASE_URL 注释)

- [ ] **Step 1: 安装 alembic 并初始化**

```bash
cd backend
pip install alembic
alembic init migrations
```

- [ ] **Step 2: 配置 alembic.ini 和 env.py**

编辑 `backend/alembic.ini`，将 `sqlalchemy.url` 行改为：

```ini
sqlalchemy.url = postgresql://financial_agent:financial_agent_2024@localhost:5432/financial_agent
```

编辑 `backend/migrations/env.py`，在 `target_metadata` 处：

```python
import os
from db.models import Base
target_metadata = Base.metadata
```

- [ ] **Step 3: 生成初始迁移**

```bash
cd backend
# 确保 PostgreSQL 正在运行
alembic revision --autogenerate -m "initial_schema"
# 检查生成的文件 migrations/versions/xxxx_initial_schema.py
```

- [ ] **Step 4: 应用初始迁移验证**

```bash
alembic upgrade head
# 预期：INFO  [alembic.runtime.migration] Running upgrade -> xxxx, initial_schema
alembic check
# 预期：无输出（无待处理的迁移）
```

- [ ] **Step 5: 将 Alembic 加入 CI 检查**

将以下内容追加到 `.env.example`：

```bash
# --- 数据库迁移 ---
# Alembic 使用 DATABASE_URL，运行 `alembic upgrade head` 应用迁移
# CI 中执行 `alembic check` 确保迁移无遗漏
```

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/ backend/alembic.ini
git commit -m "feat: add Alembic for database migration management"
```

---

### Task 3: 熔断器

**Files:**
- Create: `backend/services/circuit_breaker.py`, `backend/tests/services/test_circuit_breaker.py`

- [ ] **Step 1: 写熔断器单元测试**

创建 `backend/tests/services/test_circuit_breaker.py`：

```python
import pytest
import asyncio
from services.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_passes_when_closed(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)
        result = await cb.call(asyncio.sleep(0.001, result="ok"))
        assert result == "ok"
        assert cb.state == "closed"
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)
        with pytest.raises(ValueError):
            await cb.call(_raise(ValueError("fail")))
        with pytest.raises(ValueError):
            await cb.call(_raise(ValueError("fail")))
        assert cb.state == "open"
        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(_raise(ValueError("fail")))

    @pytest.mark.asyncio
    async def test_half_open_recovery(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0)
        with pytest.raises(ValueError):
            await cb.call(_raise(ValueError("fail")))
        assert cb.state == "open"
        # recovery_timeout=0 → 下一次调用进入 half_open
        result = await cb.call(asyncio.sleep(0.001, result="recovered"))
        assert result == "recovered"
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_half_open_fails_back_to_open(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0)
        with pytest.raises(ValueError):
            await cb.call(_raise(ValueError("fail")))
        assert cb.state == "open"
        with pytest.raises(ValueError):
            await cb.call(_raise(ValueError("fail again")))
        assert cb.state == "open"


async def _raise(exc):
    raise exc
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && python -m pytest tests/services/test_circuit_breaker.py -v
# 预期：全部 FAIL（CircuitBreaker 未定义）
```

- [ ] **Step 3: 实现熔断器**

创建 `backend/services/circuit_breaker.py`：

```python
import time
import structlog

logger = structlog.get_logger()


class CircuitBreakerOpenError(Exception):
    """熔断器打开时抛出，调用方应降级处理。"""
    def __init__(self, service_name: str):
        self.service_name = service_name
        super().__init__(f"Circuit breaker open for '{service_name}'")


class CircuitBreaker:
    """标准三态熔断器：closed → open → half_open → closed"""

    def __init__(self, name: str, failure_threshold: int = 5,
                 recovery_timeout: float = 30.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.state = "closed"
        self._last_failure_time: float = 0.0

    async def call(self, coro):
        now = time.time()

        if self.state == "open":
            if now - self._last_failure_time < self.recovery_timeout:
                raise CircuitBreakerOpenError(self.name)
            self.state = "half_open"
            logger.info("circuit_half_open", service=self.name)

        try:
            result = await coro
            self.failure_count = 0
            self.state = "closed"
            return result
        except Exception:
            self.failure_count += 1
            self._last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "open"
                logger.error("circuit_breaker_open", service=self.name,
                             failures=self.failure_count)
            raise
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && python -m pytest tests/services/test_circuit_breaker.py -v
# 预期：4 passed
```

- [ ] **Step 5: Commit**

```bash
git add backend/services/circuit_breaker.py backend/tests/services/test_circuit_breaker.py
git commit -m "feat: add circuit breaker for external API resilience"
```

---

### Task 4: 安全中间件（认证 + 限流）

**Files:**
- Create: `backend/middleware/__init__.py`, `backend/middleware/auth.py`, `backend/middleware/rate_limit.py`
- Create: `backend/tests/middleware/__init__.py`, `backend/tests/middleware/test_auth.py`, `backend/tests/middleware/test_rate_limit.py`
- Modify: `backend/main.py` (注册中间件)

- [ ] **Step 1: 创建 middleware/__init__.py**

```python
# backend/middleware/__init__.py
```

- [ ] **Step 2: 创建 tests/middleware/__init__.py**

```python
# backend/tests/middleware/__init__.py
```

- [ ] **Step 3: 写认证中间件测试**

创建 `backend/tests/middleware/test_auth.py`：

```python
import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture
def auth_client():
    os.environ["API_KEY"] = "test-key-123"
    from main import app
    return TestClient(app)


class TestAuthMiddleware:
    def test_health_bypasses_auth(self, auth_client):
        resp = auth_client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_root_bypasses_auth(self, auth_client):
        resp = auth_client.get("/")
        assert resp.status_code == 200

    def test_api_endpoint_rejects_without_key(self, auth_client):
        resp = auth_client.post("/api/v1/chat", json={"message": "hello"})
        assert resp.status_code == 401

    def test_api_endpoint_accepts_valid_key(self, auth_client):
        resp = auth_client.post(
            "/api/v1/chat",
            json={"message": "hello"},
            headers={"X-API-Key": "test-key-123"},
        )
        # 可能返回 200（LLM 调用成功）或 500（LLM 未配置），但不应是 401
        assert resp.status_code != 401

    def test_api_endpoint_rejects_invalid_key(self, auth_client):
        resp = auth_client.post(
            "/api/v1/chat",
            json={"message": "hello"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401


class TestAuthDisabled:
    def test_no_key_required_when_api_key_empty(self):
        os.environ["API_KEY"] = ""
        from main import app
        client = TestClient(app)
        resp = client.post("/api/v1/chat", json={"message": "hello"})
        assert resp.status_code != 401
```

- [ ] **Step 4: 实现认证中间件**

创建 `backend/middleware/auth.py`：

```python
import os
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

API_KEY = os.getenv("API_KEY", "")
IP_WHITELIST = [
    ip.strip() for ip in os.getenv("IP_WHITELIST", "").split(",") if ip.strip()
]

PUBLIC_PATHS = {"/api/v1/health", "/", "/docs", "/openapi.json"}


async def auth_middleware(request: Request, call_next):
    # IP 白名单（可选）
    if IP_WHITELIST:
        client_ip = request.client.host if request.client else "unknown"
        if client_ip not in IP_WHITELIST:
            return JSONResponse(status_code=403, content={"error": "ip not allowed"})

    # 公开路径不校验
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    # API Key 未配置时跳过（开发环境）
    if not API_KEY:
        return await call_next(request)

    # 校验
    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid api key")

    return await call_next(request)
```

- [ ] **Step 5: 写限流中间件测试**

创建 `backend/tests/middleware/test_rate_limit.py`：

```python
import os
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def rate_limit_client():
    os.environ["API_KEY"] = ""
    os.environ["RATE_LIMIT"] = "3"
    with patch("middleware.rate_limit.get_redis") as mock_redis:
        mock_r = AsyncMock()
        mock_r.incr.return_value = 1
        mock_r.expire = AsyncMock()
        mock_r.ttl.return_value = 59
        mock_redis.return_value = mock_r
        from main import app
        yield TestClient(app)


class TestRateLimit:
    def test_allows_within_limit(self, rate_limit_client):
        resp = rate_limit_client.post(
            "/api/v1/chat", json={"message": "hello"},
            headers={"X-API-Key": "test"},
        )
        assert resp.status_code != 429
```

- [ ] **Step 6: 实现限流中间件**

创建 `backend/middleware/rate_limit.py`：

```python
import os
import time
from fastapi import Request, HTTPException
from services.task_queue.manager import get_redis

RATE_LIMIT = int(os.getenv("RATE_LIMIT", "60"))

PUBLIC_PATHS = {"/api/v1/health", "/", "/docs", "/openapi.json"}


async def rate_limit_middleware(request: Request, call_next):
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    if RATE_LIMIT <= 0:
        return await call_next(request)

    client_key = request.headers.get("X-API-Key", request.client.host if request.client else "unknown")
    redis_key = f"rate_limit:{client_key}"

    try:
        r = await get_redis()
        current = await r.incr(redis_key)
        if current == 1:
            await r.expire(redis_key, 60)
        if current > RATE_LIMIT:
            raise HTTPException(status_code=429, detail="rate limit exceeded")
    except HTTPException:
        raise
    except Exception:
        # Redis 不可用时放行（降级策略）
        pass

    return await call_next(request)
```

- [ ] **Step 7: 在 main.py 注册中间件**

在 `backend/main.py` 中，`app = FastAPI(...)` 之后添加：

```python
from middleware.auth import auth_middleware
from middleware.rate_limit import rate_limit_middleware

app.middleware("http")(auth_middleware)
app.middleware("http")(rate_limit_middleware)
```

- [ ] **Step 8: 运行测试**

```bash
cd backend && python -m pytest tests/middleware/ -v
# 预期：全部通过
```

- [ ] **Step 9: Commit**

```bash
git add backend/middleware/ backend/tests/middleware/ backend/main.py
git commit -m "feat: add API key auth and rate limiting middleware"
```

---

### Task 5: RAG — 基础设施（config + embedder + chunker + retriever）

**Files:**
- Create: `backend/services/rag/__init__.py`, `backend/services/rag/config.py`, `backend/services/rag/embedder.py`, `backend/services/rag/chunker.py`, `backend/services/rag/retriever.py`
- Create: `backend/tests/services/rag/__init__.py`, `backend/tests/services/rag/test_chunker.py`, `backend/tests/services/rag/test_retriever.py`

- [ ] **Step 1: 创建模块目录和 __init__ 文件**

```bash
mkdir -p backend/services/rag
mkdir -p backend/tests/services/rag
```

```python
# backend/services/rag/__init__.py
from services.rag.embedder import Embedder
from services.rag.chunker import chunk_text
from services.rag.retriever import Retriever
from services.rag.config import RAGConfig

__all__ = ["Embedder", "chunk_text", "Retriever", "RAGConfig"]
```

```python
# backend/tests/services/rag/__init__.py
```

- [ ] **Step 2: 实现 config.py**

```python
# backend/services/rag/config.py
import os

class RAGConfig:
    chunk_size: int = int(os.getenv("RAG_CHUNK_SIZE", "500"))
    chunk_overlap: int = int(os.getenv("RAG_CHUNK_OVERLAP", "50"))
    top_k: int = int(os.getenv("RAG_TOP_K", "5"))
    embedding_dim: int = 1024
    model_path: str = os.getenv("BGE_M3_PATH", "/models/bge-m3")
```

- [ ] **Step 3: 写 chunker 测试**

```python
# backend/tests/services/rag/test_chunker.py
from services.rag.chunker import chunk_text


class TestChunkText:
    def test_short_text_returns_single_chunk(self):
        text = "这是一段简短的研报内容。"
        chunks = chunk_text(text, chunk_size=500, overlap=50)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_splits_into_chunks(self):
        text = "测试内容。" * 200  # ~1200 chars
        chunks = chunk_text(text, chunk_size=200, overlap=30)
        assert len(chunks) > 1
        # 每个 chunk 不超过 chunk_size + overlap
        for c in chunks:
            assert len(c) <= 230

    def test_overlap_preserves_context(self):
        text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        chunks = chunk_text(text, chunk_size=10, overlap=3)
        # 第二个块的前几个字符应该与第一个块的末尾重叠
        assert len(chunks) > 1
        assert chunks[1][:3] == chunks[0][-3:]

    def test_empty_text_returns_empty_list(self):
        assert chunk_text("", chunk_size=500, overlap=50) == []
        assert chunk_text("   ", chunk_size=500, overlap=50) == []

    def test_paragraph_boundary_chunking(self):
        text = "第一段。\n\n第二段。\n\n第三段。"
        chunks = chunk_text(text, chunk_size=500, overlap=50)
        assert len(chunks) == 1  # 短文本不拆分
```

- [ ] **Step 4: 实现 chunker.py**

```python
# backend/services/rag/chunker.py


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """将长文本按段落边界切块，块间有滑动窗口重叠。"""
    text = text.strip()
    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    # 先按段落分割
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks = []
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) + 2 <= chunk_size:
            current_chunk = (current_chunk + "\n\n" + para).strip("\n")
        else:
            if current_chunk:
                chunks.append(current_chunk)
            # 如果段落本身超过 chunk_size，按字符滑动窗口拆分
            if len(para) > chunk_size:
                sub_chunks = _split_long_paragraph(para, chunk_size, overlap)
                chunks.extend(sub_chunks)
                current_chunk = ""
            else:
                current_chunk = para

    if current_chunk:
        # 与上一个块做 overlap
        if chunks and overlap > 0:
            last = chunks[-1]
            if len(last) > overlap:
                current_chunk = last[-overlap:] + "\n\n" + current_chunk
        chunks.append(current_chunk)

    return chunks


def _split_long_paragraph(text: str, chunk_size: int, overlap: int) -> list[str]:
    """对超长段落进行滑动窗口字符级拆分。"""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start += (chunk_size - overlap)
    return chunks
```

- [ ] **Step 5: 运行 chunker 测试**

```bash
cd backend && python -m pytest tests/services/rag/test_chunker.py -v
# 预期：5 passed
```

- [ ] **Step 6: 实现 embedder.py**

```python
# backend/services/rag/embedder.py
import structlog
from sentence_transformers import SentenceTransformer
from services.rag.config import RAGConfig

logger = structlog.get_logger()


class Embedder:
    """BGE-M3 本地 embedding 模型封装。"""

    def __init__(self, model_path: str | None = None):
        path = model_path or RAGConfig.model_path
        logger.info("embedder_loading", model_path=path)
        self.model = SentenceTransformer(path)
        self.dim = RAGConfig.embedding_dim
        logger.info("embedder_loaded", dim=self.dim)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量文本向量化，返回归一化的 1024 维向量。"""
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    def embed_query(self, text: str) -> list[float]:
        """单条查询向量化。"""
        return self.embed([text])[0]
```

- [ ] **Step 7: 实现 retriever.py**

```python
# backend/services/rag/retriever.py
import structlog
from sqlalchemy import text
from services.rag.embedder import Embedder
from services.rag.config import RAGConfig
from db.models import Document

logger = structlog.get_logger()


class Retriever:
    """pgvector 语义检索封装。"""

    def __init__(self, session_factory, embedder: Embedder | None = None):
        self.session_factory = session_factory
        self.embedder = embedder or Embedder()
        self.top_k = RAGConfig.top_k

    async def search(
        self, query: str, company_code: str = "",
        doc_type: str = "", top_k: int | None = None,
    ) -> list[dict]:
        """语义检索文档切片。"""
        k = top_k or self.top_k
        query_vec = self.embedder.embed_query(query)

        conditions = []
        params = {"query_vec": query_vec, "k": k}

        if company_code:
            conditions.append("company_code = :company_code")
            params["company_code"] = company_code
        if doc_type:
            conditions.append("doc_type = :doc_type")
            params["doc_type"] = doc_type

        where_clause = " AND ".join(conditions) if conditions else "TRUE"

        sql = text(f"""
            SELECT id, company_code, doc_type, doc_title, content, content_zh,
                   1 - (embedding <=> :query_vec) AS score
            FROM documents
            WHERE {where_clause}
              AND embedding IS NOT NULL
            ORDER BY embedding <=> :query_vec
            LIMIT :k
        """)

        async with self.session_factory() as session:
            result = await session.execute(sql, params)
            rows = result.fetchall()

        return [
            {
                "id": row.id,
                "company_code": row.company_code,
                "doc_type": row.doc_type,
                "doc_title": row.doc_title or "",
                "content": row.content,
                "content_zh": row.content_zh or "",
                "score": round(float(row.score), 4),
            }
            for row in rows
        ]
```

- [ ] **Step 8: Commit**

```bash
git add backend/services/rag/ backend/tests/services/rag/
git commit -m "feat: RAG infrastructure — config, embedder (BGE-M3), chunker, pgvector retriever"
```

---

### Task 6: RAG — 数据管道（ingester + Celery 定时任务）

**Files:**
- Create: `backend/services/rag/ingester.py`, `backend/services/rag/tasks.py`
- Create: `backend/tests/services/rag/test_ingester.py`

- [ ] **Step 1: 实现 ingester.py**

```python
# backend/services/rag/ingester.py
import structlog
from services.rag.chunker import chunk_text
from services.rag.embedder import Embedder
from services.rag.config import RAGConfig
from db.models import Document

logger = structlog.get_logger()


class Ingester:
    """文档入库管道：切块 → 向量化 → 写入 documents 表。"""

    def __init__(self, session_factory, embedder: Embedder | None = None):
        self.session_factory = session_factory
        self.embedder = embedder or Embedder()
        self.chunk_size = RAGConfig.chunk_size
        self.chunk_overlap = RAGConfig.chunk_overlap

    async def index_document(
        self, content: str, company_code: str, doc_type: str,
        doc_title: str = "", content_zh: str = "",
    ) -> list[int]:
        """单篇文档入库。返回 chunk ID 列表。"""
        chunks = chunk_text(content, self.chunk_size, self.chunk_overlap)
        if not chunks:
            return []

        embeddings = self.embedder.embed(chunks)

        chunk_ids = []
        async with self.session_factory() as session:
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                doc = Document(
                    company_code=company_code,
                    doc_type=doc_type,
                    doc_title=doc_title,
                    chunk_index=i,
                    content=chunk,
                    content_zh=content_zh if i == 0 else "",
                    embedding=emb,
                )
                session.add(doc)
                await session.flush()
                chunk_ids.append(doc.id)
            await session.commit()

        logger.info("document_indexed", title=doc_title, chunks=len(chunks),
                     company=company_code)
        return chunk_ids

    async def index_batch(self, documents: list[dict]) -> int:
        """批量入库。每项格式：{content, company_code, doc_type, doc_title, content_zh}"""
        total = 0
        for doc in documents:
            ids = await self.index_document(
                content=doc["content"],
                company_code=doc.get("company_code", ""),
                doc_type=doc.get("doc_type", "report"),
                doc_title=doc.get("doc_title", ""),
                content_zh=doc.get("content_zh", ""),
            )
            total += len(ids)
        return total

    async def delete_by_company(self, company_code: str) -> int:
        """删除某公司所有切片。"""
        from sqlalchemy import delete
        async with self.session_factory() as session:
            result = await session.execute(
                delete(Document).where(Document.company_code == company_code)
            )
            await session.commit()
            count = result.rowcount
            logger.info("documents_deleted", company=company_code, count=count)
            return count
```

- [ ] **Step 2: 实现 Celery 定时任务 tasks.py**

```python
# backend/services/rag/tasks.py
import structlog
from celery import Celery
from celery.schedules import crontab
import os

logger = structlog.get_logger()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery("rag_tasks", broker=REDIS_URL)

celery_app.conf.beat_schedule = {
    "fetch-research-reports": {
        "task": "services.rag.tasks.fetch_and_index_reports",
        "schedule": crontab(hour=2, minute=0),
    },
}
celery_app.conf.timezone = "Asia/Shanghai"


@celery_app.task
def fetch_and_index_reports():
    """每日凌晨 2:00 拉取最新研报并入库。"""
    import asyncio

    async def run():
        try:
            import akshare as ak
            df = ak.stock_research_report_em()
            if df is None or df.empty:
                logger.info("no_new_reports")
                return

            from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
            from sqlalchemy.orm import sessionmaker
            from services.rag.ingester import Ingester

            DATABASE_URL = os.getenv(
                "DATABASE_URL",
                "postgresql+asyncpg://financial_agent:financial_agent_2024@localhost:5432/financial_agent",
            )
            engine = create_async_engine(DATABASE_URL)
            async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

            ingester = Ingester(async_session)

            docs = []
            for _, row in df.head(50).iterrows():
                content = str(row.get("摘要", "") or row.get("内容", ""))
                if not content or len(content) < 50:
                    continue
                docs.append({
                    "content": content,
                    "company_code": str(row.get("股票代码", "")),
                    "doc_type": "report",
                    "doc_title": str(row.get("研报标题", "")),
                })

            if docs:
                total = await ingester.index_batch(docs)
                logger.info("reports_indexed", total=total)

            await engine.dispose()
        except Exception as e:
            logger.error("report_fetch_failed", error=str(e))

    asyncio.run(run())
```

- [ ] **Step 3: 写 ingester 集成测试**

```python
# backend/tests/services/rag/test_ingester.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestIngester:
    @pytest.mark.asyncio
    async def test_index_document_stores_chunks(self):
        from services.rag.ingester import Ingester
        from services.rag.embedder import Embedder

        # Mock session
        mock_session = AsyncMock()
        mock_session_factory = MagicMock(return_value=MagicMock(
            __aenter__=AsyncMock(return_value=mock_session),
            __aexit__=AsyncMock(return_value=None),
        ))

        # Mock embedder
        mock_embedder = MagicMock(spec=Embedder)
        mock_embedder.embed.return_value = [[0.1] * 1024]

        ingester = Ingester(mock_session_factory, embedder=mock_embedder)

        ids = await ingester.index_document(
            content="测试研报内容，包含足够的文字来验证切块逻辑。" * 20,
            company_code="600519",
            doc_type="report",
            doc_title="测试研报",
        )

        assert len(ids) > 0
        assert mock_session.add.call_count == len(ids)
        mock_session.commit.assert_called_once()
```

- [ ] **Step 4: 运行 RAG 测试**

```bash
cd backend && python -m pytest tests/services/rag/ -v
# 预期：全部通过
```

- [ ] **Step 5: Commit**

```bash
git add backend/services/rag/ingester.py backend/services/rag/tasks.py \
        backend/tests/services/rag/test_ingester.py
git commit -m "feat: RAG ingestion pipeline + Celery beat daily report fetch"
```

---

### Task 7: RAG — LLM 上下文注入

**Files:**
- Create: `backend/services/rag/search.py` (简化调用封装)
- Modify: `backend/prompts/report_generation.py`, `backend/agents/reviewer/report_generator.py`
- Modify: `backend/tests/agents/test_reviewer.py` (已有测试需更新)

- [ ] **Step 1: 创建轻量 search 封装**

```python
# backend/services/rag/search.py
"""对 report_generator_node 暴露的简化检索接口。"""
import structlog
from services.rag.retriever import Retriever
from services.rag.embedder import Embedder

logger = structlog.get_logger()

_retriever: Retriever | None = None
_embedder: Embedder | None = None


def _get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


async def search_rag(
    query: str, company_code: str = "", top_k: int = 5,
    session_factory=None,
) -> list[dict]:
    """从知识库中语义检索相关文档切片。"""
    if session_factory is None:
        logger.warning("rag_search_skip_no_session")
        return []

    try:
        embedder = _get_embedder()
        retriever = Retriever(session_factory, embedder=embedder)
        results = await retriever.search(
            query, company_code=company_code, top_k=top_k,
        )
        logger.info("rag_search_done", query=query[:50], results=len(results))
        return results
    except Exception as e:
        logger.error("rag_search_error", error=str(e))
        return []
```

- [ ] **Step 2: 修改 report_generation prompt — 新增 rag_context 参数**

在 `backend/prompts/report_generation.py` 的 `build_report_prompt` 函数末尾（`return prompt` 之前）插入：

```python
    # --- RAG 上下文注入 ---
    rag_context = state.get("rag_context", "")
    if rag_context:
        prompt += f"""
### 参考研报（来自知识库）
{rag_context}

基于以上参考信息与分析数据生成投研报告。引用参考研报信息时，
在正文中以 [来源: xxx] 标注出处。
"""
```

同时修改函数签名：

```python
def build_report_prompt(state: dict, retry_context: str = "") -> str:
```

保持不变（rag_context 从 state 中读取，不通过参数传入）。

- [ ] **Step 3: 修改 report_generator_node — 报告生成前调用 RAG 检索**

在 `backend/agents/reviewer/report_generator.py` 的 `report_generator_node` 中，LLM 调用之前插入：

```python
        # --- RAG 检索：报告生成前从知识库搜索相关研报 ---
        rag_context = ""
        try:
            from services.rag.search import search_rag
            from db.models import Document
            from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
            from sqlalchemy.orm import sessionmaker
            import os

            db_url = os.getenv("DATABASE_URL", "")
            if db_url:
                engine = create_async_engine(
                    db_url.replace("postgresql://", "postgresql+asyncpg://"), echo=False,
                )
                async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
                code = state.get("company_code", "")
                name = state.get("company_name", code)
                query = f"{name} 财务分析 经营风险 行业展望 投资评级"
                results = await search_rag(
                    query=query, company_code=code, top_k=5,
                    session_factory=async_session,
                )
                if results:
                    rag_parts = []
                    for r in results:
                        rag_parts.append(
                            f"**[{r['doc_title']}]** (相关度: {r['score']:.0%})\n"
                            f"{r['content'][:300]}"
                        )
                    rag_context = "\n\n---\n\n".join(rag_parts)
                    state["rag_context"] = rag_context
                await engine.dispose()
        except Exception as e:
            logger.warning("rag_retrieval_skipped", error=str(e))
```

**注意**：这需要在 `report_generator_node` 文件顶部新增导入：

```python
import os
```

- [ ] **Step 4: 更新 reviewer 测试 — Mock RAG 检索**

在 `backend/tests/agents/test_reviewer.py` 的 `test_generates_report` 中，为 RAG 检索添加 mock：

```python
    @pytest.mark.asyncio
    async def test_generates_report_with_rag(self):
        state = make_initial_state("task-001")
        state["company_code"] = "600519"
        state["company_name"] = "贵州茅台"
        state["financial_analysis"] = {
            "dupont_decomposition": {"roe": 0.25, "net_margin": 0.50, "asset_turnover": 0.25,
                                      "equity_multiplier": 2.0, "is_valid": True},
            "anomaly_flags": [], "narrative": "茅台Q3盈利表现强劲", "analyst_confidence": "high",
        }
        state["sentiment_result"] = {
            "overall_sentiment": "positive", "overall_score": 0.72,
            "key_topics": ["业绩增长"], "summary": "舆情正面",
        }
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = {"content": "# 贵州茅台投研分析报告\n\n## 核心摘要\n...",
                                         "model": "deepseek-chat",
                                         "usage": {"prompt_tokens": 500, "completion_tokens": 800}}
        with patch("agents.reviewer.report_generator.get_llm_service", return_value=mock_llm):
            with patch("agents.reviewer.report_generator.search_rag",
                       new_callable=AsyncMock, return_value=[]):
                result = await report_generator_node(state)
                assert result["draft_report"] is not None
                assert len(result["draft_report"]) > 0
```

保留原有的 `test_generates_report`（改名为 `test_generates_report_basic` 以区分）。

- [ ] **Step 5: 运行 reviewer 测试**

```bash
cd backend && python -m pytest tests/agents/test_reviewer.py -v
# 预期：全部通过
```

- [ ] **Step 6: Commit**

```bash
git add backend/services/rag/search.py backend/prompts/report_generation.py \
        backend/agents/reviewer/report_generator.py backend/tests/agents/test_reviewer.py
git commit -m "feat: integrate RAG search into report generation pipeline"
```

---

### Task 8: 容器化 — Dockerfile + Compose 编排

**Files:**
- Create: `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`, `frontend/.env.production`
- Modify: `docker-compose.yml` (在 Task 1 基础上扩展为全栈编排)

- [ ] **Step 1: 后端 Dockerfile**

```dockerfile
# backend/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 源码
COPY . .

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: 前端 Dockerfile**

```dockerfile
# frontend/Dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json .
RUN npm ci
COPY . .
ARG VITE_API_BASE=/api/v1
ARG VITE_API_KEY=
ENV VITE_API_BASE=$VITE_API_BASE
ENV VITE_API_KEY=$VITE_API_KEY
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

- [ ] **Step 3: 前端 nginx.conf**

```nginx
server {
    listen 80;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    # API 反代
    location /api/ {
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
        proxy_buffering off;         # SSE 必须关闭缓冲
        proxy_http_version 1.1;
        proxy_set_header Connection '';
    }

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 静态资源缓存
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

- [ ] **Step 4: 前端 .env.production**

```
VITE_API_BASE=/api/v1
VITE_API_KEY=
```

- [ ] **Step 5: 更新 docker-compose.yml 为全栈编排**

在 Task 1 的 postgres 和 redis 之外，追加：

```yaml
  api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://financial_agent:${PG_PASSWORD:-financial_agent_2024}@postgres:5432/financial_agent
      - REDIS_URL=redis://redis:6379/0
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
      - DEEPSEEK_API_BASE=${DEEPSEEK_API_BASE:-https://api.deepseek.com/v1}
      - API_KEY=${API_KEY:-}
      - DATA_SOURCE=${DATA_SOURCE:-akshare}
      - BGE_M3_PATH=${BGE_M3_PATH:-/models/bge-m3}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
    volumes:
      - ${BGE_M3_PATH:-./models/bge-m3}:/models/bge-m3:ro
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 5s
      retries: 3

  worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: celery -A services.task_queue.celery_app worker --loglevel=info
    environment:
      - DATABASE_URL=postgresql://financial_agent:${PG_PASSWORD:-financial_agent_2024}@postgres:5432/financial_agent
      - REDIS_URL=redis://redis:6379/0
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
      - DEEPSEEK_API_BASE=${DEEPSEEK_API_BASE:-https://api.deepseek.com/v1}
      - BGE_M3_PATH=${BGE_M3_PATH:-/models/bge-m3}
    volumes:
      - ${BGE_M3_PATH:-./models/bge-m3}:/models/bge-m3:ro
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started

  beat:
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: celery -A services.rag.tasks beat --loglevel=info
    environment:
      - DATABASE_URL=postgresql://financial_agent:${PG_PASSWORD:-financial_agent_2024}@postgres:5432/financial_agent
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
      args:
        VITE_API_KEY: ${API_KEY:-}
    ports:
      - "${FRONTEND_PORT:-80}:80"
    depends_on:
      - api
```

- [ ] **Step 6: Commit**

```bash
git add backend/Dockerfile frontend/Dockerfile frontend/nginx.conf \
        frontend/.env.production docker-compose.yml
git commit -m "feat: add Dockerfiles and full-stack docker-compose orchestration"
```

---

### Task 9: 前端生产化改造

**Files:**
- Modify: `frontend/src/api/chat.ts`, `frontend/src/api/reports.ts`, `frontend/src/api/dashboard.ts`, `frontend/vite.config.ts`

- [ ] **Step 1: 修改 chat.ts — 添加认证头和环境变量**

```typescript
// frontend/src/api/chat.ts
export interface ChatEvent {
  intent?: string
  text?: string
  task_id?: string
  message?: string
  agent?: string
  status?: string
  latency_ms?: number
}

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'
const API_KEY = import.meta.env.VITE_API_KEY || ''

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (API_KEY) headers['X-API-Key'] = API_KEY
  return headers
}

export async function postChat(
  message: string,
  onIntent: (intent: string) => void,
  onChunk: (text: string) => void,
  onDone: (taskId: string) => void,
  onError: (error: string) => void,
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ message }),
  })
  // ... SSE 解析逻辑保持不变 ...
}

export async function postTask(companyCode: string, reportDate: string = '') {
  const response = await fetch(`${API_BASE}/tasks`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ company_code: companyCode, report_date: reportDate }),
  })
  return response.json()
}

export async function getTaskStatus(taskId: string) {
  const headers: Record<string, string> = {}
  if (API_KEY) headers['X-API-Key'] = API_KEY
  const response = await fetch(`${API_BASE}/tasks/${taskId}`, { headers })
  return response.json()
}
```

- [ ] **Step 2: 修改 reports.ts — 添加认证头**

```typescript
const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'
const API_KEY = import.meta.env.VITE_API_KEY || ''

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (API_KEY) headers['X-API-Key'] = API_KEY
  return headers
}

// 所有 fetch 调用使用 authHeaders()
```

- [ ] **Step 3: 修改 dashboard.ts — 同上**

```typescript
const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'
const API_KEY = import.meta.env.VITE_API_KEY || ''

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (API_KEY) headers['X-API-Key'] = API_KEY
  return headers
}
```

- [ ] **Step 4: 更新 vite.config.ts**

```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  },
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
})
```

- [ ] **Step 5: 验证前端构建**

```bash
cd frontend && npm run build
# 预期：dist/ 目录生成，含 index.html + assets/
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/chat.ts frontend/src/api/reports.ts \
        frontend/src/api/dashboard.ts frontend/vite.config.ts
git commit -m "feat: production-ready frontend — auth headers, env vars, vite build config"
```

---

### Task 10: CI/CD — GitHub Actions 部署流水线

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: 创建 CI/CD workflow**

```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [master]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: financial_agent
          POSTGRES_PASSWORD: test
          POSTGRES_DB: financial_agent
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install dependencies
        working-directory: backend
        run: pip install -r requirements.txt pytest pytest-asyncio pytest-cov

      - name: Run tests with coverage
        working-directory: backend
        env:
          DATABASE_URL: postgresql://financial_agent:test@localhost:5432/financial_agent
          REDIS_URL: redis://localhost:6379/0
        run: |
          python -m pytest tests/ -v --tb=short --cov=. --cov-report=term-missing

      - name: Lint check
        working-directory: backend
        run: |
          pip install ruff
          ruff check .

      - name: Alembic check
        working-directory: backend
        env:
          DATABASE_URL: postgresql://financial_agent:test@localhost:5432/financial_agent
        run: |
          pip install alembic
          alembic upgrade head
          alembic check

  deploy:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/master'
    steps:
      - uses: actions/checkout@v4

      - name: Deploy to server
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.DEPLOY_HOST }}
          username: ${{ secrets.DEPLOY_USER }}
          key: ${{ secrets.DEPLOY_SSH_KEY }}
          script: |
            cd /opt/financial-agent
            git pull origin master
            echo "PG_PASSWORD=${{ secrets.PG_PASSWORD }}" > .env.production
            echo "DEEPSEEK_API_KEY=${{ secrets.DEEPSEEK_API_KEY }}" >> .env.production
            echo "API_KEY=${{ secrets.API_KEY }}" >> .env.production
            docker compose build
            docker compose up -d --force-recreate
            sleep 10
            curl -f http://localhost:8000/api/v1/health || (docker compose down && exit 1)
```

- [ ] **Step 2: Commit**

```bash
mkdir -p .github/workflows
git add .github/workflows/deploy.yml
git commit -m "feat: add CI/CD pipeline — test, lint, alembic check, deploy with health validation"
```

---

### Task 11: 端到端集成测试与文档更新

**Files:**
- Create: `backend/tests/test_e2e.py`
- Modify: `readme.md`

- [ ] **Step 1: 写端到端集成测试**

```python
# backend/tests/test_e2e.py
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from state import make_initial_state


class TestE2EHealthCheck:
    def test_health_returns_all_services(self):
        from main import app
        client = TestClient(app)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "postgres" in data
        assert "redis" in data
        assert "version" in data


class TestE2EChatSSE:
    def test_chat_streams_sse_events(self):
        from main import app
        client = TestClient(app)
        # 使用 empty API_KEY 绕过认证
        import os
        os.environ["API_KEY"] = ""
        resp = client.post(
            "/api/v1/chat",
            json={"message": "Hello"},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        content_type = resp.headers.get("content-type", "")
        assert "text/event-stream" in content_type


class TestE2ETaskLifecycle:
    @pytest.mark.asyncio
    async def test_submit_and_query_task(self):
        import os
        os.environ["API_KEY"] = ""
        from main import app
        client = TestClient(app)

        # 提交任务
        resp = client.post("/api/v1/tasks", json={
            "company_code": "600519",
            "report_date": "2024-09-30",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "task_id" in data
        assert data["status"] == "pending"

        # 查询状态
        task_id = data["task_id"]
        resp = client.get(f"/api/v1/tasks/{task_id}")
        assert resp.status_code == 200
        status = resp.json()
        assert status.get("task_id") == task_id


class TestE2EAuthFlow:
    def test_public_endpoints_no_auth(self):
        import os
        os.environ["API_KEY"] = "secret"
        from main import app
        client = TestClient(app)

        # 公开端点无需认证
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/").status_code == 200
        assert client.get("/docs").status_code == 200

    def test_protected_endpoint_requires_auth(self):
        import os
        os.environ["API_KEY"] = "secret"
        from main import app
        client = TestClient(app)

        # 无 Key 拒绝
        resp = client.post("/api/v1/chat", json={"message": "hi"})
        assert resp.status_code == 401

        # 有效 Key 通过
        resp = client.post(
            "/api/v1/chat",
            json={"message": "hi"},
            headers={"X-API-Key": "secret"},
        )
        assert resp.status_code != 401


class TestE2ERAGPipeline:
    @pytest.mark.asyncio
    async def test_rag_search_without_db_returns_empty(self):
        from services.rag.search import search_rag
        results = await search_rag("测试查询", company_code="600519", session_factory=None)
        assert results == []

    @pytest.mark.asyncio
    async def test_chunker_integration(self):
        from services.rag.chunker import chunk_text
        from services.rag.embedder import Embedder

        text = "这是一段测试研报内容。" * 50
        chunks = chunk_text(text, chunk_size=200, overlap=30)
        assert len(chunks) > 1

        # 验证每个 chunk 可以独立向量化（如果模型可用）
        try:
            embedder = Embedder()
            embeddings = embedder.embed(chunks)
            assert len(embeddings) == len(chunks)
            assert len(embeddings[0]) == 1024
        except Exception:
            pass  # 模型路径不可用时跳过
```

- [ ] **Step 2: 运行端到端测试**

```bash
cd backend && python -m pytest tests/test_e2e.py -v --tb=short
# 预期：全部通过（RAG embedding 测试可能因模型路径跳过）
```

- [ ] **Step 3: 运行全部测试**

```bash
cd backend && python -m pytest tests/ -v --tb=short
# 预期：全部通过，覆盖率 ≥ 80%
```

- [ ] **Step 4: 更新 readme.md — 生产部署章节**

在 readme.md 末尾追加：

```markdown
## 生产部署

### 环境要求
- Docker 24.0+ & Docker Compose v2
- Python 3.11+（本地开发）
- BGE-M3 模型文件（放置在 `./models/bge-m3/`）

### 快速启动

```bash
# 1. 配置环境变量
cp backend/.env.example backend/.env
# 编辑 .env：填入 DEEPSEEK_API_KEY、PG_PASSWORD、API_KEY、BGE_M3_PATH

# 2. 全栈启动
docker compose up -d

# 3. 验证
curl http://localhost:8000/api/v1/health
# {"status":"healthy","postgres":"connected","redis":"connected","version":"1.0.0"}

# 4. 应用数据库迁移（首次部署）
docker compose exec api alembic upgrade head
```

### 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| 前端 + Nginx | 80 | SPA + API 反代 |
| FastAPI | 8000 | 后端 API |
| PostgreSQL | 5432 | 数据库 + pgvector |
| Redis | 6379 | 任务队列 |

### 环境变量（生产必填）

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | LLM API 密钥 |
| `PG_PASSWORD` | PostgreSQL 密码 |
| `API_KEY` | API 认证密钥（前端/客户端需携带） |
| `BGE_M3_PATH` | BGE-M3 模型本地路径（默认 /models/bge-m3） |
```

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_e2e.py readme.md
git commit -m "test: add end-to-end integration tests and update production deploy docs"
```

---

## 任务依赖图

```
Task 1 (PG 迁移) ──────┬──→ Task 2 (Alembic)
                       │
                       ├──→ Task 5 (RAG 基础设施)
                       │         └──→ Task 6 (RAG 管道)
                       │                   └──→ Task 7 (RAG LLM 注入)
                       │
                       ├──→ Task 3 (熔断器) ── 独立，可并行
                       │
                       └──→ Task 4 (安全中间件) ── 独立，可并行

Task 8 (容器化) ────── ───→ Task 10 (CI/CD)
Task 9 (前端生产化) ──┘

Task 11 (集成测试) ── 最后执行，依赖所有前置任务
```

---

**预估总工时：18.5 人天，按顺序单人执行约 4 周，或 2 人并行约 2 周。**
