import os
import structlog
from state import Anomaly
from constants.metrics import DEFAULT_METRICS_FETCH

logger = structlog.get_logger()

ANOMALY_WARNING_THRESHOLD = float(os.getenv("ANOMALY_WARNING_THRESHOLD", "0.30"))
ANOMALY_CRITICAL_THRESHOLD = float(os.getenv("ANOMALY_CRITICAL_THRESHOLD", "0.50"))
TRACKED_METRICS = DEFAULT_METRICS_FETCH[:6]  # 复用共享指标列表

# --- Rule-based thresholds for when no historical data is available ---
# These flag extreme values that warrant analyst attention regardless of trend.
RULE_THRESHOLDS = {
    "roe":             {"critical_low": -0.10, "warning_low": 0.0},    # ROE < 0% is concerning
    "net_margin":      {"critical_low": -0.05, "warning_low": 0.0},
    "gross_margin":    {"critical_low": 0.0,   "warning_low": 0.05},
    "debt_ratio":      {"critical_high": 0.85, "warning_high": 0.70},  # very high leverage
}


async def _fetch_historical_from_akshare(code: str) -> dict:
    """Try to fetch the prior-period financials from AKShare for YoY comparison."""
    try:
        from services.data_sources.akshare_adapter import AKShareAdapter
        from services.data_sources.base import DataSourceConfig

        adapter = AKShareAdapter(DataSourceConfig(source_type="akshare", timeout=30))
        # Fetch all metrics for the company
        result = await adapter.fetch_financials(code, "", TRACKED_METRICS)
        await adapter.close()
        return result
    except Exception as e:
        logger.info("anomaly_akshare_fallback_failed", code=code, error=str(e))
        return {}


async def detect_anomalies(code: str, current_metrics: dict, db_session=None) -> list[Anomaly]:
    """检测同比异动。

    Three-tier strategy:
    1. DB comparison (when db_session is available)
    2. AKShare historical fetch (fallback, fetches prior period)
    3. Rule-based threshold checks (final fallback)
    """
    anomalies = []

    # --- Tier 1: DB-based YoY comparison (extension point — requires MySQL) ---
    if db_session is not None:
        for metric in TRACKED_METRICS:
            if metric not in current_metrics or current_metrics[metric] is None:
                continue
            current_val = current_metrics[metric]
            try:
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
                if abs_change > ANOMALY_CRITICAL_THRESHOLD:
                    severity = "critical"
                elif abs_change > ANOMALY_WARNING_THRESHOLD:
                    severity = "warning"
                else:
                    continue

                anomalies.append(Anomaly(
                    metric_name=metric, current_value=current_val,
                    yoy_value=yoy_val, change_pct=change_pct, severity=severity,
                ))

        logger.info("anomaly_detection_db_done", code=code, anomalies=len(anomalies))
        return anomalies

    # --- Tier 2: AKShare historical fetch ---
    if code:
        historical = await _fetch_historical_from_akshare(code)
        if historical:
            for metric in TRACKED_METRICS:
                if metric not in current_metrics or metric not in historical:
                    continue
                current_val = current_metrics[metric]
                yoy_val = historical[metric]
                if current_val is None or yoy_val is None or yoy_val == 0:
                    continue
                change_pct = round((current_val - yoy_val) / abs(yoy_val), 4)
                abs_change = abs(change_pct)
                if abs_change > ANOMALY_CRITICAL_THRESHOLD:
                    severity = "critical"
                elif abs_change > ANOMALY_WARNING_THRESHOLD:
                    severity = "warning"
                else:
                    continue
                anomalies.append(Anomaly(
                    metric_name=metric, current_value=current_val,
                    yoy_value=yoy_val, change_pct=change_pct, severity=severity,
                ))

            logger.info("anomaly_detection_akshare_done", code=code, anomalies=len(anomalies))
            return anomalies

    # --- Tier 3: Rule-based threshold checks ---
    for metric, thresholds in RULE_THRESHOLDS.items():
        val = current_metrics.get(metric)
        if val is None:
            continue
        severity = None
        change_pct = None
        if "critical_low" in thresholds and val < thresholds["critical_low"]:
            severity = "critical"
            change_pct = round((val - thresholds["critical_low"]) / abs(thresholds["critical_low"]), 4) if thresholds["critical_low"] != 0 else -1.0
        elif "warning_low" in thresholds and val < thresholds["warning_low"]:
            severity = "warning"
            change_pct = round((val - thresholds["warning_low"]) / abs(thresholds["warning_low"]), 4) if thresholds["warning_low"] != 0 else -0.5
        elif "critical_high" in thresholds and val > thresholds["critical_high"]:
            severity = "critical"
            change_pct = round((val - thresholds["critical_high"]) / thresholds["critical_high"], 4)
        elif "warning_high" in thresholds and val > thresholds["warning_high"]:
            severity = "warning"
            change_pct = round((val - thresholds["warning_high"]) / thresholds["warning_high"], 4)

        if severity:
            anomalies.append(Anomaly(
                metric_name=metric, current_value=val,
                yoy_value=None, change_pct=change_pct, severity=severity,
            ))

    logger.info("anomaly_detection_rule_done", code=code, anomalies=len(anomalies))
    return anomalies
