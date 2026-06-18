import os
import re
import structlog
import httpx
import akshare as ak
from services.data_sources.base import DataSourceAdapter, DataSourceConfig
from services.env import env_int
from constants.metrics import A_SHARE_COLUMN_MAP, HK_COLUMN_MAP, PERCENT_FORMAT_METRICS, MAX_NEWS_FETCH, NEWS_MAX_LENGTH

logger = structlog.get_logger()


def _parse_report_date(user_date: str) -> str | None:
    """Convert user date formats to a target YYYY-MM-DD for DataFrame matching."""
    if not user_date or not user_date.strip():
        return None
    d = user_date.strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}$', d):
        return d
    m = re.match(r'^(\d{4})Q([1-4])$', d, re.IGNORECASE)
    if m:
        year, q = int(m.group(1)), int(m.group(2))
        last_day = {1: 31, 2: 30, 3: 30, 4: 31}[q]
        return f"{year}-{q*3:02d}-{last_day}"
    m = re.match(r'^(\d{4})H([12])$', d, re.IGNORECASE)
    if m:
        return f"{m.group(1)}-{'06-30' if m.group(2) == '1' else '12-31'}"
    m = re.match(r'^(\d{4})$', d)
    if m:
        return f"{m.group(1)}-12-31"
    return None


def _find_best_row(df, date_col: int | str, target: str | None):
    """Find the row in df whose date is closest to target (not after).
    Returns (row_series, actual_date_str). If target is None, returns latest row.
    """
    if target is None or df is None or df.empty:
        # No date specified → sort by date descending so iloc[0] is latest
        if isinstance(date_col, int):
            df = df.sort_values(by=df.columns[date_col], ascending=False)
        else:
            df = df.sort_values(by=date_col, ascending=False)
        row = df.iloc[0]
        actual = str(row.iloc[0])[:10] if isinstance(date_col, int) else str(row[date_col])[:10]
        return row, actual

    # Collect dates and find closest <= target
    best_idx = 0
    best_date = ""
    for idx in range(len(df)):
        raw = str(df.iloc[idx, date_col]) if isinstance(date_col, int) else str(df.iloc[idx][date_col])
        raw = raw[:10]
        if raw <= target and (not best_date or raw > best_date):
            best_date = raw
            best_idx = idx
    if not best_date:
        # No date <= target, use oldest
        best_idx = len(df) - 1
        raw = str(df.iloc[best_idx, date_col]) if isinstance(date_col, int) else str(df.iloc[best_idx][date_col])
        best_date = raw[:10]

    return df.iloc[best_idx], best_date


# Metric value classification — uses centralized PERCENT_FORMAT_METRICS from constants
# A-share raw values carry unit suffixes ("7.51%", "4858.33亿")
# HK raw values are bare numbers (21.13 → 0.2113, 751766000000 → 7517.66)
A_SHARE_BILLION_METRICS = {"net_profit", "revenue"}
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
        if metric in PERCENT_FORMAT_METRICS:
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
        if metric in PERCENT_FORMAT_METRICS:
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
        from services.circuit_breaker import CircuitBreaker
        cb_threshold = env_int("AKSHARE_CB_THRESHOLD", "3")
        cb_recovery = env_int("AKSHARE_CB_RECOVERY", "60")
        self._cb = CircuitBreaker("akshare", failure_threshold=cb_threshold, recovery_timeout=cb_recovery)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.config.timeout))
        return self._client

    @staticmethod
    def _is_hk_stock(code: str) -> bool:
        return len(code) == 5 and code.isdigit() and code[0] == "0"

    @staticmethod
    def _is_us_stock(code: str) -> bool:
        """Validate US stock ticker: 1-5 uppercase letters, may contain dots (e.g., BRK.A)."""
        return bool(re.match(r'^[A-Z]{1,5}(\.[A-Z])?$', code.strip().upper()))

    async def _fetch_a_share_financials(self, code: str, metrics: list[str], date: str = "") -> dict:
        profit_df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
        if profit_df is None or profit_df.empty:
            return {}
        # Sort by report date (first column) ascending for _find_best_row
        profit_df = profit_df.sort_values(by=profit_df.columns[0], ascending=True)
        target = _parse_report_date(date)
        row, actual_date = _find_best_row(profit_df, 0, target)
        result = {"_report_date": actual_date}
        for cn_col in profit_df.columns:
            matched_metric = A_SHARE_COLUMN_MAP.get(cn_col)
            if matched_metric and matched_metric in metrics:
                val = _parse_value(row[cn_col], matched_metric)
                if val is not None:
                    result[matched_metric] = val
        return result

    async def _fetch_hk_financials(self, code: str, metrics: list[str], date: str = "") -> dict:
        df = ak.stock_financial_hk_analysis_indicator_em(symbol=code)
        if df is None or df.empty:
            return {}
        # Find the date column
        date_col = None
        for col_name in ("REPORT_DATE", "日期", "报告期"):
            if col_name in df.columns:
                date_col = col_name
                break
        target = _parse_report_date(date)
        if date_col:
            row, actual_date = _find_best_row(df, date_col, target)
        else:
            row = df.iloc[0]
            actual_date = ""
        result = {"_report_date": actual_date}
        for col in df.columns:
            matched_metric = HK_COLUMN_MAP.get(col)
            if matched_metric and matched_metric in metrics:
                val = _parse_hk_value(row[col], matched_metric)
                if val is not None:
                    result[matched_metric] = val
        # Derive equity_ratio from debt_ratio
        if "debt_ratio" in result and "equity_ratio" in metrics:
            dr = result["debt_ratio"]
            if dr < 1.0:
                result["equity_ratio"] = round(dr / (1.0 - dr), 4)
        return result

    async def fetch_financials(self, code: str, date: str, metrics: list[str]) -> dict:
        if self._is_us_stock(code):
            logger.info("us_stock_financials_unavailable", code=code)
            return {}
        code = normalize_stock_code(code)
        logger.info("akshare_fetch_financials_start", code=code, date=date, requested=metrics)
        try:
            return await self._cb.call(self._fetch_financials_impl(code, date, metrics))
        except Exception:
            return {}

    async def _fetch_financials_impl(self, code: str, date: str, metrics: list[str]) -> dict:
        if self._is_hk_stock(code):
            result = await self._fetch_hk_financials(code, metrics, date)
        else:
            result = await self._fetch_a_share_financials(code, metrics, date)
        logger.info("akshare_fetch_financials_done", code=code, found=len(result),
                    date=date, report_date=result.get("_report_date", ""))
        return result

    async def fetch_news(self, code: str, days: int) -> list[dict]:
        code = normalize_stock_code(code)
        logger.info("akshare_fetch_news_start", code=code, days=days)
        try:
            return await self._cb.call(self._fetch_news_impl(code, days))
        except Exception:
            return []

    async def _fetch_news_impl(self, code: str, days: int) -> list[dict]:
        df = ak.stock_news_em(symbol=code)
        if df is None or df.empty:
            return []
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(days=days)
        news_list = []
        for _, row in df.head(MAX_NEWS_FETCH).iterrows():
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
                "summary": (str(row.get("新闻内容", "") or row.get("内容", "")))[:NEWS_MAX_LENGTH],
                "source": "东方财富",
                "published_at": published_str,
                "url": str(row.get("新闻链接", "") or ""),
            })
        logger.info("akshare_fetch_news_done", code=code, count=len(news_list))
        return news_list

    async def fetch_market_data(self, query_type: str, target: str = "") -> dict:
        """拉取市场行情数据。根据 query_type 选择合适的 AKShare API，用 target 搜索匹配项。"""
        try:
            return await self._cb.call(self._fetch_market_data_impl(query_type, target))
        except Exception:
            return {}

    async def _fetch_market_data_impl(self, query_type: str, target: str = "") -> dict:
        # Exceptions propagate to CircuitBreaker.call() for proper failure tracking.
        # --- 汇率 ---
        if query_type == "exchange_rate":
            df = ak.fx_spot_quote()
            if df is not None and not df.empty:
                cols = list(df.columns)
                pair_col = df[cols[0]]
                row = None
                invert = False

                # 从 target 提取两个货币代码
                import re as re2
                codes = re2.findall(r'[A-Z]{3}', target.upper()) if target else []
                if len(codes) >= 2:
                    pair_a = f"{codes[0]}/{codes[1]}"
                    pair_b = f"{codes[1]}/{codes[0]}"
                    # 查找正向
                    mask = pair_col.astype(str).str.contains(pair_a, case=False, na=False)
                    if mask.any():
                        row = df[mask].iloc[0]
                    else:
                        # 查找反向，标记需要倒数
                        mask = pair_col.astype(str).str.contains(pair_b, case=False, na=False)
                        if mask.any():
                            row = df[mask].iloc[0]
                            invert = True
                else:
                    # 单个货币名 → 模糊搜索
                    for kw in [target, "USD/CNY"]:
                        mask = pair_col.astype(str).str.contains(kw, case=False, na=False)
                        if mask.any():
                            row = df[mask].iloc[0]
                            break

                if row is not None:
                    bid = float(row[cols[1]])
                    ask = float(row[cols[2]])
                    if invert:
                        orig_bid, orig_ask = bid, ask
                        bid = round(1.0 / orig_ask, 6) if orig_ask else 0
                        ask = round(1.0 / orig_bid, 6) if orig_bid else 0
                    return {
                        "type": "exchange_rate",
                        "pair": str(row[cols[0]]),
                        "bid": bid,
                        "ask": ask,
                        "inverted": invert,
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
            code = target.strip().upper()  # keep US tickers as-is
            if self._is_us_stock(code):
                try:
                    df = ak.stock_us_daily(symbol=code)
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
                            "date": str(latest["date"]), "market": "US",
                        }
                except Exception as exc:
                    logger.debug("stock_price_fetch_branch_failed", error=str(exc))
            # A/H 股需要纯数字代码
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
                except Exception as exc:
                    logger.debug("stock_price_fetch_branch_failed", error=str(exc))
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
                except Exception as exc:
                    logger.debug("stock_price_fetch_branch_failed", error=str(exc))
        return {}

    async def fetch_documents(self, code: str, doc_type: str, limit: int) -> list[dict]:
        return []

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
