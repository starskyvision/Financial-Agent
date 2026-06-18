import os
import structlog
from celery import Celery
from celery.schedules import crontab

logger = structlog.get_logger()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery("rag_tasks", broker=REDIS_URL)

celery_app.conf.beat_schedule = {
    "fetch-research-reports": {
        "task": "services.rag.tasks.fetch_and_index_reports",
        "schedule": crontab(hour=2, minute=0),
    },
}
celery_app.conf.timezone = "Asia/Shanghai"


@celery_app.task
def fetch_and_index_reports():
    """每日凌晨 2:00 拉取最新研报并入库。"""
    import asyncio

    async def run():
        engine = None
        try:
            import akshare as ak
            df = ak.stock_research_report_em()
            if df is None or df.empty:
                logger.info("no_new_reports")
                return

            from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
            from sqlalchemy.orm import sessionmaker
            from services.rag.ingester import Ingester
            from services.db_utils import ensure_asyncpg_url

            DATABASE_URL = ensure_asyncpg_url()
            engine = create_async_engine(DATABASE_URL)
            async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

            ingester = Ingester(async_session)
            docs = []
            for _, row in df.head(50).iterrows():
                content = str(row.get("摘要", "") or row.get("内容", ""))
                if not content or len(content) < 50:
                    continue
                docs.append({
                    "content": content,
                    "company_code": str(row.get("股票代码", "")),
                    "doc_type": "report",
                    "doc_title": str(row.get("研报标题", "")),
                })

            if docs:
                total = await ingester.index_batch(docs)
                logger.info("reports_indexed", total=total)
        except Exception as e:
            logger.error("report_fetch_failed", error=str(e))
        finally:
            if engine is not None:
                await engine.dispose()

    asyncio.run(run())
