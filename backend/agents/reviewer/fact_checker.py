import os
import re
import structlog
from constants.metrics import FACT_CHECK_MAP

logger = structlog.get_logger()
FACT_CHECK_DEVIATION_TOLERANCE = float(os.getenv("FACT_CHECK_TOLERANCE", "0.01"))  # 1% default

# Expanded patterns to catch more claim formats in generated reports
CLAIM_PATTERNS = [
    # Percentage metrics: "ROE为12.3%", "ROE 12.3%", "ROE=12.3%"
    (r'(ROE|ROA|净利率|毛利率|资产负债率)\s*[为=：:]?\s*(\d+\.?\d*)\s*%', 'percent', 100),
    # Billion-unit metrics: "净利润50亿元", "营收100亿", "净利润56.78亿"
    (r'(净利润|营收|营业总收入)\s*[为=：:]?\s*(\d+\.?\d*)\s*亿', 'billions', 1),
    # Cashflow: "现金流12.3亿元", "经营现金流5亿", "每股经营现金流2.5"
    (r'(经营现金流|现金流|每股经营现金流)\s*[为=：:]?\s*(\d+\.?\d*)\s*(?:亿|元)?', 'cashflow', 1),
    # Ratio-style: "净利率 = 0.50", "净利率: 0.50" (raw decimal form from Dupont)
    (r'(净利率|毛利率)\s*[为=：:]?\s*(\d+\.\d{2,4})\b(?!\s*%)', 'ratio', 1),
]


async def verify_facts(report: str, company_code: str, db_session=None,
                       source_metrics: dict | None = None) -> list[str]:
    """程序化事实核对。从报告中正则提取数值断言，与源数据比对，偏差 >1% 报错。

    Three-tier source lookup:
    1. DB session (when available — production path)
    2. source_metrics dict (when provided — inline metrics from current fetch)
    3. Returns empty if neither is available
    """
    errors = []
    for pattern, unit_type, divisor in CLAIM_PATTERNS:
        for match in re.finditer(pattern, report):
            metric_cn = match.group(1)
            report_value = float(match.group(2))
            if unit_type == "percent":
                report_value = report_value / divisor

            metric_name = FACT_CHECK_MAP.get(metric_cn)
            if not metric_name:
                continue

            source_value = None

            # Tier 1: DB lookup (extension point — requires MySQL)
            if db_session is not None:
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

            # Tier 2: Inline source_metrics fallback
            if source_value is None and source_metrics:
                source_value = source_metrics.get(metric_name)
                if source_value is not None:
                    source_value = float(source_value)

            if source_value is not None and source_value != 0:
                deviation = abs(report_value - source_value) / abs(source_value)
                if deviation > FACT_CHECK_DEVIATION_TOLERANCE:
                    errors.append(
                        f"{metric_cn}: 报告值 {report_value:.4f}，源数据 {source_value:.4f}，偏差 {deviation:.1%}"
                    )
            elif source_value is not None and source_value == 0 and report_value != 0:
                # Zero in source but non-zero in report → likely hallucination
                errors.append(
                    f"{metric_cn}: 报告值 {report_value:.4f}，源数据为 0（疑似编造数据）"
                )

    logger.info("fact_check_done", errors=len(errors))
    return errors
