# Phase 1 — 数据源抽象层

**优先级**: P0　|　**前置**: Phase 0　|　**预计工时**: 1.5 天

## 目标

实现 `DataSourceAdapter` 协议接口和 AKShare 适配器，使数据收集 Agent 可以通过统一接口获取财务数据、新闻、文档。

## 子任务

### 1.1 定义 Adapter 协议接口

📁 `backend/services/data_sources/base.py`

- [ ] 定义 `DataSourceAdapter` Protocol 类，包含三个方法签名：
  ```python
  async def fetch_financials(self, code: str, date: str, metrics: list[str]) -> dict
  async def fetch_news(self, code: str, days: int) -> list[dict]
  async def fetch_documents(self, code: str, doc_type: str, limit: int) -> list[dict]
  ```
- [ ] `fetch_financials` 返回格式：`{"revenue": 123.4, "net_profit": 56.7, ...}` （数值单位为亿元）
- [ ] `fetch_news` 返回格式：`[{"title": "...", "summary": "...", "source": "...", "published_at": "..."}, ...]`
- [ ] 定义 `DataSourceConfig` Pydantic 模型（`source_type`, `api_key`, `timeout`）

**验收**: `DataSourceAdapter` 协议类可通过 `isinstance` 检查

### 1.2 实现 AKShare 适配器

📁 `backend/services/data_sources/akshare_adapter.py`

- [ ] 实现 `AKShareAdapter` 类，遵循 `DataSourceAdapter` 协议
- [ ] `fetch_financials` 对接 AKShare `stock_financial_abstract` 接口，按 A 股代码拉取利润表、资产负债表核心指标
- [ ] 股票代码格式转换：用户输入 `600519` / `600519.SH` / `SH600519` → 统一为 AKShare 所需格式
- [ ] `fetch_news` 对接 AKShare `stock_news_em` 接口，支持按天数过滤
- [ ] `fetch_documents` MVP 阶段返回空列表（AKShare 不支持文档下载），预留扩展点
- [ ] 异步 HTTP 请求使用 `httpx.AsyncClient`，设置 30s 超时
- [ ] 错误处理：捕捉网络异常、数据缺失，返回空 dict/list 并记录 WARNING 日志

**验收**: 调用 `fetch_financials("600519", "2024-09-30", ["revenue","net_profit"])` 返回非空 dict

### 1.3 实现数据源工厂

📁 `backend/services/data_sources/__init__.py`

- [ ] 实现 `create_data_source(config: DataSourceConfig) -> DataSourceAdapter`
- [ ] 支持 `match config.source_type` 分发：
  - `"akshare"` → `AKShareAdapter`
  - `"tushare"` → 预留 `TushareAdapter`（返回 `NotImplementedError`）
  - `"wind"` → 预留 `WindAdapter`（返回 `NotImplementedError`）
- [ ] 单例模式：同一 `source_type` 复用同一实例（模块级缓存）

**验收**: `create_data_source(DataSourceConfig(source_type="akshare"))` 返回 `AKShareAdapter` 实例

### 1.4 编写 AKShare Adapter 单元测试

📁 `backend/tests/services/test_akshare_adapter.py`

- [ ] Mock httpx 响应，测试 `fetch_financials` 正常解析
- [ ] 测试股票代码格式转换逻辑（3 种输入格式）
- [ ] 测试网络异常时返回空 dict（不抛异常）
- [ ] 测试 `create_data_source` 工厂分发

**验收**: `pytest tests/services/test_akshare_adapter.py` 全部通过

### 1.5 数据归一化入库

📁 `backend/services/data_sources/importer.py`

- [ ] 实现 `import_financials_to_db(code, date, financials: dict, db_session)` 函数
- [ ] 将 `fetch_financials` 返回的 dict 按 `metric_name` / `metric_value` 拆分为多条记录写入 MySQL `financial_data` 表
- [ ] 实现幂等性：同一 `(company_code, report_date, metric_name)` 组合存在时更新，不存在时插入（`ON DUPLICATE KEY UPDATE`）
- [ ] `source` 字段填入 `"akshare"`

**验收**: 导入后查询 `SELECT * FROM financial_data WHERE company_code='600519'` 有数据

---

## 产出物

- [ ] `backend/services/data_sources/base.py` — Adapter 协议
- [ ] `backend/services/data_sources/akshare_adapter.py` — AKShare 实现
- [ ] `backend/services/data_sources/__init__.py` — 工厂函数
- [ ] `backend/services/data_sources/importer.py` — 入库模块
- [ ] `backend/tests/services/test_akshare_adapter.py` — 单元测试

*关联文档: [设计规格 §3.2](../superpowers/specs/2026-06-16-financial-agent-mvp-design.md#32-数据收集-agent)*
