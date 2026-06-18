# 进程管理指南

## 问题

开发过程中频繁重启前后端服务，导致以下问题反复出现：

1. **Celery 多实例冲突** — `taskkill` 未清理所有 celery.exe，新旧 worker 同名导致 `DuplicateNodenameWarning`，任务被发送到已死 worker
2. **Python 子进程残留** — `uvicorn --reload` 会 fork 子进程，`taskkill //IM python.exe` 只杀主进程，子进程继续占用端口
3. **综合分析无结果** — Celery worker 冲突时，前端显示 `⏳ 任务已提交` 但任务永远不会被执行

## 根因

| 现象 | 根因 |
|------|------|
| 3 个 celery.exe 同时运行 | 多次启动 Celery 未先杀旧进程 |
| `DuplicateNodenameWarning` | 两个 worker 使用相同节点名 `celery@LAPTOP-OUC3J920` |
| 任务提交后无响应 | Redis 把任务发给了已僵死的旧 worker |
| 端口 8000 被占用 | uvicorn 子进程未被 taskkill 清理 |

## 解决方案

### 1. 统一启动脚本

创建 `backend/start_all.bat`：

```bat
@echo off
echo === Killing all existing processes ===
taskkill /F /IM python.exe 2>nul
taskkill /F /IM celery.exe 2>nul
taskkill /F /IM node.exe 2>nul
timeout /t 2 /nobreak >nul

echo === Starting Docker containers ===
docker start financial-agent-redis-1 financial-agent-postgres-1 2>nul
timeout /t 3 /nobreak >nul

echo === Starting Backend ===
start "Backend" cmd /c "cd /d %~dp0 && uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

echo === Waiting for backend warm-up (embedder model loading) ===
timeout /t 20 /nobreak >nul

echo === Starting Celery Worker ===
start "Celery" cmd /c "cd /d %~dp0 && celery -A services.task_queue.celery_app worker --loglevel=info -P solo -n worker1"

echo === Starting Frontend ===
start "Frontend" cmd /c "cd /d %~dp0..\frontend && npm run dev"

echo === All services started ===
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:5173
echo Celery:   worker1
pause
```

### 2. Celery 命名规范

**始终使用唯一节点名**，避免默认的机器名冲突：

```bash
# ❌ 默认节点名 — 同名冲突
celery -A services.task_queue.celery_app worker -P solo

# ✅ 显式唯一节点名
celery -A services.task_queue.celery_app worker -P solo -n worker1

# ✅ 生产环境用 hostname
celery -A services.task_queue.celery_app worker -P solo -n worker@%COMPUTERNAME%
```

### 3. 彻底杀进程

不要依赖 `taskkill //IM python.exe` — 用端口定位更可靠：

```bash
# 按端口杀进程（Windows）
for /f "tokens=5" %a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %a
for /f "tokens=5" %a in ('netstat -ano ^| findstr :5173 ^| findstr LISTENING') do taskkill /F /PID %a

# 或者用 PowerShell（推荐）
Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

### 4. Docker Compose 健康检查

确保基础设施容器在应用之前就绪：

```bash
# 启动并等待健康
docker compose up -d --wait

# 或者手动等待
docker start financial-agent-redis-1 financial-agent-postgres-1
timeout /t 5
docker exec financial-agent-postgres-1 pg_isready -U financial_agent
```

### 5. 故障排查清单

当出现"任务提交但无结果"时，按顺序检查：

1. `curl http://localhost:8000/api/v1/health` — 后端是否存活
2. `docker ps` — Redis/PostgreSQL 容器是否运行
3. `tasklist | findstr celery` — Celery worker 是否只有一个进程
4. `celery -A services.task_queue.celery_app inspect active` — worker 是否在消费任务
5. 查看 `backend/celery.log` 确认任务是否被接收和执行

## 预防措施

- 每次 `taskkill //IM python.exe` 后**必须等 2 秒**再启动新进程
- Celery 启动前**确认只有一个 celery.exe**（`tasklist | findstr celery`）
- uvicorn 使用 `--reload` 时，**不要手动 `taskkill` 子进程**，杀主进程即可
- 开发环境 Celery 使用 `-P solo`（单进程，调试友好），生产用 `-P prefork`
