import re
import structlog
from constants.metrics import FACT_CHECK_MAP

logger = structlog.get_logger()

CLAIM_PATTERNS = [
    (r'(ROE|ROA)[^\d]*(\d+\.?\d*)\s*%', 'percent', 100),
    (r'(净利润|营收|净利率|毛利率)[^\d]*(\d+\.?\d*)\s*[亿元]', 'billions', 1),
    (r'(现金流)[^\d]*(\d+\.?\d*)\s*[亿元]', 'billions', 1),
]


async def verify_facts(report: str, company_code: str, db_session=None) -> list[str]:
    """纯 Python 程序化事实核对。从报告中正则提取数值断言，与 MySQL 源数据比对，偏差 >1% 报错。"""
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

    logger.info("fact_check_done", errors=len(errors))
    return errors
