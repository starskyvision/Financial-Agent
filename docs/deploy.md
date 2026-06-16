# 部署文档

## 环境要求

- Docker 24.0+
- Docker Compose v2
- Python 3.11+
- Node.js 18+（前端开发）

## 生产部署

### 1. 环境变量

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入生产环境配置
# 特别注意：APP_ENV=production, LOG_LEVEL=WARNING
```

### 2. 构建与启动

```bash
# 构建镜像
docker compose build

# 后台启动
docker compose up -d

# 查看日志
docker compose logs -f
```

### 3. 验证

```bash
# 健康检查
curl http://localhost:8000/api/v1/health

# 预期返回
# {"status": "healthy", "milvus": "connected", "redis": "connected", "mysql": "connected"}
```

## 常见问题

### Milvus 启动失败

检查 etcd 和 minio 容器是否先于 milvus 启动：

```bash
docker compose restart etcd minio
sleep 10
docker compose restart milvus
```

### 端口冲突

修改 `docker-compose.yml` 中的端口映射，或在 `.env` 中设置替代端口。

### GPU 部署 Qwen

若需 GPU 推理加速，确保安装 nvidia-container-toolkit：

```bash
# 验证 GPU 可用
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```
