# Phase 0 — 基础设施确认

**优先级**: P0　|　**前置**: 无　|　**预计工时**: 0.5 天

## 目标

确认 Docker 编排中各服务正常启动，Python 依赖安装无冲突，数据库表结构就绪。

## 子任务

### 0.1 环境变量配置

- [ ] 复制 `backend/.env.example` 为 `backend/.env`
- [ ] 填写必填项：
  - `DEEPSEEK_API_KEY` — DeepSeek API 密钥
  - `QWEN_API_BASE` — Qwen API 地址（备选降级）
  - `MILVUS_URI` — Milvus 连接地址（默认 `localhost:19530`）
  - `MYSQL_ROOT_PASSWORD` — MySQL root 密码
- [ ] 可选配置：`DATA_SOURCE=akshare`、`LOG_LEVEL=INFO`

**验收**: `.env` 文件中所有必填项不为空

### 0.2 Docker 服务启动

- [ ] 执行 `docker compose up -d --build`
- [ ] 确认 6 个容器全部 Running：etcd、minio、milvus、redis、mysql
- [ ] 确认 MySQL `financial_agent` 数据库已创建，`financial_data`/`documents`/`tasks` 三张表已初始化
- [ ] 确认 Milvus `financial_docs` Collection 已创建
- [ ] 确认 Redis 可连接（`docker compose exec redis redis-cli PING` → `PONG`）

**验收**: `docker compose ps` 全部 `Up` 状态，三张 MySQL 表存在

### 0.3 依赖安装验证

- [ ] `cd backend && pip install -r requirements.txt`
- [ ] 确认无版本冲突报错，尤其关注：
  - `redis` 版本在 5.0~5.2.1 范围内（Celery 兼容）
  - `pymilvus` 版本在 2.4.x 范围内
  - `langgraph>=1.2.0` 与 `langchain>=1.3.0` 版本兼容
- [ ] `python -c "import langgraph; print(langgraph.__version__)"` 输出版本 ≥1.2

**验收**: `pip check` 无冲突

### 0.4 健康检查端点

- [ ] 启动 FastAPI：`uvicorn main:app --host 0.0.0.0 --port 8000`
- [ ] `GET http://localhost:8000/api/v1/health` 返回 `{"status":"healthy"}`
- [ ] Swagger UI `http://localhost:8000/docs` 可访问

**验收**: `/api/v1/health` 返回 200

---

## 产出物

- [ ] `backend/.env` 已配置
- [ ] Docker 所有容器运行正常
- [ ] `pip check` 无冲突
- [ ] 健康检查端点可访问

*关联文档: [README.md](../../readme.md), [架构文档](../architecture.md)*
