import re
import structlog
import httpx
import akshare as ak
from services.data_sources.base import DataSourceAdapter, DataSourceConfig
from constants.metrics import A_SHARE_COLUMN_MAP, HK_COLUMN_MAP

logger = structlog.get_logger()

# A-Share: "7.51%" / "4858.33亿" format
A_SHARE_PERCENT_METRICS = {"roe", "roa", "gross_margin", "net_margin", "debt_ratio"}
A_SHARE_BILLION_METRICS = {"net_profit", "revenue"}

# HK: 21.13 -> 0.2113 / raw yuan -> billions
HK_PERCENT_METRICS = {"roe", "roa", "gross_margin", "net_margin", "debt_ratio"}
HK_BILLION_METRICS = {"revenue", "net_profit"}


def normalize_stock_code(code: str) -> str:
    code = code.strip().upper()
    code = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    code = code.replace("SH", "").replace("SZ", "").replace("BJ", "")
    return code


def _parse_value(raw: str, metric: str) -> float | None:
    """Parse A-share raw value: strip unit suffix, convert to float"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s == "False" or s == "nan":
        return None
    try:
        if metric in A_SHARE_PERCENT_METRICS:
            s = s.replace("%", "")
            return round(float(s) / 100.0, 4)
        elif metric in A_SHARE_BILLION_METRICS:
            s = s.replace("亿", "").replace("万", "")
            return round(float(s), 4)
        else:
            return round(float(s), 4)
    except (ValueError, TypeError):
        return None


def _parse_hk_value(raw, metric: str) -> float | None:
    """Parse HK financial data (raw numbers, no unit suffix)"""
    if raw is None:
        return None
    try:
        val = float(raw)
        if metric in HK_PERCENT_METRICS:
            return round(val / 100.0, 4)   # 21.13 -> 0.2113
        elif metric in HK_BILLION_METRICS:
            return round(val / 1e8, 4)      # 751766000000 -> 7517.66
        else:
            return round(val, 4)
    except (ValueError, TypeError):
        return None


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
        return len(code) == 5 and code.isdigit() and code[0] == "0"

    async def _fetch_a_share_financials(self, code: str, metrics: list[str]) -> dict:
        profit_df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
        if profit_df is None or profit_df.empty:
            return {}
        profit_df = profit_df.sort_index(ascending=False)
        latest = profit_df.iloc[0]
        result = {}
        for cn_col in profit_df.columns:
            matched_metric = A_SHARE_COLUMN_MAP.get(cn_col)
            if matched_metric and matched_metric in metrics:
                val = _parse_value(latest[cn_col], matched_metric)
                if val is not None:
                    result[matched_metric] = val
        return result

    async def _fetch_hk_financials(self, code: str, metrics: list[str]) -> dict:
        df = ak.stock_financial_hk_analysis_indicator_em(symbol=code)
        if df is None or df.empty:
            return {}
        latest = df.iloc[0]
        result = {}
        for col in df.columns:
            matched_metric = HK_COLUMN_MAP.get(col)
            if matched_metric and matched_metric in metrics:
                val = _parse_hk_value(latest[col], matched_metric)
                if val is not None:
                    result[matched_metric] = val
        # Derive equity_ratio from debt_ratio
        if "debt_ratio" in result and "equity_ratio" in metrics:
            dr = result["debt_ratio"]
            if dr < 1.0:
                result["equity_ratio"] = round(dr / (1.0 - dr), 4)
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

    async def fetch_market_data(self, query_type: str, target: str = "") -> dict:
        """拉取市场行情数据。根据 query_type 选择合适的 AKShare API，用 target 搜索匹配项。"""
        try:
            # --- 汇率 ---
            if query_type == "exchange_rate":
                df = ak.fx_spot_quote()
                if df is not None and not df.empty:
                    cols = list(df.columns)
                    # target 如 "USD/CNY" 或 "美元" 或 "人民币"
                    search_terms = [target] if target else ["USD/CNY"]
                    if "美元" in target or "USD" in target.upper():
                        search_terms = ["USD/CNY"]
                    for term in search_terms:
                        mask = df[cols[0]].astype(str).str.contains(term, case=False, na=False)
                        if mask.any():
                            row = df[mask].iloc[0]
                            return {
                                "type": "exchange_rate",
                                "pair": str(row[cols[0]]),
                                "bid": float(row[cols[1]]),
                                "ask": float(row[cols[2]]),
                            }

            # --- 大宗商品（通用搜索 futures_global_spot_em） ---
            elif query_type == "commodity_price":
                df = ak.futures_global_spot_em()
                if df is not None and not df.empty and target:
                    cols = list(df.columns)
                    # 在名称列（索引2）中搜索 target
                    name_col = cols[2]
                    mask = df[name_col].astype(str).str.contains(target, case=False, na=False)
                    if mask.any():
                        row = df[mask].iloc[0]
                        price = float(row[cols[3]]) if row[cols[3]] and str(row[cols[3]]) != "nan" else 0
                        change = float(row[cols[5]]) if row[cols[5]] and str(row[cols[5]]) != "nan" else 0
                        return {
                            "type": "commodity_price",
                            "label": str(row[name_col]),
                            "price": price,
                            "change_pct": change,
                        }

            # --- 黄金（专用 API，更精确） ---
            elif query_type == "gold_price":
                df = ak.spot_golden_benchmark_sge()
                if df is not None and not df.empty:
                    latest = df.iloc[-1]
                    cols = list(df.columns)
                    return {
                        "type": "gold_price",
                        "label": "上海金交所 Au99.99 基准价",
                        "open": round(float(latest[cols[1]]), 2),
                        "close": round(float(latest[cols[2]]), 2),
                        "date": str(latest[cols[0]]),
                        "unit": "元/克",
                    }

            # --- 股票价格 ---
            elif query_type == "stock_price":
                code = re.sub(r'\D', '', target)
                if self._is_hk_stock(code):
                    try:
                        df = ak.stock_hk_daily(symbol=code, adjust="")
                        if df is not None and not df.empty:
                            latest = df.iloc[-1]
                            prev = df.iloc[-2] if len(df) > 1 else latest
                            change_pct = ((latest["close"] - prev["close"]) / prev["close"] * 100) if len(df) > 1 else 0
                            return {
                                "type": "stock_price", "code": code, "name": target,
                                "price": round(float(latest["close"]), 2),
                                "change_pct": round(float(change_pct), 2),
                                "open": round(float(latest["open"]), 2),
                                "high": round(float(latest["high"]), 2),
                                "low": round(float(latest["low"]), 2),
                                "volume": float(latest["volume"]),
                                "amount": float(latest["amount"]),
                                "date": str(latest["date"]), "market": "HK",
                            }
                    except Exception:
                        pass
                else:
                    try:
                        df = ak.stock_zh_a_spot_em()
                        match = df[df["代码"] == code]
                        if not match.empty:
                            row = match.iloc[0]
                            return {
                                "type": "stock_price", "code": code,
                                "name": str(row.get("名称", "")),
                                "price": float(row.get("最新价", 0)),
                                "change_pct": float(row.get("涨跌幅", 0)),
                                "volume": float(row.get("成交量", 0)),
                                "amount": float(row.get("成交额", 0)), "market": "A",
                            }
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("market_data_error", query_type=query_type, error=str(e))
        return {}

    async def fetch_documents(self, code: str, doc_type: str, limit: int) -> list[dict]:
        return []

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
