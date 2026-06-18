import os
import json
import uuid
import structlog
import redis.asyncio as redis
from services.env import env_str

logger = structlog.get_logger()

REDIS_URL = env_str("REDIS_URL", "redis://localhost:6379/0")

# Import TASK_TTL from celery_app (single source of truth)
from services.task_queue.celery_app import TASK_TTL  # noqa: E402


_redis_client: redis.Redis | None = None


async def get_redis():
    """Return a shared Redis client (singleton) to avoid connection pool proliferation."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


class TaskManager:
    @staticmethod
    async def _check_worker() -> bool:
        """检查是否有 Celery worker 在线。超时 2 秒。"""
        try:
            import asyncio
            from services.task_queue.celery_app import celery_app
            inspect = celery_app.control.inspect(timeout=2.0)
            stats = await asyncio.to_thread(inspect.stats)
            return stats is not None and len(stats) > 0
        except Exception:
            return False

    @staticmethod
    async def submit(company_code: str, report_date: str = "", company_name: str = "") -> str:
        task_id = str(uuid.uuid4())[:8]

        # 检查 Celery worker 是否在线
        if not await TaskManager._check_worker():
            logger.error("celery_no_worker", task_id=task_id)
            raise RuntimeError(
                "任务队列未启动。请先运行 Celery Worker：\n"
                "cd backend && celery -A services.task_queue.celery_app worker -P solo -n worker1"
            )

        try:
            r = await get_redis()
            await r.setex(f"task:{task_id}", TASK_TTL, json.dumps({
                "task_id": task_id, "company_code": company_code,
                "company_name": company_name,
                "status": "pending", "result": None,
            }, ensure_ascii=False))
            await r.publish(f"task:{task_id}:events", json.dumps({
                "type": "status", "status": "pending", "task_id": task_id,
            }, ensure_ascii=False))
        except Exception as e:
            logger.warning("redis_submit_failed", error=str(e))
        try:
            from services.task_queue.celery_app import run_comprehensive_analysis
            run_comprehensive_analysis.delay(task_id, company_code, report_date, company_name)
        except Exception as e:
            logger.warning("celery_submit_failed", error=str(e))
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
        await r.set(f"task:{task_id}:cancelled", "1", ex=TASK_TTL)
        # Publish cancellation event for SSE subscribers
        await r.publish(f"task:{task_id}:events", json.dumps({
            "type": "failed", "message": "任务已取消", "task_id": task_id,
        }, ensure_ascii=False))
        from services.task_queue.celery_app import celery_app
        celery_app.control.revoke(task_id, terminate=True)
        logger.info("task_cancelled", task_id=task_id)
        return True
