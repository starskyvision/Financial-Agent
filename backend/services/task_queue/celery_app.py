import os
import json
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


def _publish_progress(task_id: str, event_type: str, message: str = "", data: dict | None = None):
    """Publish a progress event to the task's Redis pubsub channel."""
    try:
        import redis
        r = redis.from_url(REDIS_URL, decode_responses=True)
        payload = {"type": event_type, "message": message, "task_id": task_id}
        if data:
            payload.update(data)
        r.publish(f"task:{task_id}:events", json.dumps(payload, ensure_ascii=False))
        r.close()
    except Exception as e:
        logger.warning("progress_publish_failed", task_id=task_id, error=str(e))


@celery_app.task(bind=True, max_retries=2)
def run_comprehensive_analysis(self, task_id: str, company_code: str, report_date: str = ""):
    """Celery async task: execute comprehensive full-pipeline analysis with progress events."""
    import asyncio
    from state import make_initial_state
    from graph import build_graph

    logger.info("celery_task_start", task_id=task_id, code=company_code)
    _publish_progress(task_id, "progress", "任务已提交，开始执行...",
                      {"stage": "submitted", "company_code": company_code})

    try:
        state = make_initial_state(task_id)
        state["intent"] = "comprehensive"
        state["company_code"] = company_code
        state["report_date"] = report_date

        _publish_progress(task_id, "progress", "正在拉取数据...", {"stage": "collecting"})

        graph = build_graph()

        _publish_progress(task_id, "progress", "正在执行分析流水线...", {"stage": "analyzing"})

        async def run():
            return await graph.ainvoke(state)

        final_state = asyncio.run(run())

        # Update Redis with final result
        import redis
        r = redis.from_url(REDIS_URL, decode_responses=True)
        result_data = {
            "task_id": task_id, "company_code": company_code,
            "status": "done",
            "result": {
                "draft_report": final_state.get("draft_report", ""),
                "chat_reply": final_state.get("chat_reply", ""),
            },
        }
        r.setex(f"task:{task_id}", 3600, json.dumps(result_data, ensure_ascii=False))
        r.close()

        _publish_progress(task_id, "done", "分析完成",
                          {"stage": "completed", "report_length": len(final_state.get("draft_report", ""))})

        logger.info("celery_task_done", task_id=task_id)
        return {"status": "done", "task_id": task_id}
    except Exception as e:
        logger.error("celery_task_error", task_id=task_id, error=str(e))
        _publish_progress(task_id, "failed", f"任务失败: {str(e)}", {"stage": "failed"})
        raise self.retry(exc=e, countdown=10)
