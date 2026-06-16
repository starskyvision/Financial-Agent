# 数据契约（Schema 真相源）

## MySQL 表结构

### financial_data — 财务数据中心

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | 自增主键 |
| company_code | VARCHAR(10) | 股票代码 |
| report_date | DATE | 报告期 |
| metric_name | VARCHAR(64) | 指标名称 |
| metric_value | DECIMAL(20,4) | 指标值 |
| source | VARCHAR(32) | 数据来源（wind/pdf/llm） |
| created_at | DATETIME | 创建时间 |

### documents — 文档切片

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | 自增主键 |
| company_code | VARCHAR(10) | 关联股票 |
| doc_type | VARCHAR(32) | 文档类型（report/announcement/transcript） |
| chunk_index | INT | 切片序号 |
| content | TEXT | 原文内容 |
| vector_id | VARCHAR(64) | Milvus 向量 ID |
| created_at | DATETIME | 创建时间 |

### tasks — 任务记录

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(36) PK | 任务 UUID |
| company_code | VARCHAR(10) | 目标股票 |
| status | ENUM | pending/running/done/failed |
| result | JSON | 结果摘要 |
| error_log | TEXT | 错误日志 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

## Milvus Collection

### financial_docs

- **Partition Key**: `company_code`
- **Index**: HNSW, metric_type=IP
- **Fields**: id (PK), company_code (VARCHAR), doc_type (VARCHAR), chunk_text (VARCHAR), embedding (FLOAT_VECTOR 4096), sparse_embedding (SPARSE_FLOAT_VECTOR)

## Redis Key 约定

| Key 模式 | 用途 | TTL |
|----------|------|-----|
| `task:{task_id}` | 任务状态缓存 | 1h |
| `task:{task_id}:progress` | 任务进度（0-100） | 1h |
| `sentiment:{company_code}:{date}` | 舆情时序数据 | 24h |
