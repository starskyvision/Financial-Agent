import structlog
import httpx
import akshare as ak
from services.data_sources.base import DataSourceAdapter, DataSourceConfig

logger = structlog.get_logger()

# AKShare stock_financial_abstract_ths 实际返回的列名 → 我们的 metric 名
METRIC_MAP = {
    "净利润": "net_profit",
    "营业总收入": "revenue",
    "净资产收益率-摊薄": "roe",          # "净资产收益率" 经常返回 False，用摊薄代替
    "净资产收益率": "roe",               # 备选
    "总资产收益率": "roa",
    "销售毛利率": "gross_margin",
    "销售净利率": "net_margin",
    "每股经营现金流": "operating_cashflow_per_share",
    "资产负债率": "debt_ratio",
    "产权比率": "equity_ratio",
}

# 需要按百分比解析的指标（AKShare 返回 "7.51%" 格式）
PERCENT_METRICS = {"roe", "roa", "gross_margin", "net_margin", "debt_ratio"}

# 需要按"亿"解析的指标（AKShare 返回 "4858.33亿" 格式）
BILLION_METRICS = {"net_profit", "revenue"}


def _parse_value(raw: str, metric: str) -> float | None:
    """解析 AKShare 返回的原始值：去掉单位，转为 float"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s == "False" or s == "nan":
        return None
    try:
        if metric in PERCENT_METRICS:
            s = s.replace("%", "")
            return round(float(s) / 100.0, 4)  # 转为小数，如 7.51% → 0.0751
        elif metric in BILLION_METRICS:
            s = s.replace("亿", "").replace("万", "")
            return round(float(s), 4)  # 已经是亿为单位
        else:
            return round(float(s), 4)
    except (ValueError, TypeError):
        return None


def normalize_stock_code(code: str) -> str:
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

            # 取最新一行数据（按报告期降序排列，第一行为最新）
            profit_df = profit_df.sort_index(ascending=False)
            latest = profit_df.iloc[0]
            result = {}

            # 遍历 AKShare 的每一列，匹配我们需要的指标
            for cn_col in profit_df.columns:
                matched_metric = METRIC_MAP.get(cn_col)
                if matched_metric and matched_metric in metrics:
                    val = _parse_value(latest[cn_col], matched_metric)
                    if val is not None:
                        result[matched_metric] = val

            # 根据可用数据推导缺失指标
            # 如果 ROE 没拿到（"净资产收益率"返回False），尝试"净资产收益率-摊薄"
            if "roe" not in result and "净资产收益率-摊薄" not in [c for c in profit_df.columns]:
                # 已经尝试过摊薄映射
                pass

            # 如果拿到了产权比率，可以推导权益乘数: equity_multiplier = 1 + equity_ratio
            if "equity_ratio" in result and "equity_multiplier" in metrics:
                eq_ratio = result.get("equity_ratio")
                if eq_ratio is not None:
                    result["equity_multiplier"] = round(1.0 + eq_ratio, 4)

            # 如果拿到了资产负债率+产权比率，尝试推导 total_assets 和 total_liabilities
            if "debt_ratio" in result and "revenue" in result and "total_assets" in metrics:
                # 资产负债率 = 总负债/总资产 = 产权比率/(1+产权比率)
                # 这里留空，因为没有总资产的具体数值
                pass

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
                title = str(row.get("新闻标题", "") or row.get("标题", ""))
                if not title:
                    continue
                published_str = str(row.get("发布时间", ""))
                if published_str and cutoff:
                    try:
                        pub_date = datetime.strptime(published_str[:10], "%Y-%m-%d")
                        if pub_date < cutoff:
                            continue
                    except ValueError:
                        pass
                news_list.append({
                    "title": title,
                    "summary": (str(row.get("新闻内容", "") or row.get("内容", "")))[:200],
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
