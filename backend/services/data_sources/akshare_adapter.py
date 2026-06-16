import structlog
import httpx
import akshare as ak
from services.data_sources.base import DataSourceAdapter, DataSourceConfig

logger = structlog.get_logger()

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

# 比率类指标（小数表示，不需要单位转换）
RATIO_METRICS = {"roe", "roa", "gross_margin", "net_margin", "asset_turnover", "equity_multiplier"}


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
            profit_df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
            if profit_df is None or profit_df.empty:
                logger.warning("akshare_empty_response", code=code)
                return {}

            result = {}
            for metric in metrics:
                cn_name = METRIC_MAP.get(metric)
                if cn_name and cn_name in profit_df.columns:
                    val = profit_df[cn_name].dropna().iloc[0] if not profit_df[cn_name].dropna().empty else None
                    if val is not None:
                        try:
                            num = float(val)
                            # 比率类指标小数表示，无需单位转换；绝对金额转为亿元
                            if metric not in RATIO_METRICS:
                                num = round(num / 1e8, 4)
                            else:
                                num = round(num, 4)
                            result[metric] = num
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
                published_str = str(row.get("发布时间", ""))
                # 按 days 参数过滤
                if published_str and cutoff:
                    try:
                        pub_date = datetime.strptime(published_str[:10], "%Y-%m-%d")
                        if pub_date < cutoff:
                            continue
                    except ValueError:
                        pass  # 无法解析日期时不跳过
                news_list.append({
                    "title": title,
                    "summary": str(row.get("内容", ""))[:200] if row.get("内容") else "",
                    "source": "东方财富",
                    "published_at": published_str,
                })
            logger.info("akshare_fetch_news_done", code=code, count=len(news_list))
            return news_list
        except ImportError:
            return []
        except Exception as e:
            logger.error("akshare_fetch_news_error", code=code, error=str(e))
            return []

    async def fetch_documents(self, code: str, doc_type: str, limit: int) -> list[dict]:
        return []

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
