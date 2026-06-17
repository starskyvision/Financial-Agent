import os
import json
import uuid
import structlog
import redis.asyncio as redis

logger = structlog.get_logger()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


async def get_redis():
    return redis.from_url(REDIS_URL, decode_responses=True)


class TaskManager:
    @staticmethod
    async def submit(company_code: str, report_date: str = "") -> str:
        task_id = str(uuid.uuid4())[:8]
        try:
            r = await get_redis()
            await r.setex(f"task:{task_id}", 3600, json.dumps({
                "task_id": task_id, "company_code": company_code,
                "status": "pending", "result": None,
            }, ensure_ascii=False))
            # Publish initial status event for SSE subscribers
            await r.publish(f"task:{task_id}:events", json.dumps({
                "type": "status", "status": "pending", "task_id": task_id,
            }, ensure_ascii=False))
        except Exception as e:
            logger.warning("redis_submit_failed", error=str(e))
            # Redis 不可用时仍返回 task_id，降级为内存模式
        try:
            from services.task_queue.celery_app import run_comprehensive_analysis
            run_comprehensive_analysis.delay(task_id, company_code, report_date)
        except Exception as e:
            logger.warning("celery_submit_failed", error=str(e))
            # Publish failure if Celery is unavailable
            try:
                r = await get_redis()
                await r.publish(f"task:{task_id}:events", json.dumps({
                    "type": "failed", "message": f"任务队列不可用: {str(e)}", "task_id": task_id,
                }, ensure_ascii=False))
            except Exception:
                pass
        logger.info("task_submitted", task_id=task_id)
        return task_id

    @staticmethod
    async def get_status(task_id: str) -> dict:
        try:
            r = await get_redis()
            data = await r.get(f"task:{task_id}")
            if data:
                return json.loads(data)
            return {"task_id": task_id, "status": "not_found"}
        except Exception as e:
            logger.warning("redis_get_status_error", task_id=task_id, error=str(e))
            return {"task_id": task_id, "status": "not_found"}

    @staticmethod
    async def cancel(task_id: str) -> bool:
        r = await get_redis()
        await r.set(f"task:{task_id}:cancelled", "1", ex=3600)
        # Publish cancellation event for SSE subscribers
        await r.publish(f"task:{task_id}:events", json.dumps({
            "type": "failed", "message": "任务已取消", "task_id": task_id,
        }, ensure_ascii=False))
        from services.task_queue.celery_app import celery_app
        celery_app.control.revoke(task_id, terminate=True)
        logger.info("task_cancelled", task_id=task_id)
        return True
