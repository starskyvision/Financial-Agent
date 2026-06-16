# Phase 3 — 数据收集 Agent

**优先级**: P0　|　**前置**: Phase 1　|　**预计工时**: 1.5 天

## 目标

实现数据收集 Agent 节点，调用数据源 Adapter 拉取财务指标、新闻、文档，写入 MySQL 并填充 `State.raw_data`。

## 子任务

### 3.1 实现数据收集节点函数

📁 `backend/agents/data_collector/node.py`

- [ ] 实现 LangGraph 节点函数 `async def data_collector_node(state: AgentState) -> AgentState`
- [ ] 从 `state["company_code"]`、`state["report_date"]`、`state.get("metric_names")` 读取输入
- [ ] 调用 Adapter 的三个方法并行获取数据：
  ```python
  financials, news, docs = await asyncio.gather(
      adapter.fetch_financials(code, date, metrics),
      adapter.fetch_news(code, days=30),
      adapter.fetch_documents(code, "announcement", limit=5),
      return_exceptions=True
  )
  ```
- [ ] 并行中的单个调用失败不中断其他调用，失败项写入 `state["errors"]`
- [ ] 结果组装为 `state["raw_data"]`：
  ```python
  {
      "financial_metrics": {"revenue": ..., "net_profit": ..., ...},
      "news_headlines": [{"title": ..., "summary": ..., ...}, ...],
      "doc_snippets": [...],
      "data_sources": ["akshare"],
      "fetched_at": "2026-06-16T10:30:00"
  }
  ```
- [ ] 对于 `simple_query` 意图：按用户问的具体指标筛选，其他指标不拉取（减少 API 调用）

**验收**: 传入 `company_code=600519` → `raw_data.financial_metrics` 包含营收/净利润等字段

### 3.2 实现 PDF 解析（辅助功能）

📁 `backend/agents/data_collector/pdf_parser.py`

- [ ] 实现 `async def parse_pdf(file_path: str) -> dict`
- [ ] 使用 PyMuPDF 提取文本，pdfplumber 提取表格
- [ ] 从表格中识别财务指标（行列匹配标题关键词："营业收入""净利润""ROE"等）
- [ ] 返回结构化 dict：`{"text": "...", "tables": [{"title":"...", "rows":[...]}, ...], "metrics": {...}}`
- [ ] 文件路径白名单校验（禁止目录遍历）

**验收**: 传入一份标准财报 PDF → 返回非空 `tables` 和 `metrics`

### 3.3 实现数据写入 MySQL

📁 `backend/agents/data_collector/storage.py`

- [ ] 实现 `async def persist_raw_data(raw_data: dict, company_code: str, db_session) -> None`
- [ ] 调用 Phase 1.5 的 `import_financials_to_db()` 写入 `financial_data` 表
- [ ] PDF 解析结果写入 `documents` 表（含 `vector_id` 字段留空，后续向量化）
- [ ] 使用 SQLAlchemy `async session`，批量 `insert` 时使用 `add_all` + `commit`

**验收**: 持久化后 MySQL 对应表有数据

### 3.4 实现数据收集工具 Schema

📁 `backend/agents/data_collector/tools.py`

- [ ] 定义 `fetch_financials` Function Calling JSON Schema
- [ ] `metrics` 参数为 `enum` 白名单（12 个预定义指标），防止 LLM 编造指标名
- [ ] 包含 3 组 Few-shot 示例（单一指标、复合指标、全量拉取）
- [ ] Schema 包含 `strict: true` 标记

**验收**: JSON Schema 通过 `jsonschema` 库校验

### 3.5 编写数据收集单元测试

📁 `backend/tests/agents/test_data_collector.py`

- [ ] Mock `DataSourceAdapter`，测试节点函数正常流程
- [ ] 测试并行调用中部分失败时 `errors` 正确记录
- [ ] 测试 `simple_query` 意图只拉取相关指标
- [ ] 测试 PDF 解析表格提取准确率（金标测试集 ≥90%）
- [ ] 测试 `fetch_financials` Schema 拒绝不在白名单的指标名

**验收**: `pytest tests/agents/test_data_collector.py` 全部通过

---

## 产出物

- [ ] `backend/agents/data_collector/__init__.py`
- [ ] `backend/agents/data_collector/node.py` — LangGraph 节点
- [ ] `backend/agents/data_collector/pdf_parser.py` — PDF 解析
- [ ] `backend/agents/data_collector/storage.py` — MySQL 写入
- [ ] `backend/agents/data_collector/tools.py` — Function Calling Schema
- [ ] `backend/tests/agents/test_data_collector.py` — 单元测试

*关联文档: [设计规格 §3.2](../superpowers/specs/2026-06-16-financial-agent-mvp-design.md#32-数据收集-agent), [Phase 1](phase-1-data-source.md)*
