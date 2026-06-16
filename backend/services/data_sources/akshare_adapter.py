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


# 港股财务指标列名映射（stock_hk_financial_indicator_em 实际列名）
HK_METRIC_MAP = {
    "每股净资产(元)": "book_value_per_share",
    "每股股息TTM(港元)": "dividend_per_share",
    "每股经营现金流(元)": "operating_cashflow_per_share",
    "销售净利率(%)": "net_margin",
    "营业总收入": "revenue",
}


def _parse_hk_value(raw) -> float | None:
    """解析港股财务数据（纯数字，无单位后缀）"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s in ("False", "nan", "None", ""):
        return None
    try:
        return round(float(s), 4)
    except (ValueError, TypeError):
        return None


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

    @staticmethod
    def _is_hk_stock(code: str) -> bool:
        """港股代码通常为 5 位数字，如 00700、09988"""
        return len(code) == 5 and code.isdigit() and code[0] == "0"

    async def _fetch_a_share_financials(self, code: str, metrics: list[str]) -> dict:
        """A 股财报数据"""
        profit_df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
        if profit_df is None or profit_df.empty:
            return {}
        profit_df = profit_df.sort_index(ascending=False)
        latest = profit_df.iloc[0]
        result = {}
        for cn_col in profit_df.columns:
            matched_metric = METRIC_MAP.get(cn_col)
            if matched_metric and matched_metric in metrics:
                val = _parse_value(latest[cn_col], matched_metric)
                if val is not None:
                    result[matched_metric] = val
        return result

    async def _fetch_hk_financials(self, code: str, metrics: list[str]) -> dict:
        """港股财务指标数据"""
        df = ak.stock_hk_financial_indicator_em(symbol=code)
        if df is None or df.empty:
            return {}
        latest = df.iloc[0]
        result = {}
        for cn_col in df.columns:
            matched_metric = HK_METRIC_MAP.get(cn_col)
            if matched_metric and matched_metric in metrics:
                raw_val = latest[cn_col]
                if matched_metric == "net_margin":
                    # 港股 API 返回百分比数值如 30.23，转为小数 0.3023
                    val = _parse_hk_value(raw_val)
                    if val is not None:
                        result[matched_metric] = round(val / 100.0, 4)
                elif matched_metric == "revenue":
                    # 港股 API 返回原始金额（元），转为亿
                    val = _parse_hk_value(raw_val)
                    if val is not None:
                        result[matched_metric] = round(val / 1e8, 4)
                else:
                    val = _parse_hk_value(raw_val)
                    if val is not None:
                        result[matched_metric] = val
        return result

    async def fetch_financials(self, code: str, date: str, metrics: list[str]) -> dict:
        code = normalize_stock_code(code)
        logger.info("akshare_fetch_financials_start", code=code, date=date, requested=metrics)
        try:
            if self._is_hk_stock(code):
                result = await self._fetch_hk_financials(code, metrics)
            else:
                result = await self._fetch_a_share_financials(code, metrics)

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
