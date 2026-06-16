import structlog
from state import Anomaly

logger = structlog.get_logger()

ANOMALY_WARNING_THRESHOLD = 0.30
ANOMALY_CRITICAL_THRESHOLD = 0.50
TRACKED_METRICS = ["revenue", "net_profit", "roe", "gross_margin", "net_margin", "operating_cashflow"]


async def detect_anomalies(code: str, current_metrics: dict, db_session=None) -> list[Anomaly]:
    """检测同比异动。MVP: 无历史数据时返回空列表。"""
    anomalies = []
    if db_session is None:
        logger.info("anomaly_skip_no_db", code=code)
        return anomalies

    for metric in TRACKED_METRICS:
        if metric not in current_metrics or current_metrics[metric] is None:
            continue
        current_val = current_metrics[metric]
        try:
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

    logger.info("anomaly_detection_done", code=code, anomalies=len(anomalies))
    return anomalies
