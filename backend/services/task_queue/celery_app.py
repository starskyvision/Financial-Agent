import os
import structlog
from celery import Celery

logger = structlog.get_logger()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("financial_agent", broker=REDIS_URL, backend=REDIS_URL)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)


@celery_app.task(bind=True, max_retries=2)
def run_comprehensive_analysis(self, task_id: str, company_code: str, report_date: str = ""):
    """Celery async task: execute comprehensive full-pipeline analysis"""
    import asyncio
    from state import make_initial_state
    from graph import build_graph

    logger.info("celery_task_start", task_id=task_id, code=company_code)
    try:
        state = make_initial_state(task_id)
        state["intent"] = "comprehensive"
        state["company_code"] = company_code
        state["report_date"] = report_date

        graph = build_graph()

        async def run():
            return await graph.ainvoke(state)

        final_state = asyncio.run(run())

        import json
        import redis
        r = redis.from_url(REDIS_URL, decode_responses=True)
        r.setex(f"task:{task_id}", 3600, json.dumps({
            "task_id": task_id, "company_code": company_code,
            "status": "done",
            "result": {
                "draft_report": final_state.get("draft_report", ""),
                "chat_reply": final_state.get("chat_reply", ""),
            },
        }, ensure_ascii=False))

        logger.info("celery_task_done", task_id=task_id)
        return {"status": "done", "task_id": task_id}
    except Exception as e:
        logger.error("celery_task_error", task_id=task_id, error=str(e))
        raise self.retry(exc=e, countdown=10)
