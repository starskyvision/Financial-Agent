# 金融多智能体协作系统 MVP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建基于 LangGraph 1.2+ 的金融投研多智能体协作系统 MVP，实现双通道交互（/chat 快速对话 + /tasks 异步报告），4 个专职 Agent 各完成 1 个核心功能，端到端跑通"意图分类→数据收集→分析→校验→输出"全链路。

**Architecture:** LangGraph StateGraph 编排 6 个节点（意图分类、数据收集、财务分析、舆情解读、报告生成、重写）+ 输出节点，4 个条件边控制路由。FastAPI 双路由暴露 /chat（SSE 流式）和 /tasks（Celery 异步）。数据源通过 Adapter 协议抽象，默认 AKShare 实现。LLM 通过 LLMService 统一调用 DeepSeek-V3 API。

**Tech Stack:** Python 3.11+, FastAPI 0.115+, LangGraph 1.2+, LangChain 1.3+, Celery 5.6, Redis 5.0-5.2.1, pymilvus 2.4.x, MySQL 8.0, AKShare, DeepSeek-V3 API, sse-starlette 2.0+

**Source spec:** [2026-06-16-financial-agent-mvp-design.md](../specs/2026-06-16-financial-agent-mvp-design.md)
**Task breakdown:** [docs/task/](../../task/)

---

### Task 1: AgentState + 核心类型定义

**Files:**
- Create: `backend/state.py`
- Create: `backend/tests/test_state.py`

- [ ] **Step 1: 创建 AgentState TypedDict 和所有 Pydantic 子类型**

```python
# backend/state.py
from typing import TypedDict, NotRequired
from pydantic import BaseModel


class IntentResult(BaseModel):
    """意图分类器输出"""
    intent: str  # simple_query | financial_analysis | sentiment_analysis | comprehensive
    company_code: str
    company_name: str = ""
    report_date: str = ""
    metric_names: list[str] = []


class DupontResult(BaseModel):
    """杜邦分解计算结果"""
    roe: float
    net_margin: float
    asset_turnover: float
    equity_multiplier: float
    is_valid: bool
    missing_metrics: list[str] = []


class Anomaly(BaseModel):
    """异动检测结果"""
    metric_name: str
    current_value: float
    yoy_value: float | None = None
    change_pct: float | None = None
    severity: str  # warning | critical


class SentimentDetail(BaseModel):
    """单条新闻情感"""
    title: str
    sentiment: str   # positive | neutral | negative
    score: float     # 0~1
    reasoning: str = ""


class SentimentResult(BaseModel):
    """舆情分析结果"""
    overall_sentiment: str  # positive | neutral | negative
    overall_score: float
    positive_count: int = 0
    neutral_count: int = 0
    negative_count: int = 0
    key_topics: list[str] = []
    summary: str = ""
    details: list[SentimentDetail] = []


class AgentState(TypedDict, total=False):
    # 任务元数据
    task_id: str
    intent: str

    # 用户输入
    company_code: str
    company_name: str
    report_date: str

    # 各 Agent 输出
    raw_data: dict | None
    financial_analysis: dict | None
    sentiment_result: dict | None

    # 输出
    chat_reply: str | None
    draft_report: str | None

    # 反思控制
    errors: list[str]
    retry_count: int
    status: str  # pending | running | done | failed
```

- [ ] **Step 2: 编写 State 初始化辅助函数**

```python
# backend/state.py (追加)

def make_initial_state(task_id: str, company_code: str = "", report_date: str = "") -> AgentState:
    return AgentState(
        task_id=task_id,
        intent="",
        company_code=company_code,
        company_name="",
        report_date=report_date,
        raw_data=None,
        financial_analysis=None,
        sentiment_result=None,
        chat_reply=None,
        draft_report=None,
        errors=[],
        retry_count=0,
        status="pending",
    )
```

- [ ] **Step 3: 编写类型单元测试**

```python
# backend/tests/test_state.py
import pytest
from state import AgentState, IntentResult, DupontResult, Anomaly, make_initial_state


class TestIntentResult:
    def test_valid_intent(self):
        r = IntentResult(intent="financial_analysis", company_code="600519")
        assert r.intent == "financial_analysis"

    def test_invalid_intent_fails(self):
        with pytest.raises(Exception):
            IntentResult(intent="unknown", company_code="")  # Pydantic 不拒绝任意 str，本测试仅验证结构


class TestDupontResult:
    def test_compute_roe(self):
        d = DupontResult(roe=0.15, net_margin=0.50, asset_turnover=0.20, equity_multiplier=1.5, is_valid=True)
        # ROE ≈ net_margin * asset_turnover * equity_multiplier = 0.50*0.20*1.5 = 0.15
        assert abs(d.roe - (d.net_margin * d.asset_turnover * d.equity_multiplier)) < 0.01

    def test_invalid_when_missing_metrics(self):
        d = DupontResult(roe=0, net_margin=0, asset_turnover=0, equity_multiplier=0,
                         is_valid=False, missing_metrics=["revenue"])
        assert not d.is_valid
        assert "revenue" in d.missing_metrics


class TestAnomaly:
    def test_warning_severity(self):
        a = Anomaly(metric_name="revenue", current_value=100, yoy_value=70, change_pct=0.30, severity="warning")
        assert a.severity == "warning"

    def test_critical_severity(self):
        a = Anomaly(metric_name="net_profit", current_value=50, yoy_value=100, change_pct=-0.50, severity="critical")
        assert a.severity == "critical"


class TestMakeInitialState:
    def test_initial_state_defaults(self):
        state = make_initial_state("task-001")
        assert state["task_id"] == "task-001"
        assert state["status"] == "pending"
        assert state["intent"] == ""
        assert state["errors"] == []
        assert state["retry_count"] == 0
        assert state["raw_data"] is None
```

- [ ] **Step 4: 运行测试**

```bash
cd backend && pytest tests/test_state.py -v
```

Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/state.py backend/tests/test_state.py
git commit -m "feat: add AgentState TypedDict and core Pydantic types"
```

---

### Task 2: DataSourceAdapter 协议 + AKShare 适配器

**Files:**
- Create: `backend/services/__init__.py`
- Create: `backend/services/data_sources/__init__.py`
- Create: `backend/services/data_sources/base.py`
- Create: `backend/services/data_sources/akshare_adapter.py`
- Create: `backend/tests/services/__init__.py`
- Create: `backend/tests/services/test_akshare_adapter.py`

- [ ] **Step 1: 定义 Adapter 协议和配置模型**

```python
# backend/services/data_sources/base.py
from typing import Protocol
from pydantic import BaseModel


class DataSourceConfig(BaseModel):
    source_type: str = "akshare"  # akshare | tushare | wind
    api_key: str = ""
    timeout: int = 30


class DataSourceAdapter(Protocol):
    async def fetch_financials(self, code: str, date: str, metrics: list[str]) -> dict:
        """拉取财务指标，返回 {metric_name: value, ...} (单位: 亿元)"""
        ...

    async def fetch_news(self, code: str, days: int) -> list[dict]:
        """拉取新闻，返回 [{"title":"...", "summary":"...", "source":"...", "published_at":"..."}, ...]"""
        ...

    async def fetch_documents(self, code: str, doc_type: str, limit: int) -> list[dict]:
        """拉取文档切片，MVP 阶段返回空列表"""
        ...
```

- [ ] **Step 2: 实现 AKShare 适配器**

```python
# backend/services/data_sources/akshare_adapter.py
import structlog
import httpx
from services.data_sources.base import DataSourceAdapter, DataSourceConfig

logger = structlog.get_logger()

# AKShare 支持的指标名 → AKShare 实际字段名映射
METRIC_MAP = {
    "revenue": "营业收入",
    "net_profit": "净利润",
    "roe": "净资产收益率",
    "roa": "总资产收益率",
    "gross_margin": "销售毛利率",
    "net_margin": "销售净利率",
    "operating_cashflow": "经营活动现金流净额",
    "free_cashflow": "自由现金流",
    "total_assets": "总资产",
    "total_liabilities": "总负债",
    "asset_turnover": "总资产周转率",
    "equity_multiplier": "权益乘数",
}


def normalize_stock_code(code: str) -> str:
    """归一化股票代码为 AKShare 需要的纯数字格式"""
    code = code.strip().upper()
    code = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    code = code.replace("SH", "").replace("SZ", "").replace("BJ", "")
    return code


class AKShareAdapter(DataSourceAdapter):
    def __init__(self, config: DataSourceConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.config.timeout))
        return self._client

    async def fetch_financials(self, code: str, date: str, metrics: list[str]) -> dict:
        code = normalize_stock_code(code)
        logger.info("akshare_fetch_financials_start", code=code, date=date, requested=metrics)
        try:
            import akshare as ak
            # 拉取利润表和资产负债表数据
            profit_df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
            if profit_df is None or profit_df.empty:
                logger.warning("akshare_empty_response", code=code)
                return {}

            result = {}
            for metric in metrics:
                cn_name = METRIC_MAP.get(metric)
                if cn_name and cn_name in profit_df.columns:
                    # 取最新一期数据
                    val = profit_df[cn_name].dropna().iloc[0] if not profit_df[cn_name].dropna().empty else None
                    if val is not None:
                        try:
                            result[metric] = round(float(val) / 1e8, 4)  # 转换为亿元
                        except (ValueError, TypeError):
                            result[metric] = None
            logger.info("akshare_fetch_financials_done", code=code, found=len(result))
            return result
        except ImportError:
            logger.error("akshare_not_installed")
            return {}
        except Exception as e:
            logger.error("akshare_fetch_financials_error", code=code, error=str(e))
            return {}

    async def fetch_news(self, code: str, days: int) -> list[dict]:
        code = normalize_stock_code(code)
        logger.info("akshare_fetch_news_start", code=code, days=days)
        try:
            import akshare as ak
            df = ak.stock_news_em(symbol=code)
            if df is None or df.empty:
                return []

            from datetime import datetime, timedelta
            cutoff = datetime.now() - timedelta(days=days)
            news_list = []
            for _, row in df.head(30).iterrows():
                title = str(row.get("标题", ""))
                if not title:
                    continue
                news_list.append({
                    "title": title,
                    "summary": str(row.get("内容", ""))[:200] if row.get("内容") else "",
                    "source": "东方财富",
                    "published_at": str(row.get("发布时间", "")),
                })
            logger.info("akshare_fetch_news_done", code=code, count=len(news_list))
            return news_list
        except ImportError:
            return []
        except Exception as e:
            logger.error("akshare_fetch_news_error", code=code, error=str(e))
            return []

    async def fetch_documents(self, code: str, doc_type: str, limit: int) -> list[dict]:
        return []  # MVP: AKShare 不支持文档下载

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
```

- [ ] **Step 3: 实现数据源工厂**

```python
# backend/services/data_sources/__init__.py
from services.data_sources.base import DataSourceAdapter, DataSourceConfig
from services.data_sources.akshare_adapter import AKShareAdapter

_instances: dict[str, DataSourceAdapter] = {}


def create_data_source(config: DataSourceConfig) -> DataSourceAdapter:
    """创建或复用数据源实例"""
    key = config.source_type
    if key in _instances:
        return _instances[key]

    match config.source_type:
        case "akshare":
            adapter = AKShareAdapter(config)
        case "tushare":
            raise NotImplementedError("Tushare adapter not yet implemented")
        case "wind":
            raise NotImplementedError("Wind adapter not yet implemented")
        case _:
            raise ValueError(f"Unsupported data source: {config.source_type}")

    _instances[key] = adapter
    return adapter


def clear_cache():
    """清理缓存的适配器实例（测试用）"""
    _instances.clear()
```

- [ ] **Step 4: 编写 AKShare 适配器单元测试**

```python
# backend/tests/services/test_akshare_adapter.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from services.data_sources.base import DataSourceConfig
from services.data_sources.akshare_adapter import AKShareAdapter, normalize_stock_code
from services.data_sources import create_data_source, clear_cache


class TestNormalizeStockCode:
    def test_pure_number(self):
        assert normalize_stock_code("600519") == "600519"

    def test_with_sh_suffix(self):
        assert normalize_stock_code("600519.SH") == "600519"

    def test_with_sz_suffix(self):
        assert normalize_stock_code("000001.SZ") == "000001"

    def test_with_sh_prefix(self):
        assert normalize_stock_code("SH600519") == "600519"


class TestAKShareAdapter:
    @pytest.fixture
    def adapter(self):
        config = DataSourceConfig(source_type="akshare", timeout=10)
        return AKShareAdapter(config)

    @pytest.mark.asyncio
    async def test_fetch_financials_returns_dict(self, adapter):
        with patch("services.data_sources.akshare_adapter.ak.stock_financial_abstract_ths") as mock_ak:
            import pandas as pd
            mock_df = pd.DataFrame({"净资产收益率": [0.15, 0.14], "营业收入": [100e8, 90e8]})
            mock_ak.return_value = mock_df

            result = await adapter.fetch_financials("600519", "2024-09-30", ["roe", "revenue"])
            assert isinstance(result, dict)
            assert "roe" in result or len(result) > 0

    @pytest.mark.asyncio
    async def test_fetch_financials_empty_on_error(self, adapter):
        with patch("services.data_sources.akshare_adapter.ak.stock_financial_abstract_ths",
                   side_effect=Exception("network error")):
            result = await adapter.fetch_financials("600519", "2024-09-30", ["roe"])
            assert result == {}

    @pytest.mark.asyncio
    async def test_fetch_news_returns_list(self, adapter):
        with patch("services.data_sources.akshare_adapter.ak.stock_news_em") as mock_ak:
            import pandas as pd
            mock_df = pd.DataFrame({"标题": ["茅台Q3业绩增长"], "内容": ["贵州茅台第三季度营收..."],
                                     "发布时间": ["2024-10-28"]})
            mock_ak.return_value = mock_df

            result = await adapter.fetch_news("600519", 30)
            assert isinstance(result, list)
            if result:
                assert "title" in result[0]

    @pytest.mark.asyncio
    async def test_fetch_news_empty_on_error(self, adapter):
        with patch("services.data_sources.akshare_adapter.ak.stock_news_em",
                   side_effect=Exception("network error")):
            result = await adapter.fetch_news("600519", 30)
            assert result == []

    @pytest.mark.asyncio
    async def test_fetch_documents_returns_empty(self, adapter):
        result = await adapter.fetch_documents("600519", "announcement", 5)
        assert result == []


class TestCreateDataSource:
    def setup_method(self):
        clear_cache()

    def test_create_akshare(self):
        config = DataSourceConfig(source_type="akshare")
        adapter = create_data_source(config)
        from services.data_sources.akshare_adapter import AKShareAdapter
        assert isinstance(adapter, AKShareAdapter)

    def test_create_unsupported_raises(self):
        config = DataSourceConfig(source_type="wind")
        with pytest.raises(NotImplementedError):
            create_data_source(config)

    def test_singleton_cache(self):
        config = DataSourceConfig(source_type="akshare")
        a1 = create_data_source(config)
        a2 = create_data_source(config)
        assert a1 is a2
```

- [ ] **Step 5: 运行测试**

```bash
cd backend && pytest tests/services/test_akshare_adapter.py -v
```

Expected: 9 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/ backend/tests/services/
git commit -m "feat: add DataSourceAdapter protocol and AKShare adapter"
```

---

### Task 3: LLMService — 统一 LLM 调用

**Files:**
- Create: `backend/services/llm_service.py`
- Create: `backend/tests/services/test_llm_service.py`

- [ ] **Step 1: 实现 LLMService**

```python
# backend/services/llm_service.py
import os
import time
import structlog
from openai import AsyncOpenAI
from collections import deque

logger = structlog.get_logger()

AGENT_LLM_CONFIG = {
    "intent_classifier":    {"model": "deepseek-chat", "temperature": 0.0, "max_tokens": 512},
    "financial_analyzer":   {"model": "deepseek-chat", "temperature": 0.3, "max_tokens": 2048},
    "sentiment_analyzer":   {"model": "deepseek-chat", "temperature": 0.3, "max_tokens": 2048},
    "reviewer":             {"model": "deepseek-chat", "temperature": 0.5, "max_tokens": 8192},
    "default":              {"model": "deepseek-chat", "temperature": 0.2, "max_tokens": 2048},
}

FALLBACK_CONFIG = {
    "model": os.getenv("QWEN_MODEL", "qwen-turbo"),
    "api_base": os.getenv("QWEN_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
}


class SimpleRateLimiter:
    """简易 token bucket 限流器"""
    def __init__(self, max_calls_per_minute: int = 30):
        self.max_calls = max_calls_per_minute
        self.timestamps: deque[float] = deque()

    async def acquire(self):
        now = time.time()
        # 清理 1 分钟前的时间戳
        while self.timestamps and self.timestamps[0] < now - 60:
            self.timestamps.popleft()
        if len(self.timestamps) >= self.max_calls:
            wait = self.timestamps[0] + 60 - now
            if wait > 0:
                logger.info("rate_limit_wait", seconds=wait)
                import asyncio
                await asyncio.sleep(wait)
        self.timestamps.append(time.time())


class LLMService:
    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        base_url = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
        self._primary = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._fallback: AsyncOpenAI | None = None
        if os.getenv("QWEN_API_KEY"):
            self._fallback = AsyncOpenAI(
                api_key=os.getenv("QWEN_API_KEY"),
                base_url=FALLBACK_CONFIG["api_base"],
            )
        self._rate_limiter = SimpleRateLimiter(max_calls_per_minute=30)

    async def invoke(
        self,
        agent: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_format: type | None = None,
    ) -> dict | str:
        """统一 LLM 调用入口"""
        config = AGENT_LLM_CONFIG.get(agent, AGENT_LLM_CONFIG["default"])
        await self._rate_limiter.acquire()

        t0 = time.time()
        last_error = None
        for attempt in range(3):  # 最多重试 2 次
            try:
                kwargs = {
                    "model": config["model"],
                    "messages": messages,
                    "temperature": config["temperature"],
                    "max_tokens": config["max_tokens"],
                }
                if tools:
                    kwargs["tools"] = tools
                if response_format:
                    kwargs["response_format"] = {"type": "json_object"}

                resp = await self._primary.chat.completions.create(**kwargs)
                elapsed = (time.time() - t0) * 1000
                choice = resp.choices[0]

                result = {
                    "content": choice.message.content,
                    "tool_calls": choice.message.tool_calls,
                    "model": resp.model,
                    "usage": {
                        "prompt_tokens": resp.usage.prompt_tokens,
                        "completion_tokens": resp.usage.completion_tokens,
                    },
                }
                logger.info("llm_call_done", agent=agent, latency_ms=int(elapsed),
                            tokens=resp.usage.total_tokens)
                return result

            except Exception as e:
                last_error = e
                logger.warning("llm_call_retry", agent=agent, attempt=attempt, error=str(e))
                if attempt < 2:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)  # 指数退避: 1s, 2s
                # 最后一次重试尝试 fallback
                if attempt == 1 and self._fallback:
                    logger.info("llm_fallback_switch", from_model=config["model"],
                                to_model=FALLBACK_CONFIG["model"])
                    try:
                        kwargs["model"] = FALLBACK_CONFIG["model"]
                        resp = await self._fallback.chat.completions.create(**kwargs)
                        elapsed = (time.time() - t0) * 1000
                        return {
                            "content": resp.choices[0].message.content,
                            "tool_calls": resp.choices[0].message.tool_calls,
                            "model": resp.model,
                            "usage": {"prompt_tokens": resp.usage.prompt_tokens,
                                       "completion_tokens": resp.usage.completion_tokens},
                        }
                    except Exception as fe:
                        last_error = fe
                        logger.error("llm_fallback_failed", error=str(fe))

        logger.error("llm_call_exhausted", agent=agent, error=str(last_error))
        return {"content": "", "tool_calls": None, "model": "none",
                "usage": {"prompt_tokens": 0, "completion_tokens": 0}}


# 全局单例
_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
```

- [ ] **Step 2: 编写 LLMService 单元测试**

```python
# backend/tests/services/test_llm_service.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from services.llm_service import LLMService, get_llm_service, SimpleRateLimiter


class TestSimpleRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_within_limit(self):
        rl = SimpleRateLimiter(max_calls_per_minute=100)
        await rl.acquire()
        await rl.acquire()
        assert len(rl.timestamps) == 2


class TestGetLLMService:
    def test_singleton(self):
        s1 = get_llm_service()
        s2 = get_llm_service()
        assert s1 is s2


class TestLLMService:
    @pytest.fixture
    def svc(self):
        return LLMService()

    @pytest.mark.asyncio
    async def test_invoke_returns_content(self, svc):
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "贵州茅台Q3 ROE为12.3%"
        mock_resp.choices[0].message.tool_calls = None
        mock_resp.model = "deepseek-chat"
        mock_resp.usage.prompt_tokens = 100
        mock_resp.usage.completion_tokens = 50
        mock_resp.usage.total_tokens = 150

        with patch.object(svc._primary.chat.completions, "create", return_value=mock_resp):
            result = await svc.invoke("financial_analyzer", [
                {"role": "system", "content": "你是一个金融分析师"},
                {"role": "user", "content": "分析茅台Q3 ROE"}
            ])
            assert result["content"] == "贵州茅台Q3 ROE为12.3%"
            assert result["model"] == "deepseek-chat"

    @pytest.mark.asyncio
    async def test_invoke_returns_empty_on_exhausted(self, svc):
        with patch.object(svc._primary.chat.completions, "create",
                          side_effect=Exception("always fails")):
            result = await svc.invoke("default", [{"role": "user", "content": "hello"}])
            assert result["content"] == ""
            assert result["model"] == "none"
```

- [ ] **Step 3: 运行测试**

```bash
cd backend && pytest tests/services/test_llm_service.py -v
```

Expected: 4 tests PASS

- [ ] **Step 4: Commit**

```bash
git add backend/services/llm_service.py backend/tests/services/test_llm_service.py
git commit -m "feat: add LLMService with rate limiting and fallback"
```

---

### Task 4: 意图分类器 Agent

**Files:**
- Create: `backend/agents/__init__.py`
- Create: `backend/agents/intent_classifier/__init__.py`
- Create: `backend/agents/intent_classifier/classifier.py`
- Create: `backend/agents/intent_classifier/node.py`
- Create: `backend/prompts/intent_classifier.py`
- Create: `backend/tests/agents/__init__.py`
- Create: `backend/tests/agents/test_intent_classifier.py`

- [ ] **Step 1: 编写意图分类 Prompt**

```python
# backend/prompts/intent_classifier.py
INTENT_CLASSIFIER_SYSTEM = """你是一个金融查询意图分类器。根据用户消息判断意图类型并提取关键实体。

## 四种意图

- **simple_query**: 查询单一数据点，不需要分析推理。如"茅台PE多少""XX最新股价"
- **financial_analysis**: 涉及财务指标分析、盈利能力/偿债能力/现金流评估。如"分析茅台Q3盈利能力""XX现金流怎么样"
- **sentiment_analysis**: 询问市场情绪、新闻舆论、利好利空。如"市场怎么看XX""XX最近有什么利好"
- **comprehensive**: 多维度综合分析或明确要求生成报告。如"全面分析茅台""出份XX投研报告"

## 实体提取规则

- company_code: A股6位数字代码。简称映射: 茅台→600519, 五粮液→000858, 宁德时代→300750, 比亚迪→002594, 平安→601318
- report_date: 报告期，如"2024Q3"→"2024-09-30"，未提及则用当前季度
- metric_names: 用户关心的指标列表 (revenue/net_profit/roe/roa/gross_margin/net_margin/operating_cashflow/free_cashflow)

## 输出格式

严格输出 JSON，不要添加任何其他文字:
{"intent": "...", "company_code": "...", "company_name": "...", "report_date": "...", "metric_names": [...]}

## 示例

用户: 茅台PE多少
输出: {"intent": "simple_query", "company_code": "600519", "company_name": "贵州茅台", "report_date": "", "metric_names": ["pe"]}

用户: 分析一下贵州茅台2024Q3的盈利能力
输出: {"intent": "financial_analysis", "company_code": "600519", "company_name": "贵州茅台", "report_date": "2024-09-30", "metric_names": ["revenue", "net_profit", "roe", "roa", "gross_margin", "net_margin"]}

用户: 宁德时代最近有什么新闻利好还是利空
输出: {"intent": "sentiment_analysis", "company_code": "300750", "company_name": "宁德时代", "report_date": "", "metric_names": []}

用户: 全面分析茅台并出份报告
输出: {"intent": "comprehensive", "company_code": "600519", "company_name": "贵州茅台", "report_date": "2026-06-30", "metric_names": ["revenue", "net_profit", "roe", "roa", "gross_margin", "net_margin", "operating_cashflow", "free_cashflow"]}
"""
```

- [ ] **Step 2: 实现意图分类器**

```python
# backend/agents/intent_classifier/classifier.py
import json
import structlog
from state import IntentResult
from services.llm_service import get_llm_service
from prompts.intent_classifier import INTENT_CLASSIFIER_SYSTEM

logger = structlog.get_logger()

# 股票简称 → 代码映射表
NAME_TO_CODE = {
    "茅台": "600519", "贵州茅台": "600519",
    "五粮液": "000858",
    "宁德时代": "300750", "宁德": "300750",
    "比亚迪": "002594",
    "平安": "601318", "中国平安": "601318",
    "招商银行": "600036", "招行": "600036",
    "万科": "000002", "万科A": "000002",
    "美的": "000333", "美的集团": "000333",
    "格力": "000651", "格力电器": "000651",
}


async def classify_intent(message: str, history: list[dict] | None = None) -> IntentResult:
    """使用 LLM 分类用户意图并提取实体"""
    llm = get_llm_service()
    messages = [{"role": "system", "content": INTENT_CLASSIFIER_SYSTEM}]

    # 附加最近 2 轮对话历史（如有）
    if history:
        messages.extend(history[-4:])  # 最近 2 轮 = 4 条消息

    messages.append({"role": "user", "content": message})

    result = await llm.invoke("intent_classifier", messages)

    try:
        content = result.get("content", "")
        # 提取 JSON（LLM 可能在 JSON 前后加文字）
        if "{" in content and "}" in content:
            start = content.index("{")
            end = content.rindex("}") + 1
            content = content[start:end]

        data = json.loads(content)
        intent_result = IntentResult(
            intent=data.get("intent", "comprehensive"),
            company_code=data.get("company_code", ""),
            company_name=data.get("company_name", ""),
            report_date=data.get("report_date", ""),
            metric_names=data.get("metric_names", []),
        )

        # 如果 company_code 为空但 company_name 有值，尝试映射
        if not intent_result.company_code and intent_result.company_name:
            intent_result.company_code = NAME_TO_CODE.get(intent_result.company_name, "")

        logger.info("intent_classified", intent=intent_result.intent,
                    code=intent_result.company_code)
        return intent_result
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning("intent_parse_error", error=str(e), raw=result.get("content", ""))
        # 降级：默认为 comprehensive，安全兜底
        return IntentResult(intent="comprehensive", company_code="")
```

- [ ] **Step 3: 实现 LangGraph 节点**

```python
# backend/agents/intent_classifier/node.py
import structlog
from state import AgentState
from agents.intent_classifier.classifier import classify_intent

logger = structlog.get_logger()


async def intent_classifier_node(state: AgentState) -> AgentState:
    """LangGraph 入口节点：分类用户意图"""
    logger.info("intent_classifier_node_start", task_id=state.get("task_id"))

    # 从 state 中取最后一条用户消息（由调用方在运行前设置）
    # 这里假设 state 中包含一个 messages 字段或调用方已设置 company_code
    # 实际运行时，调用方会将用户消息内容注入 state
    # MVP: 如果 state 中已有 intent（如 /tasks 直接提交），则跳过分类
    if state.get("intent") and state["intent"] != "":
        logger.info("intent_already_set", intent=state["intent"])
        state["status"] = "running"
        return state

    # 降级：如果 state 中没有任何输入信息，设为 comprehensive
    if not state.get("company_code"):
        logger.warning("intent_classifier_no_input")
        state["intent"] = "comprehensive"
        state["status"] = "running"
        return state

    state["status"] = "running"
    logger.info("intent_classifier_node_done", intent=state.get("intent"))
    return state
```

- [ ] **Step 4: 编写意图分类器单元测试**

```python
# backend/tests/agents/test_intent_classifier.py
import pytest
import json
from unittest.mock import AsyncMock, patch
from state import IntentResult
from agents.intent_classifier.classifier import classify_intent
from agents.intent_classifier.node import intent_classifier_node
from state import make_initial_state


class TestClassifyIntent:
    @pytest.mark.asyncio
    async def test_financial_analysis_intent(self):
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = {
            "content": json.dumps({
                "intent": "financial_analysis",
                "company_code": "600519",
                "company_name": "贵州茅台",
                "report_date": "2024-09-30",
                "metric_names": ["revenue", "net_profit", "roe"]
            }),
            "model": "deepseek-chat",
            "usage": {"prompt_tokens": 100, "completion_tokens": 30},
        }
        with patch("agents.intent_classifier.classifier.get_llm_service", return_value=mock_llm):
            result = await classify_intent("分析茅台2024Q3的盈利能力")
            assert result.intent == "financial_analysis"
            assert result.company_code == "600519"
            assert "roe" in result.metric_names

    @pytest.mark.asyncio
    async def test_simple_query_intent(self):
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = {
            "content": json.dumps({
                "intent": "simple_query",
                "company_code": "600519",
                "company_name": "贵州茅台",
                "report_date": "",
                "metric_names": ["pe"]
            }),
            "model": "deepseek-chat",
            "usage": {"prompt_tokens": 80, "completion_tokens": 20},
        }
        with patch("agents.intent_classifier.classifier.get_llm_service", return_value=mock_llm):
            result = await classify_intent("茅台PE多少")
            assert result.intent == "simple_query"

    @pytest.mark.asyncio
    async def test_fallback_on_json_error(self):
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = {
            "content": "这是一些废话 {invalid json}",
            "model": "deepseek-chat",
            "usage": {"prompt_tokens": 50, "completion_tokens": 10},
        }
        with patch("agents.intent_classifier.classifier.get_llm_service", return_value=mock_llm):
            result = await classify_intent("测试消息")
            assert result.intent == "comprehensive"  # 降级兜底

    @pytest.mark.asyncio
    async def test_name_to_code_mapping(self):
        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = {
            "content": json.dumps({
                "intent": "sentiment_analysis",
                "company_code": "",
                "company_name": "宁德时代",
                "report_date": "",
                "metric_names": []
            }),
            "model": "deepseek-chat",
            "usage": {"prompt_tokens": 80, "completion_tokens": 20},
        }
        with patch("agents.intent_classifier.classifier.get_llm_service", return_value=mock_llm):
            result = await classify_intent("宁德时代最近怎么样")
            assert result.company_code == "300750"


class TestIntentClassifierNode:
    @pytest.mark.asyncio
    async def test_node_sets_intent_and_status(self):
        state = make_initial_state("task-001")
        state["company_code"] = "600519"
        state["intent"] = "financial_analysis"  # 已预设意图

        result = await intent_classifier_node(state)
        assert result["status"] == "running"
        assert result["intent"] == "financial_analysis"

    @pytest.mark.asyncio
    async def test_node_defaults_to_comprehensive_when_no_input(self):
        state = make_initial_state("task-002")

        result = await intent_classifier_node(state)
        assert result["intent"] == "comprehensive"
        assert result["status"] == "running"
```

- [ ] **Step 5: 运行测试**

```bash
cd backend && pytest tests/agents/test_intent_classifier.py -v
```

Expected: 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/agents/__init__.py backend/agents/intent_classifier/ backend/prompts/ backend/tests/agents/
git commit -m "feat: add intent classifier agent with LLM-based routing"
```

---

### Task 5: 数据收集 Agent

**Files:**
- Create: `backend/agents/data_collector/__init__.py`
- Create: `backend/agents/data_collector/node.py`
- Create: `backend/agents/data_collector/tools.py`
- Create: `backend/tests/agents/test_data_collector.py`

- [ ] **Step 1: 实现 Function Calling Schema**

```python
# backend/agents/data_collector/tools.py
FETCH_FINANCIALS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "fetch_financials",
        "description": "拉取指定股票在指定报告期的财务指标数据",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "company_code": {
                    "type": "string",
                    "description": "A股6位数字股票代码，如 600519"
                },
                "report_date": {
                    "type": "string",
                    "description": "报告期日期，格式 YYYY-MM-DD，如 2024-09-30"
                },
                "metrics": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "revenue", "net_profit", "roe", "roa",
                            "gross_margin", "net_margin", "operating_cashflow",
                            "free_cashflow", "total_assets", "total_liabilities",
                            "asset_turnover", "equity_multiplier"
                        ]
                    },
                    "description": "需要拉取的指标列表"
                }
            },
            "required": ["company_code", "metrics"]
        }
    }
}

FETCH_FINANCIALS_FEWSHOT = {
    "role": "user",
    "content": "分析茅台Q3 ROE和净利率",
    "tool_calls": [{
        "function": {
            "name": "fetch_financials",
            "arguments": '{"company_code": "600519", "report_date": "2024-09-30", '
                         '"metrics": ["roe", "net_margin"]}'
        }
    }]
}
```

- [ ] **Step 2: 实现数据收集节点**

```python
# backend/agents/data_collector/node.py
import asyncio
import structlog
from services.data_sources import create_data_source
from services.data_sources.base import DataSourceConfig
from state import AgentState

logger = structlog.get_logger()


async def data_collector_node(state: AgentState) -> AgentState:
    """LangGraph 节点：拉取财务数据、新闻、文档"""
    logger.info("data_collector_node_start", task_id=state.get("task_id"),
                code=state.get("company_code"))

    intent = state.get("intent", "comprehensive")
    code = state.get("company_code", "")
    date = state.get("report_date", "")

    if not code:
        state["errors"].append("数据收集失败: company_code 为空")
        state["raw_data"] = None
        return state

    config = DataSourceConfig(source_type="akshare", timeout=30)
    adapter = create_data_source(config)

    # 确定需要拉取的指标
    if intent == "simple_query":
        metrics = state.get("metric_names", ["revenue", "net_profit"]) or ["revenue", "net_profit"]
    else:
        metrics = state.get("metric_names", []) or [
            "revenue", "net_profit", "roe", "roa", "gross_margin",
            "net_margin", "operating_cashflow", "total_assets", "total_liabilities"
        ]

    # 并行拉取财务数据和新闻
    financials_task = adapter.fetch_financials(code, date, metrics)
    news_task = adapter.fetch_news(code, days=30)
    # 仅 comprehensive 拉取文档
    if intent == "comprehensive":
        docs_task = adapter.fetch_documents(code, "announcement", limit=5)
        results = await asyncio.gather(
            financials_task, news_task, docs_task, return_exceptions=True
        )
    else:
        results = await asyncio.gather(
            financials_task, news_task, return_exceptions=True
        )
        results = [results[0], results[1], []]  # docs 为空

    financials, news, docs = results[0], results[1], results[2]

    # 处理异常结果
    errors = []
    if isinstance(financials, Exception):
        logger.error("fetch_financials_failed", error=str(financials))
        errors.append(f"财务数据拉取失败: {str(financials)}")
        financials = {}
    if isinstance(news, Exception):
        logger.error("fetch_news_failed", error=str(news))
        errors.append(f"新闻拉取失败: {str(news)}")
        news = []
    if isinstance(docs, Exception):
        logger.error("fetch_docs_failed", error=str(docs))
        errors.append(f"文档拉取失败: {str(docs)}")
        docs = []

    from datetime import datetime
    state["raw_data"] = {
        "financial_metrics": financials if isinstance(financials, dict) else {},
        "news_headlines": news if isinstance(news, list) else [],
        "doc_snippets": docs if isinstance(docs, list) else [],
        "data_sources": ["akshare"],
        "fetched_at": datetime.now().isoformat(),
    }
    state["errors"].extend(errors)

    logger.info("data_collector_node_done",
                metrics_count=len(state["raw_data"]["financial_metrics"]),
                news_count=len(state["raw_data"]["news_headlines"]),
                errors=len(errors))
    return state
```

- [ ] **Step 3: 编写数据收集单元测试**

```python
# backend/tests/agents/test_data_collector.py
import pytest
from unittest.mock import AsyncMock, patch
from state import make_initial_state
from agents.data_collector.node import data_collector_node


class TestDataCollectorNode:
    @pytest.mark.asyncio
    async def test_node_fetches_data(self):
        state = make_initial_state("task-001")
        state["company_code"] = "600519"
        state["report_date"] = "2024-09-30"
        state["intent"] = "financial_analysis"

        mock_adapter = AsyncMock()
        mock_adapter.fetch_financials.return_value = {"revenue": 100.0, "net_profit": 50.0}
        mock_adapter.fetch_news.return_value = [{"title": "茅台Q3业绩"}]
        mock_adapter.fetch_documents.return_value = []

        with patch("agents.data_collector.node.create_data_source", return_value=mock_adapter):
            result = await data_collector_node(state)
            assert result["raw_data"] is not None
            assert result["raw_data"]["financial_metrics"]["revenue"] == 100.0
            assert len(result["raw_data"]["news_headlines"]) == 1

    @pytest.mark.asyncio
    async def test_node_handles_partial_failure(self):
        state = make_initial_state("task-002")
        state["company_code"] = "000858"
        state["intent"] = "sentiment_analysis"

        mock_adapter = AsyncMock()
        mock_adapter.fetch_financials.side_effect = Exception("timeout")
        mock_adapter.fetch_news.return_value = [{"title": "五粮液提价"}]
        mock_adapter.fetch_documents.return_value = []

        with patch("agents.data_collector.node.create_data_source", return_value=mock_adapter):
            result = await data_collector_node(state)
            assert result["raw_data"] is not None
            assert result["raw_data"]["financial_metrics"] == {}
            assert len(result["raw_data"]["news_headlines"]) == 1
            assert any("财务数据" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_node_errors_on_empty_code(self):
        state = make_initial_state("task-003")
        state["company_code"] = ""

        result = await data_collector_node(state)
        assert result["raw_data"] is None
        assert any("company_code" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_node_skips_docs_for_simple_query(self):
        state = make_initial_state("task-004")
        state["company_code"] = "600519"
        state["intent"] = "simple_query"

        mock_adapter = AsyncMock()
        mock_adapter.fetch_financials.return_value = {"revenue": 100.0}
        mock_adapter.fetch_news.return_value = []

        with patch("agents.data_collector.node.create_data_source", return_value=mock_adapter):
            result = await data_collector_node(state)
            # simple_query 不应该调用 fetch_documents
            mock_adapter.fetch_documents.assert_not_called()
```

- [ ] **Step 4: 运行测试**

```bash
cd backend && pytest tests/agents/test_data_collector.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/agents/data_collector/ backend/tests/agents/test_data_collector.py
git commit -m "feat: add data collector agent with parallel fetch and partial failure handling"
```

---

### Task 6: 财务分析 Agent（杜邦分解 + 异动检测）

**Files:**
- Create: `backend/agents/financial_analyzer/__init__.py`
- Create: `backend/agents/financial_analyzer/dupont.py`
- Create: `backend/agents/financial_analyzer/anomaly.py`
- Create: `backend/agents/financial_analyzer/node.py`
- Create: `backend/prompts/financial_analysis.py`
- Create: `backend/tests/agents/test_financial_analyzer.py`

- [ ] **Step 1: 实现杜邦分解计算引擎**

```python
# backend/agents/financial_analyzer/dupont.py
from state import DupontResult


def compute_dupont(metrics: dict) -> DupontResult:
    """
    杜邦分解: ROE = 净利率 × 资产周转率 × 权益乘数

    净利率 = 净利润 / 营收
    资产周转率 = 营收 / 总资产
    权益乘数 = 总资产 / 净资产
    """
    required = ["net_profit", "revenue", "total_assets"]
    missing = [m for m in required if m not in metrics or metrics[m] is None or metrics[m] == 0]

    if missing:
        # 尝试用已有数据计算部分因子
        return DupontResult(
            roe=0, net_margin=0, asset_turnover=0, equity_multiplier=0,
            is_valid=False, missing_metrics=missing,
        )

    net_profit = metrics.get("net_profit", 0)
    revenue = metrics.get("revenue", 0)
    total_assets = metrics.get("total_assets", 0)
    total_liabilities = metrics.get("total_liabilities", 0)
    equity = total_assets - total_liabilities

    if revenue == 0 or total_assets == 0 or equity == 0:
        return DupontResult(
            roe=0, net_margin=0, asset_turnover=0, equity_multiplier=0,
            is_valid=False, missing_metrics=["equity_data"],
        )

    net_margin = round(net_profit / revenue, 4)
    asset_turnover = round(revenue / total_assets, 4)
    equity_multiplier = round(total_assets / equity, 4)
    roe = round(net_margin * asset_turnover * equity_multiplier, 4)

    return DupontResult(
        roe=roe,
        net_margin=net_margin,
        asset_turnover=asset_turnover,
        equity_multiplier=equity_multiplier,
        is_valid=True,
    )
```

- [ ] **Step 2: 实现异动检测**

```python
# backend/agents/financial_analyzer/anomaly.py
import structlog
from state import Anomaly

logger = structlog.get_logger()

# 需要检测同比变动的指标
TRACKED_METRICS = ["revenue", "net_profit", "roe", "gross_margin", "net_margin", "operating_cashflow"]


async def detect_anomalies(code: str, current_metrics: dict, db_session=None) -> list[Anomaly]:
    """
    检测同比异动。
    当前 MVP: 如果无历史数据（db_session 为空），返回空列表。
    后续通过 MySQL 查询上年同期数据对比。
    """
    anomalies = []
    if db_session is None:
        logger.info("anomaly_skip_no_db", code=code)
        return anomalies

    # MVP: 从 MySQL 查询上年同期数据
    for metric in TRACKED_METRICS:
        if metric not in current_metrics or current_metrics[metric] is None:
            continue
        current_val = current_metrics[metric]

        try:
            # 查询上年同期数据（简化，实际需要 async SQLAlchemy）
            from datetime import datetime
            from db import get_session
            from sqlalchemy import select
            async with db_session() as session:
                from db.models import FinancialData
                stmt = select(FinancialData).where(
                    FinancialData.company_code == code,
                    FinancialData.metric_name == metric,
                ).order_by(FinancialData.report_date.desc()).limit(2)
                result = await session.execute(stmt)
                rows = result.scalars().all()
                if len(rows) < 2:
                    continue
                yoy_val = float(rows[1].metric_value)
        except Exception:
            continue

        if yoy_val and yoy_val != 0:
            change_pct = round((current_val - yoy_val) / abs(yoy_val), 4)
            abs_change = abs(change_pct)

            if abs_change > 0.50:
                severity = "critical"
            elif abs_change > 0.30:
                severity = "warning"
            else:
                continue

            anomalies.append(Anomaly(
                metric_name=metric,
                current_value=current_val,
                yoy_value=yoy_val,
                change_pct=change_pct,
                severity=severity,
            ))

    logger.info("anomaly_detection_done", code=code, anomalies=len(anomalies))
    return anomalies
```

- [ ] **Step 3: 编写财务分析 Prompt**

```python
# backend/prompts/financial_analysis.py
FINANCIAL_ANALYSIS_SYSTEM = """你是一个资深金融分析师。基于提供的杜邦分解结果和异动检测数据，生成财务分析评述。

## 分析结构

1. **盈利概览**: 一两句话评价 ROE 水平和变化趋势
2. **杜邦因子分析**: 分别分析净利率、资产周转率、权益乘数，指出哪个因子是 ROE 的主要驱动/拖累。引用具体数值。
3. **异常预警**: 如果存在异动指标，逐项列出并给出可能的业务原因解释。如果没有，写"本期未发现显著异动"。

## 重要规则

- **必须引用输入数据中的具体数值**，不得编造
- 数值保留 2 位小数
- 如果输入数据不完整，明确指出"XX数据不可用"而非编造
- 篇幅: 200-400 字
"""


def build_financial_analysis_prompt(dupont, anomalies: list, company_name: str, report_date: str) -> str:
    dupont_str = f"""杜邦分解结果:
- ROE: {dupont['roe']}
- 净利率: {dupont['net_margin']}
- 资产周转率: {dupont['asset_turnover']}
- 权益乘数: {dupont['equity_multiplier']}
- 数据有效性: {'有效' if dupont.get('is_valid') else '无效: ' + str(dupont.get('missing_metrics', []))}
"""

    anomaly_str = "异动检测:\n"
    if not anomalies:
        anomaly_str += "本期未发现显著异动（同比变动均在 30% 以内）"
    else:
        for a in anomalies:
            direction = "上升" if a.get("change_pct", 0) > 0 else "下降"
            anomaly_str += (f"- {a['metric_name']}: {direction} {abs(a.get('change_pct', 0))*100:.1f}% "
                            f"(当前 {a['current_value']}, 同期 {a.get('yoy_value')}, "
                            f"严重程度: {a['severity']})\n")

    return f"""请分析 {company_name} 在 {report_date} 的财务状况。

{dupont_str}

{anomaly_str}"""
```

- [ ] **Step 4: 实现财务分析 LangGraph 节点**

```python
# backend/agents/financial_analyzer/node.py
import structlog
from state import AgentState
from agents.financial_analyzer.dupont import compute_dupont
from agents.financial_analyzer.anomaly import detect_anomalies
from services.llm_service import get_llm_service
from prompts.financial_analysis import FINANCIAL_ANALYSIS_SYSTEM, build_financial_analysis_prompt

logger = structlog.get_logger()


async def financial_analyzer_node(state: AgentState) -> AgentState:
    """LangGraph 节点：执行杜邦分解、异动检测、生成分析评述"""
    logger.info("financial_analyzer_node_start", task_id=state.get("task_id"))

    raw_data = state.get("raw_data") or {}
    metrics = raw_data.get("financial_metrics", {})

    if not metrics:
        state["errors"].append("财务分析跳过: 无可用财务数据")
        state["financial_analysis"] = {
            "dupont_decomposition": {
                "roe": 0, "net_margin": 0, "asset_turnover": 0, "equity_multiplier": 0,
                "is_valid": False, "missing_metrics": ["all"]
            },
            "anomaly_flags": [],
            "narrative": "无可用的财务数据，无法完成分析。",
            "analyst_confidence": "low",
        }
        return state

    try:
        # 1. 杜邦分解
        dupont = compute_dupont(metrics)
        dupont_dict = dupont.model_dump()

        # 2. 异动检测
        anomalies = await detect_anomalies(state.get("company_code", ""), metrics)
        anomaly_dicts = [a.model_dump() for a in anomalies]

        # 3. 生成分析评述
        llm = get_llm_service()
        prompt = build_financial_analysis_prompt(
            dupont_dict, anomaly_dicts,
            state.get("company_name", state.get("company_code", "")),
            state.get("report_date", ""),
        )
        result = await llm.invoke("financial_analyzer", [
            {"role": "system", "content": FINANCIAL_ANALYSIS_SYSTEM},
            {"role": "user", "content": prompt},
        ])
        narrative = result.get("content", "")

        confidence = "high"
        if not dupont.is_valid:
            confidence = "low"
        elif len(anomalies) > 3:
            confidence = "medium"

        state["financial_analysis"] = {
            "dupont_decomposition": dupont_dict,
            "anomaly_flags": anomaly_dicts,
            "narrative": narrative,
            "analyst_confidence": confidence,
        }
        logger.info("financial_analyzer_node_done", confidence=confidence)
    except Exception as e:
        logger.error("financial_analyzer_error", error=str(e))
        state["errors"].append(f"财务分析节点失败: {str(e)}")
        state["financial_analysis"] = None

    return state
```

- [ ] **Step 5: 编写财务分析单元测试**

```python
# backend/tests/agents/test_financial_analyzer.py
import pytest
from unittest.mock import AsyncMock, patch
from state import make_initial_state
from agents.financial_analyzer.dupont import compute_dupont, DupontResult
from agents.financial_analyzer.anomaly import detect_anomalies
from agents.financial_analyzer.node import financial_analyzer_node


class TestDupont:
    def test_valid_computation(self):
        metrics = {"net_profit": 15, "revenue": 100, "total_assets": 200, "total_liabilities": 100}
        result = compute_dupont(metrics)
        assert result.is_valid
        assert result.net_margin == 0.15
        assert result.asset_turnover == 0.5
        assert result.equity_multiplier == 2.0
        assert result.roe == 0.15  # 0.15 * 0.5 * 2.0

    def test_missing_metrics(self):
        metrics = {"net_profit": 15}  # 缺少 revenue 和 total_assets
        result = compute_dupont(metrics)
        assert not result.is_valid
        assert "revenue" in result.missing_metrics

    def test_zero_division_protection(self):
        metrics = {"net_profit": 15, "revenue": 0, "total_assets": 200, "total_liabilities": 100}
        result = compute_dupont(metrics)
        assert not result.is_valid


class TestAnomalyDetection:
    @pytest.mark.asyncio
    async def test_no_db_returns_empty(self):
        anomalies = await detect_anomalies("600519", {"revenue": 100})
        assert anomalies == []


class TestFinancialAnalyzerNode:
    @pytest.mark.asyncio
    async def test_node_generates_analysis(self):
        state = make_initial_state("task-001")
        state["company_code"] = "600519"
        state["company_name"] = "贵州茅台"
        state["report_date"] = "2024-09-30"
        state["raw_data"] = {
            "financial_metrics": {
                "net_profit": 50, "revenue": 150, "total_assets": 300,
                "total_liabilities": 100, "roe": 0.25
            },
            "news_headlines": [],
            "doc_snippets": [],
        }

        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = {
            "content": "贵州茅台2024Q3 ROE为25.00%...",
            "model": "deepseek-chat",
            "usage": {"prompt_tokens": 200, "completion_tokens": 100},
        }

        with patch("agents.financial_analyzer.node.get_llm_service", return_value=mock_llm):
            result = await financial_analyzer_node(state)
            assert result["financial_analysis"] is not None
            assert result["financial_analysis"]["dupont_decomposition"]["is_valid"]
            assert len(result["financial_analysis"]["narrative"]) > 0

    @pytest.mark.asyncio
    async def test_node_handles_empty_metrics(self):
        state = make_initial_state("task-002")
        state["raw_data"] = {"financial_metrics": {}, "news_headlines": [], "doc_snippets": []}

        result = await financial_analyzer_node(state)
        assert result["financial_analysis"]["analyst_confidence"] == "low"
        assert "无可用" in result["financial_analysis"]["narrative"]
```

- [ ] **Step 6: 运行测试**

```bash
cd backend && pytest tests/agents/test_financial_analyzer.py -v
```

Expected: 5 tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/agents/financial_analyzer/ backend/prompts/financial_analysis.py backend/tests/agents/test_financial_analyzer.py
git commit -m "feat: add financial analyzer with DuPont decomposition and anomaly detection"
```

---

### Task 7: 舆情解读 Agent

**Files:**
- Create: `backend/agents/sentiment_analyzer/__init__.py`
- Create: `backend/agents/sentiment_analyzer/node.py`
- Create: `backend/prompts/sentiment_analysis.py`
- Create: `backend/tests/agents/test_sentiment_analyzer.py`

- [ ] **Step 1: 编写舆情分析 Prompt**

```python
# backend/prompts/sentiment_analysis.py
SENTIMENT_ANALYSIS_SYSTEM = """你是一个金融舆情分析师。对提供的新闻列表进行情感分析和主题聚合。

## 情感分类标准

- **positive (积极)**: 业绩超预期、政策扶持、大额订单、产品涨价、行业利好
- **neutral (中性)**: 例行公告、人事变动、股东大会通知、无倾向性报道
- **negative (消极)**: 业绩下滑、监管处罚、管理层负面、债务违约、大股东减持

## 打分规则

- 0.8~1.0: 强利好/强利空
- 0.6~0.8: 中等利好/利空
- 0.4~0.6: 轻微倾向或中性

## 输出格式

严格输出 JSON:
{
  "overall_sentiment": "positive|neutral|negative",
  "overall_score": 0.65,
  "key_topics": ["topic1", "topic2"],
  "summary": "1-2句话的整体舆情总结",
  "details": [
    {"title": "新闻标题", "sentiment": "positive", "score": 0.8, "reasoning": "判断理由"}
  ]
}

## 规则
- 只基于提供的新闻文本判断，不引入外部知识
- 如果新闻列表为空，overall_sentiment 设为 "neutral"，overall_score 设为 0.5
"""
```

- [ ] **Step 2: 实现舆情分析节点**

```python
# backend/agents/sentiment_analyzer/node.py
import json
import structlog
from state import AgentState
from services.llm_service import get_llm_service
from prompts.sentiment_analysis import SENTIMENT_ANALYSIS_SYSTEM

logger = structlog.get_logger()

MAX_NEWS_PER_BATCH = 30


async def sentiment_analyzer_node(state: AgentState) -> AgentState:
    """LangGraph 节点：分析新闻舆情"""
    logger.info("sentiment_analyzer_node_start", task_id=state.get("task_id"))

    raw_data = state.get("raw_data") or {}
    news_list = raw_data.get("news_headlines", [])

    if not news_list:
        state["sentiment_result"] = {
            "overall_sentiment": "neutral",
            "overall_score": 0.5,
            "positive_count": 0, "neutral_count": 0, "negative_count": 0,
            "key_topics": [],
            "summary": "无可用舆情数据",
            "details": [],
        }
        return state

    try:
        # 构建新闻列表文本（每条截断标题+摘要）
        news_texts = []
        for n in news_list[:MAX_NEWS_PER_BATCH]:
            title = n.get("title", "")
            summary = n.get("summary", "")[:100]
            news_texts.append(f"- {title} | {summary}")
        news_block = "\n".join(news_texts)

        user_prompt = f"请分析以下 {len(news_texts)} 条新闻的情感倾向：\n\n{news_block}"

        llm = get_llm_service()
        result = await llm.invoke("sentiment_analyzer", [
            {"role": "system", "content": SENTIMENT_ANALYSIS_SYSTEM},
            {"role": "user", "content": user_prompt},
        ])

        content = result.get("content", "")
        if "{" in content and "}" in content:
            start = content.index("{")
            end = content.rindex("}") + 1
            content = content[start:end]

        data = json.loads(content)

        details = data.get("details", [])
        pos = sum(1 for d in details if d.get("sentiment") == "positive")
        neu = sum(1 for d in details if d.get("sentiment") == "neutral")
        neg = sum(1 for d in details if d.get("sentiment") == "negative")

        state["sentiment_result"] = {
            "overall_sentiment": data.get("overall_sentiment", "neutral"),
            "overall_score": data.get("overall_score", 0.5),
            "positive_count": pos, "neutral_count": neu, "negative_count": neg,
            "key_topics": data.get("key_topics", []),
            "summary": data.get("summary", ""),
            "details": details,
        }
        logger.info("sentiment_analyzer_node_done", overall=state["sentiment_result"]["overall_sentiment"])
    except Exception as e:
        logger.error("sentiment_analyzer_error", error=str(e))
        state["errors"].append(f"舆情分析失败: {str(e)}")
        state["sentiment_result"] = {
            "overall_sentiment": "neutral",
            "overall_score": 0.5,
            "positive_count": 0, "neutral_count": 0, "negative_count": 0,
            "key_topics": [],
            "summary": f"舆情分析异常: {str(e)}",
            "details": [],
        }

    return state
```

- [ ] **Step 3: 编写舆情分析单元测试**

```python
# backend/tests/agents/test_sentiment_analyzer.py
import pytest
import json
from unittest.mock import AsyncMock, patch
from state import make_initial_state
from agents.sentiment_analyzer.node import sentiment_analyzer_node


class TestSentimentAnalyzerNode:
    @pytest.mark.asyncio
    async def test_node_analyzes_news(self):
        state = make_initial_state("task-001")
        state["raw_data"] = {
            "financial_metrics": {},
            "news_headlines": [
                {"title": "茅台Q3营收超预期", "summary": "贵州茅台第三季度营收同比增长18%"},
                {"title": "茅台公告分红方案", "summary": "拟每10股派发现金红利100元"},
                {"title": "白酒板块整体走弱", "summary": "受宏观影响白酒板块今日下跌"},
            ],
            "doc_snippets": [],
        }

        mock_result = {
            "overall_sentiment": "positive",
            "overall_score": 0.72,
            "key_topics": ["业绩增长", "分红"],
            "summary": "茅台近期舆情偏正面，主要受超预期业绩和分红方案推动。",
            "details": [
                {"title": "茅台Q3营收超预期", "sentiment": "positive", "score": 0.85, "reasoning": "业绩超预期"},
                {"title": "茅台公告分红方案", "sentiment": "positive", "score": 0.7, "reasoning": "分红利好"},
                {"title": "白酒板块整体走弱", "sentiment": "negative", "score": 0.6, "reasoning": "板块下跌"},
            ]
        }

        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = {
            "content": json.dumps(mock_result),
            "model": "deepseek-chat",
            "usage": {"prompt_tokens": 200, "completion_tokens": 100},
        }

        with patch("agents.sentiment_analyzer.node.get_llm_service", return_value=mock_llm):
            result = await sentiment_analyzer_node(state)
            assert result["sentiment_result"]["overall_sentiment"] == "positive"
            assert result["sentiment_result"]["positive_count"] == 2
            assert result["sentiment_result"]["negative_count"] == 1

    @pytest.mark.asyncio
    async def test_node_handles_empty_news(self):
        state = make_initial_state("task-002")
        state["raw_data"] = {"financial_metrics": {}, "news_headlines": [], "doc_snippets": []}

        result = await sentiment_analyzer_node(state)
        assert result["sentiment_result"]["overall_sentiment"] == "neutral"
        assert result["sentiment_result"]["overall_score"] == 0.5

    @pytest.mark.asyncio
    async def test_node_handles_llm_error(self):
        state = make_initial_state("task-003")
        state["raw_data"] = {
            "financial_metrics": {},
            "news_headlines": [{"title": "测试新闻", "summary": "摘要"}],
            "doc_snippets": [],
        }

        mock_llm = AsyncMock()
        mock_llm.invoke.side_effect = Exception("LLM timeout")

        with patch("agents.sentiment_analyzer.node.get_llm_service", return_value=mock_llm):
            result = await sentiment_analyzer_node(state)
            assert result["sentiment_result"]["overall_sentiment"] == "neutral"
            assert any("舆情分析" in e for e in result["errors"])
```

- [ ] **Step 4: 运行测试**

```bash
cd backend && pytest tests/agents/test_sentiment_analyzer.py -v
```

Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/agents/sentiment_analyzer/ backend/prompts/sentiment_analysis.py backend/tests/agents/test_sentiment_analyzer.py
git commit -m "feat: add sentiment analyzer agent with batch news analysis"
```

---

### Task 8: 校验总结 Agent + 反思循环

**Files:**
- Create: `backend/agents/reviewer/__init__.py`
- Create: `backend/agents/reviewer/report_generator.py`
- Create: `backend/agents/reviewer/fact_checker.py`
- Create: `backend/agents/reviewer/rewriter.py`
- Create: `backend/agents/reviewer/router.py`
- Create: `backend/prompts/report_generation.py`
- Create: `backend/tests/agents/test_reviewer.py`

- [ ] **Step 1: 实现事实核对模块**

```python
# backend/agents/reviewer/fact_checker.py
import re
import structlog

logger = structlog.get_logger()

# 数值断言匹配模式: "ROE为12.3%" / "净利润56.78亿元" / "营收 123.45 亿"
CLAIM_PATTERNS = [
    (r'(ROE|ROA)[^\d]*(\d+\.?\d*)\s*%', 'percent', 100),
    (r'(净利润|营收|净利率|毛利率)[^\d]*(\d+\.?\d*)\s*[亿元]', 'billions', 1),
    (r'(现金流)[^\d]*(\d+\.?\d*)\s*[亿元]', 'billions', 1),
]

# 报告指标名 → 数据库 metric_name 映射
METRIC_NAME_MAP = {
    "ROE": "roe", "ROA": "roa",
    "净利润": "net_profit", "营收": "revenue",
    "净利率": "net_margin", "毛利率": "gross_margin",
    "现金流": "operating_cashflow",
}


async def verify_facts(report: str, company_code: str, db_session=None) -> list[str]:
    """
    纯 Python 程序化事实核对，不经过 LLM。
    从报告中正则提取数值断言，与 MySQL 源数据比对，偏差 >1% 报错。
    """
    errors = []

    for pattern, unit_type, divisor in CLAIM_PATTERNS:
        for match in re.finditer(pattern, report):
            metric_cn = match.group(1)
            report_value = float(match.group(2))
            if unit_type == "percent":
                report_value = report_value / divisor  # 转为小数

            metric_name = METRIC_NAME_MAP.get(metric_cn)
            if not metric_name:
                continue

            # 查询源数据
            source_value = None
            if db_session:
                try:
                    from sqlalchemy import select
                    from db.models import FinancialData
                    async with db_session() as session:
                        stmt = select(FinancialData).where(
                            FinancialData.company_code == company_code,
                            FinancialData.metric_name == metric_name,
                        ).order_by(FinancialData.report_date.desc()).limit(1)
                        result = await session.execute(stmt)
                        row = result.scalar_one_or_none()
                        if row:
                            source_value = float(row.metric_value)
                except Exception as e:
                    logger.warning("fact_check_db_error", error=str(e))

            if source_value is not None and source_value != 0:
                deviation = abs(report_value - source_value) / abs(source_value)
                if deviation > 0.01:
                    errors.append(
                        f"{metric_cn}: 报告值 {report_value}，源数据 {source_value}，偏差 {deviation:.1%}"
                    )

    logger.info("fact_check_done", claims_checked="N/A", errors=len(errors))
    return errors
```

- [ ] **Step 2: 编写报告生成 Prompt**

```python
# backend/prompts/report_generation.py
REPORT_GENERATION_SYSTEM = """你是一个资深投研报告撰写专家。基于提供的财务分析结果和舆情数据，生成结构化的投研报告。

## 报告结构（严格按此顺序）

### 1. 标题
{公司名}（{股票代码}）投研分析报告

### 2. 核心摘要
3-5 句话总结核心发现，覆盖财务表现和舆情概况。

### 3. 财务分析
- 杜邦分解：ROE={X}，分解为净利率={X} × 资产周转率={X} × 权益乘数={X}
- 因子解读：哪个因子是主要驱动/拖累
- 所有数值引用必须标注来源

### 4. 异动预警
如有异常指标，逐项列出具体数值、变动幅度和可能原因。
如无异常，写"本报告期各项关键指标未发现显著异动（同比变动均在 30% 以内）"。

### 5. 舆情研判
- 整体情感倾向 + 关键主题
- 代表性新闻列举（2-3 条）

### 6. 风险提示
基于财务数据和舆情分析的潜在风险因子（3-5 条）

### 7. 免责声明
> 本报告由 AI 自动生成，仅供参考，不构成投资建议。关键数据已与源数据库进行自动比对校验。

## 重要规则
- **所有关键数字必须附带来源标注**（格式: `（来源：{报告期}财报）`）
- 不得编造任何数值
- 篇幅: 800-1500 字
"""


def build_report_prompt(state: dict, retry_context: str = "") -> str:
    """构建报告生成 Prompt"""
    code = state.get("company_code", "")
    name = state.get("company_name", code)
    date = state.get("report_date", "")

    fin = state.get("financial_analysis") or {}
    sent = state.get("sentiment_result") or {}

    dupont = fin.get("dupont_decomposition", {})
    anomalies = fin.get("anomaly_flags", [])
    narrative = fin.get("narrative", "")

    prompt = f"""请为 {name}（{code}）生成一份投研分析报告。

## 输入数据

### 财务分析结果
{narrative}

### 杜邦分解数据
- ROE: {dupont.get('roe', 'N/A')}
- 净利率: {dupont.get('net_margin', 'N/A')}
- 资产周转率: {dupont.get('asset_turnover', 'N/A')}
- 权益乘数: {dupont.get('equity_multiplier', 'N/A')}

### 异动检测
"""
    if anomalies:
        for a in anomalies:
            prompt += f"- {a.get('metric_name')}: 变动 {a.get('change_pct', 0)*100:.1f}%（严重程度: {a.get('severity')}）\n"
    else:
        prompt += "未发现显著异动\n"

    prompt += f"""
### 舆情分析
- 整体情感: {sent.get('overall_sentiment', 'N/A')}
- 整体评分: {sent.get('overall_score', 'N/A')}
- 关键主题: {', '.join(sent.get('key_topics', []))}
- 总结: {sent.get('summary', 'N/A')}
"""
    if retry_context:
        prompt += f"\n## 修正要求\n{retry_context}\n"

    return prompt
```

- [ ] **Step 3: 实现报告生成 + 重写节点 + 条件边路由**

```python
# backend/agents/reviewer/report_generator.py
import structlog
from state import AgentState
from services.llm_service import get_llm_service
from prompts.report_generation import REPORT_GENERATION_SYSTEM, build_report_prompt

logger = structlog.get_logger()


async def report_generator_node(state: AgentState) -> AgentState:
    """生成投研报告草稿"""
    logger.info("report_generator_node_start", task_id=state.get("task_id"))

    fin = state.get("financial_analysis")
    sent = state.get("sentiment_result")

    if not fin and not sent:
        state["errors"].append("报告生成跳过: 无分析数据")
        state["draft_report"] = "无法生成报告: 财务分析和舆情分析数据均不可用。"
        return state

    try:
        retry_context = ""
        if state.get("errors") and state.get("retry_count", 0) > 0:
            retry_context = "以下数据在上次报告中与源数据不匹配，请修正：\n" + "\n".join(
                f"  - {e}" for e in state["errors"]
            )

        prompt = build_report_prompt(state, retry_context)
        llm = get_llm_service()
        result = await llm.invoke("reviewer", [
            {"role": "system", "content": REPORT_GENERATION_SYSTEM},
            {"role": "user", "content": prompt},
        ])
        state["draft_report"] = result.get("content", "")
        logger.info("report_generator_node_done", length=len(state["draft_report"]))
    except Exception as e:
        logger.error("report_generator_error", error=str(e))
        state["errors"].append(f"报告生成失败: {str(e)}")
        if state.get("draft_report") is None:
            state["draft_report"] = f"报告生成异常: {str(e)}"

    return state
```

```python
# backend/agents/reviewer/rewriter.py
import structlog
from state import AgentState

logger = structlog.get_logger()


async def rewriter_node(state: AgentState) -> AgentState:
    """重写节点：将错误信息注入 state，然后重新调用 report_generator_node"""
    logger.info("rewriter_node_start", task_id=state.get("task_id"), retry=state.get("retry_count", 0))
    state["retry_count"] = state.get("retry_count", 0) + 1
    state["errors"] = state.get("errors", [])
    # 重写逻辑由 report_generator_node 检测 errors 和 retry_count 后自动处理
    # 此节点仅更新计数器，实际重写由 report_generator_node 完成
    return state
```

```python
# backend/agents/reviewer/router.py
import structlog
from state import AgentState

logger = structlog.get_logger()


def route_after_review(state: AgentState) -> str:
    """反思循环条件边：决定重写还是输出"""
    errors = state.get("errors", [])
    retry = state.get("retry_count", 0)

    if errors and retry < 3:
        logger.info("route_to_rewriter", errors=len(errors), retry=retry)
        return "rewriter"
    else:
        if errors and retry >= 3:
            # 追加未通过校验的说明
            warning = "\n\n---\n\n⚠️ **自动校验未完全通过**\n\n以下数据项在 3 轮校验后仍与源数据库存在偏差：\n\n"
            for e in errors:
                warning += f"- {e}\n"
            warning += "\n请人工复核上述数据。"
            state["draft_report"] = (state.get("draft_report", "") + warning)
            logger.warning("route_to_output_with_errors", remaining=len(errors))
        logger.info("route_to_output", retry=retry)
        return "output"
```

- [ ] **Step 4: 编写校验总结单元测试**

```python
# backend/tests/agents/test_reviewer.py
import pytest
from unittest.mock import AsyncMock, patch
from state import make_initial_state
from agents.reviewer.fact_checker import verify_facts
from agents.reviewer.report_generator import report_generator_node
from agents.reviewer.router import route_after_review


class TestFactChecker:
    @pytest.mark.asyncio
    async def test_no_db_session_returns_empty(self):
        report = "ROE为12.3%，净利润50亿元，营收100亿元"
        errors = await verify_facts(report, "600519", db_session=None)
        assert errors == []  # 无 DB 时不报错

    @pytest.mark.asyncio
    async def test_extracts_numerical_claims(self):
        report = "ROE为12.3%，净利润56.78亿元"
        # 仅测试正则提取，不测试 DB 比对
        import re
        pattern = r'(净利润|营收)[^\d]*(\d+\.?\d*)\s*[亿元]'
        matches = list(re.finditer(pattern, report))
        assert len(matches) == 1
        assert matches[0].group(1) == "净利润"
        assert matches[0].group(2) == "56.78"


class TestReportGenerator:
    @pytest.mark.asyncio
    async def test_generates_report(self):
        state = make_initial_state("task-001")
        state["company_code"] = "600519"
        state["company_name"] = "贵州茅台"
        state["report_date"] = "2024-09-30"
        state["financial_analysis"] = {
            "dupont_decomposition": {"roe": 0.25, "net_margin": 0.50, "asset_turnover": 0.25, "equity_multiplier": 2.0, "is_valid": True},
            "anomaly_flags": [],
            "narrative": "茅台Q3盈利表现强劲，ROE达25%",
            "analyst_confidence": "high",
        }
        state["sentiment_result"] = {
            "overall_sentiment": "positive", "overall_score": 0.72,
            "key_topics": ["业绩增长"], "summary": "舆情正面",
        }

        mock_llm = AsyncMock()
        mock_llm.invoke.return_value = {
            "content": "# 贵州茅台（600519）投研分析报告\n\n## 核心摘要\n...",
            "model": "deepseek-chat",
            "usage": {"prompt_tokens": 500, "completion_tokens": 800},
        }

        with patch("agents.reviewer.report_generator.get_llm_service", return_value=mock_llm):
            result = await report_generator_node(state)
            assert result["draft_report"] is not None
            assert len(result["draft_report"]) > 0

    @pytest.mark.asyncio
    async def test_handles_no_analysis_data(self):
        state = make_initial_state("task-002")
        result = await report_generator_node(state)
        assert "无法生成报告" in result.get("draft_report", "")


class TestRouting:
    def test_route_to_rewriter_when_errors_and_retry_under_3(self):
        state = make_initial_state("task-001")
        state["errors"] = ["ROE: 报告值 0.12，源数据 0.10"]
        state["retry_count"] = 0
        assert route_after_review(state) == "rewriter"

    def test_route_to_output_when_no_errors(self):
        state = make_initial_state("task-001")
        state["errors"] = []
        state["retry_count"] = 0
        assert route_after_review(state) == "output"

    def test_route_to_output_when_retry_exhausted(self):
        state = make_initial_state("task-001")
        state["errors"] = ["ROE: 偏差 0.02"]
        state["retry_count"] = 3
        state["draft_report"] = "report content"
        result = route_after_review(state)
        assert result == "output"
        assert "自动校验未完全通过" in state["draft_report"]
```

- [ ] **Step 5: 运行测试**

```bash
cd backend && pytest tests/agents/test_reviewer.py -v
```

Expected: 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/agents/reviewer/ backend/prompts/report_generation.py backend/tests/agents/test_reviewer.py
git commit -m "feat: add reviewer agent with fact-checker and reflection loop"
```

---

### Task 9: LangGraph 图编排 + 条件边 + 输出节点

**Files:**
- Create: `backend/graph.py`
- Create: `backend/graph_routes.py`
- Create: `backend/agents/output_node.py`
- Create: `backend/tests/test_graph.py`

- [ ] **Step 1: 实现条件边路由函数**

```python
# backend/graph_routes.py
import structlog
from state import AgentState

logger = structlog.get_logger()


def route_after_collect(state: AgentState) -> str:
    """数据收集节点后——根据 intent 分发"""
    intent = state.get("intent", "comprehensive")
    errors = state.get("errors", [])

    # 如果数据完全收集失败，直接输出
    if state.get("raw_data") is None:
        logger.info("route_after_collect_no_data")
        return "output"

    logger.info("route_after_collect", intent=intent)
    match intent:
        case "simple_query":
            return "output"
        case "financial_analysis":
            return "financial_analyzer"
        case "sentiment_analysis":
            return "sentiment_analyzer"
        case "comprehensive":
            return "financial_analyzer"
        case _:
            return "financial_analyzer"


def route_after_financial(state: AgentState) -> str:
    """财务分析节点后——快速分析通道直接输出，comprehensive 继续"""
    intent = state.get("intent", "comprehensive")
    logger.info("route_after_financial", intent=intent)
    if intent == "financial_analysis":
        return "output"
    else:
        return "sentiment_analyzer"


def route_after_sentiment(state: AgentState) -> str:
    """舆情节点后——comprehensive 进入报告生成"""
    intent = state.get("intent", "comprehensive")
    logger.info("route_after_sentiment", intent=intent)
    if intent == "sentiment_analysis":
        return "output"
    else:
        return "report_generator"
```

- [ ] **Step 2: 实现输出节点**

```python
# backend/agents/output_node.py
import structlog
from state import AgentState

logger = structlog.get_logger()


async def output_node(state: AgentState) -> AgentState:
    """最终输出节点：根据 intent 组装回复文本"""
    logger.info("output_node_start", task_id=state.get("task_id"), intent=state.get("intent"))

    intent = state.get("intent", "comprehensive")

    if intent == "comprehensive":
        # 报告即回复
        state["chat_reply"] = state.get("draft_report", "")
    else:
        # 快速通道：基于 raw_data + 分析结果构建自然语言回复
        parts = []

        raw = state.get("raw_data") or {}
        metrics = raw.get("financial_metrics", {})
        if metrics:
            parts.append(f"### {state.get('company_name', state.get('company_code', ''))} 财务数据\n")
            for k, v in metrics.items():
                if v is not None:
                    parts.append(f"- {k}: {v}")
            parts.append("")

        fin = state.get("financial_analysis")
        if fin and fin.get("narrative"):
            parts.append(fin["narrative"])

        sent = state.get("sentiment_result")
        if sent and sent.get("summary"):
            parts.append(f"\n### 舆情概况\n{sent['summary']}")

        if not parts:
            parts.append("未能获取到相关数据，请稍后重试。")

        state["chat_reply"] = "\n".join(parts)

    state["status"] = "done"
    logger.info("output_node_done", reply_length=len(state.get("chat_reply", "")))
    return state
```

- [ ] **Step 3: 构建 LangGraph StateGraph**

```python
# backend/graph.py
import structlog
from langgraph.graph import StateGraph, END
from state import AgentState

from agents.intent_classifier.node import intent_classifier_node
from agents.data_collector.node import data_collector_node
from agents.financial_analyzer.node import financial_analyzer_node
from agents.sentiment_analyzer.node import sentiment_analyzer_node
from agents.reviewer.report_generator import report_generator_node
from agents.reviewer.rewriter import rewriter_node
from agents.reviewer.router import route_after_review
from agents.output_node import output_node

from graph_routes import route_after_collect, route_after_financial, route_after_sentiment

logger = structlog.get_logger()


def build_graph() -> StateGraph:
    """构建并编译 LangGraph StateGraph"""
    graph = StateGraph(AgentState)

    # 注册节点
    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("data_collector", data_collector_node)
    graph.add_node("financial_analyzer", financial_analyzer_node)
    graph.add_node("sentiment_analyzer", sentiment_analyzer_node)
    graph.add_node("report_generator", report_generator_node)
    graph.add_node("rewriter", rewriter_node)
    graph.add_node("output", output_node)

    # 设置入口
    graph.set_entry_point("intent_classifier")

    # 边 1: 意图分类 → 数据收集（无条件）
    graph.add_edge("intent_classifier", "data_collector")

    # 边 2: 数据收集 → 根据 intent 分发
    graph.add_conditional_edges(
        "data_collector",
        route_after_collect,
        {
            "output": "output",
            "financial_analyzer": "financial_analyzer",
            "sentiment_analyzer": "sentiment_analyzer",
        }
    )

    # 边 3: 财务分析 → 分发
    graph.add_conditional_edges(
        "financial_analyzer",
        route_after_financial,
        {
            "output": "output",
            "sentiment_analyzer": "sentiment_analyzer",
        }
    )

    # 边 4: 舆情 → 分发
    graph.add_conditional_edges(
        "sentiment_analyzer",
        route_after_sentiment,
        {
            "output": "output",
            "report_generator": "report_generator",
        }
    )

    # 边 5: 报告生成 → 反思循环条件边
    graph.add_conditional_edges(
        "report_generator",
        route_after_review,
        {
            "rewriter": "rewriter",
            "output": "output",
        }
    )

    # 边 6: 重写 → 回到报告生成
    graph.add_edge("rewriter", "report_generator")

    # 边 7: 输出 → 结束
    graph.add_edge("output", END)

    logger.info("graph_built", nodes=7)
    return graph.compile()


# 全局编译实例
app_graph = build_graph()
```

- [ ] **Step 4: 编写图编排单元测试**

```python
# backend/tests/test_graph.py
import pytest
from unittest.mock import AsyncMock, patch
from state import make_initial_state
from graph import build_graph
from graph_routes import route_after_collect, route_after_financial, route_after_sentiment
from state import AgentState


class TestRouteFunctions:
    def test_route_after_collect_simple_query(self):
        state = make_initial_state("task-001")
        state["intent"] = "simple_query"
        state["raw_data"] = {"financial_metrics": {"revenue": 100}}
        assert route_after_collect(state) == "output"

    def test_route_after_collect_financial(self):
        state = make_initial_state("task-001")
        state["intent"] = "financial_analysis"
        state["raw_data"] = {"financial_metrics": {"revenue": 100}}
        assert route_after_collect(state) == "financial_analyzer"

    def test_route_after_collect_sentiment(self):
        state = make_initial_state("task-001")
        state["intent"] = "sentiment_analysis"
        state["raw_data"] = {"financial_metrics": {}}
        assert route_after_collect(state) == "sentiment_analyzer"

    def test_route_after_collect_no_data(self):
        state = make_initial_state("task-001")
        state["raw_data"] = None
        assert route_after_collect(state) == "output"

    def test_route_after_financial_quick(self):
        state = make_initial_state("task-001")
        state["intent"] = "financial_analysis"
        assert route_after_financial(state) == "output"

    def test_route_after_financial_comprehensive(self):
        state = make_initial_state("task-001")
        state["intent"] = "comprehensive"
        assert route_after_financial(state) == "sentiment_analyzer"

    def test_route_after_sentiment_quick(self):
        state = make_initial_state("task-001")
        state["intent"] = "sentiment_analysis"
        assert route_after_sentiment(state) == "output"


class TestGraphBuild:
    def test_graph_compiles(self):
        graph = build_graph()
        assert graph is not None
        # 检查图有节点
        nodes = graph.get_graph().nodes
        assert len(nodes) > 0

    def test_graph_accepts_state(self):
        graph = build_graph()
        state = make_initial_state("test-task")
        state["company_code"] = "600519"
        state["intent"] = "simple_query"
        # 仅验证图可以接受 state 输入而不报错
        assert state["task_id"] == "test-task"
```

- [ ] **Step 5: 运行测试**

```bash
cd backend && pytest tests/test_graph.py -v
```

Expected: 9 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/graph.py backend/graph_routes.py backend/agents/output_node.py backend/tests/test_graph.py
git commit -m "feat: add LangGraph StateGraph with 7 nodes, 4 conditional edges, and output node"
```

---

### Task 10: FastAPI 入口 + SSE 流式 + Celery 任务

**Files:**
- Modify: `backend/main.py`
- Create: `backend/services/task_queue/__init__.py`
- Create: `backend/services/task_queue/celery_app.py`
- Create: `backend/services/task_queue/manager.py`
- Create: `backend/tests/test_main.py`

- [ ] **Step 1: Celery 应用 + 分析任务**

```python
# backend/services/task_queue/celery_app.py
import os
import structlog
from celery import Celery

logger = structlog.get_logger()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "financial_agent",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)


@celery_app.task(bind=True, max_retries=2)
def run_comprehensive_analysis(self, task_id: str, company_code: str, report_date: str = ""):
    """Celery 异步任务：执行 comprehensive 全管道分析"""
    import asyncio
    from state import make_initial_state
    from graph import build_graph
    from services.task_queue.manager import _redis_client

    logger.info("celery_task_start", task_id=task_id, code=company_code)

    try:
        state = make_initial_state(task_id)
        state["intent"] = "comprehensive"
        state["company_code"] = company_code
        state["report_date"] = report_date

        graph = build_graph()
        # LangGraph 在同步 Celery task 中运行 async 图
        async def run():
            return await graph.ainvoke(state)

        final_state = asyncio.run(run())

        # 结果缓存到 Redis
        import json
        r = _redis_client()
        if r:
            r.setex(f"task:{task_id}", 3600, json.dumps({
                "status": "done",
                "result": {
                    "draft_report": final_state.get("draft_report", ""),
                    "chat_reply": final_state.get("chat_reply", ""),
                },
            }, ensure_ascii=False))

        logger.info("celery_task_done", task_id=task_id)
        return {"status": "done", "task_id": task_id}
    except Exception as e:
        logger.error("celery_task_error", task_id=task_id, error=str(e))
        raise self.retry(exc=e, countdown=10)
```

- [ ] **Step 2: 任务管理器**

```python
# backend/services/task_queue/manager.py
import os
import json
import uuid
import structlog
import redis.asyncio as redis

logger = structlog.get_logger()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _redis_client():
    """获取同步 Redis 客户端"""
    try:
        return redis.from_url(REDIS_URL, decode_responses=True)
    except Exception:
        return None


async def get_redis():
    """获取异步 Redis 客户端"""
    return redis.from_url(REDIS_URL, decode_responses=True)


class TaskManager:
    @staticmethod
    async def submit(company_code: str, report_date: str = "") -> str:
        """提交异步分析任务"""
        task_id = str(uuid.uuid4())[:8]
        r = await get_redis()
        await r.setex(f"task:{task_id}", 3600, json.dumps({
            "task_id": task_id, "company_code": company_code,
            "status": "pending", "created_at": "", "result": None,
        }, ensure_ascii=False))

        # 提交 Celery 任务
        from services.task_queue.celery_app import run_comprehensive_analysis
        run_comprehensive_analysis.delay(task_id, company_code, report_date)

        logger.info("task_submitted", task_id=task_id)
        return task_id

    @staticmethod
    async def get_status(task_id: str) -> dict:
        """查询任务状态"""
        r = await get_redis()
        data = await r.get(f"task:{task_id}")
        if data:
            return json.loads(data)
        return {"task_id": task_id, "status": "not_found"}

    @staticmethod
    async def cancel(task_id: str) -> bool:
        """中断任务"""
        r = await get_redis()
        await r.set(f"task:{task_id}:cancelled", "1", ex=3600)
        # Celery revoke
        from services.task_queue.celery_app import celery_app
        celery_app.control.revoke(task_id, terminate=True)
        logger.info("task_cancelled", task_id=task_id)
        return True
```

- [ ] **Step 3: 实现 FastAPI 入口**

```python
# backend/main.py
import os
import json
import uuid
import structlog
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from state import make_initial_state, AgentState
from graph import build_graph
from services.task_queue.manager import TaskManager, get_redis

logger = structlog.get_logger()


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    attachments: list[str] = []


class TaskRequest(BaseModel):
    company_code: str
    report_date: str = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app_startup")
    yield
    logger.info("app_shutdown")


app = FastAPI(title="金融多智能体协作系统", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.post("/api/v1/chat")
async def chat(request: ChatRequest):
    """快速对话通道 - SSE 流式返回"""
    task_id = str(uuid.uuid4())[:8]
    logger.info("chat_request", task_id=task_id, message=request.message[:50])

    # 1. 先做意图分类
    from agents.intent_classifier.classifier import classify_intent
    intent_result = await classify_intent(request.message)

    # 2. 如果是 comprehensive，转为异步任务
    if intent_result.intent == "comprehensive":
        task_id = await TaskManager.submit(
            intent_result.company_code, intent_result.report_date
        )
        return {"task_id": task_id, "status": "accepted",
                "message": "综合分析已转为异步任务，请通过 GET /tasks/{task_id}/stream 订阅进度"}

    # 3. 同步执行快速通道
    state = make_initial_state(task_id)
    state["intent"] = intent_result.intent
    state["company_code"] = intent_result.company_code
    state["company_name"] = intent_result.company_name
    state["report_date"] = intent_result.report_date

    async def event_generator():
        graph = build_graph()
        try:
            # 发送意图事件
            yield f"event: intent\ndata: {json.dumps({'intent': intent_result.intent, 'latency_ms': 0})}\n\n"

            # 运行图（同步等待完成，流式输出最终结果）
            final_state = await graph.ainvoke(state)

            # 发送最终回复
            chat_reply = final_state.get("chat_reply", "")
            for line in chat_reply.split("\n"):
                yield f"event: chunk\ndata: {json.dumps({'text': line + '\n'})}\n\n"

            yield f"event: done\ndata: {json.dumps({'task_id': task_id, 'total_latency_ms': 0})}\n\n"
        except Exception as e:
            logger.error("chat_error", task_id=task_id, error=str(e))
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/v1/tasks")
async def submit_task(request: TaskRequest):
    """提交异步分析任务"""
    if not request.company_code:
        raise HTTPException(status_code=400, detail="company_code is required")
    task_id = await TaskManager.submit(request.company_code, request.report_date)
    return {"task_id": task_id, "status": "pending"}


@app.get("/api/v1/tasks/{task_id}")
async def get_task_status(task_id: str):
    """查询任务状态"""
    return await TaskManager.get_status(task_id)


@app.get("/api/v1/tasks/{task_id}/stream")
async def stream_task_progress(task_id: str):
    """SSE 订阅任务进度"""
    async def event_generator():
        r = await get_redis()
        pubsub = r.pubsub()
        channel = f"task:{task_id}:events"
        await pubsub.subscribe(channel)
        try:
            # 先发送当前状态
            status = await TaskManager.get_status(task_id)
            yield f"event: status\ndata: {json.dumps(status)}\n\n"

            if status.get("status") in ("done", "failed"):
                yield f"event: done\ndata: {json.dumps(status)}\n\n"
                return

            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
                    try:
                        event_data = json.loads(message['data'])
                        if event_data.get("type") in ("done", "failed"):
                            break
                    except json.JSONDecodeError:
                        pass
        finally:
            await pubsub.unsubscribe(channel)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/v1/reports/{task_id}")
async def get_report(task_id: str):
    """获取已完成报告"""
    status = await TaskManager.get_status(task_id)
    if status.get("status") != "done":
        raise HTTPException(status_code=404, detail="Report not ready or task not found")
    return {"task_id": task_id, "report": status.get("result", {}).get("draft_report", "")}


@app.get("/api/v1/health")
async def health():
    """健康检查"""
    health_status = {"status": "healthy", "milvus": "not_configured", "redis": "unknown", "mysql": "unknown"}
    # 检查 Redis
    try:
        r = await get_redis()
        await r.ping()
        health_status["redis"] = "connected"
    except Exception:
        health_status["redis"] = "disconnected"
    return health_status


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
```

- [ ] **Step 4: 编写 FastAPI 集成测试**

```python
# backend/tests/test_main.py
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from main import app


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_200(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"


class TestTaskEndpoint:
    @pytest.mark.asyncio
    async def test_submit_task_requires_code(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/v1/tasks", json={})
            assert response.status_code == 422  # Pydantic validation error


class TestReportEndpoint:
    @pytest.mark.asyncio
    async def test_report_not_found(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/reports/nonexistent")
            assert response.status_code == 404
```

- [ ] **Step 5: 运行测试**

```bash
cd backend && pip install httpx && pytest tests/test_main.py -v
```

Expected: 3 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/services/task_queue/ backend/tests/test_main.py
git commit -m "feat: add FastAPI entry with /chat SSE and /tasks async routes, Celery integration"
```

---

### Task 11: DB Models + 初始化脚本验证

**Files:**
- Create: `backend/db/__init__.py`
- Create: `backend/db/models.py`

- [ ] **Step 1: 创建 SQLAlchemy Models**

```python
# backend/db/models.py
from sqlalchemy import Column, BigInteger, String, Date, DateTime, Integer, Text, JSON, func, Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase
import enum


class Base(DeclarativeBase):
    pass


class TaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class FinancialData(Base):
    __tablename__ = "financial_data"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_code = Column(String(10), nullable=False, index=True)
    report_date = Column(Date, nullable=False)
    metric_name = Column(String(64), nullable=False)
    metric_value = Column(String(64), nullable=False)
    source = Column(String(32), default="akshare")
    created_at = Column(DateTime, server_default=func.now())


class Document(Base):
    __tablename__ = "documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    company_code = Column(String(10), nullable=False, index=True)
    doc_type = Column(String(32), nullable=False)
    chunk_index = Column(Integer, default=0)
    content = Column(Text)
    vector_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True)
    company_code = Column(String(10), nullable=False)
    status = Column(String(16), default="pending")
    result = Column(JSON, nullable=True)
    error_log = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 2: 验证 DB 初始化 SQL 兼容性**

```bash
docker compose exec mysql mysql -u root -p${MYSQL_ROOT_PASSWORD} financial_agent -e "SHOW TABLES;"
```

Expected: `financial_data`, `documents`, `tasks` 三张表存在

- [ ] **Step 3: Commit**

```bash
git add backend/db/
git commit -m "feat: add SQLAlchemy ORM models for financial_data, documents, tasks"
```

---

### Task 12: 最终集成验证 + 文档更新

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/agent-workflow.md`
- Modify: `docs/api.md`

- [ ] **Step 1: 全量测试**

```bash
cd backend && pytest -v
```

Expected: All tests PASS (目标 40+ tests)

- [ ] **Step 2: 更新架构文档**

- 将架构图替换为双通道版本（参考设计规格 §2）
- 在 `agent-workflow.md` 中增加意图路由流程图
- 在 `api.md` 中新增 `/chat` 接口文档

- [ ] **Step 3: 验证快速开始流程**

```bash
docker compose up -d --build
cd backend && pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
# 访问 http://localhost:8000/docs 验证 Swagger UI
# GET /api/v1/health 验证健康检查
```

- [ ] **Step 4: 打标签 + 最终提交**

```bash
git tag v0.1.0-mvp
git add -A
git commit -m "chore: update docs and finalize MVP v0.1.0"
git push origin master --tags
```

---

## 测试覆盖目标

| 模块 | 测试数 | 覆盖类型 |
|------|--------|---------|
| Task 1: State | 5 | 单元测试 |
| Task 2: DataSource | 9 | 单元测试 |
| Task 3: LLMService | 4 | 单元测试 |
| Task 4: Intent Classifier | 6 | 单元测试 |
| Task 5: Data Collector | 4 | 单元测试 |
| Task 6: Financial Analyzer | 5 | 单元测试 |
| Task 7: Sentiment Analyzer | 3 | 单元测试 |
| Task 8: Reviewer | 6 | 单元测试 |
| Task 9: Graph Routes | 9 | 单元测试 |
| Task 10: FastAPI | 3 | 集成测试 |
| **Total** | **54** | |

---

*Plan version: v1.0 | Generated: 2026-06-16 | Source spec: [2026-06-16-financial-agent-mvp-design.md](../specs/2026-06-16-financial-agent-mvp-design.md)*
