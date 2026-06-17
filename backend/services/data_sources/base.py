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

    async def fetch_market_data(self, query_type: str, target: str = "") -> dict:
        """拉取市场行情数据（汇率/商品/黄金/股价/指数）。
        返回 {"type": "...", "price": ..., ...} 或空字典。
        """
        ...
