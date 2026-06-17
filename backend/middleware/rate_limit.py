import os
from fastapi import Request, HTTPException
from services.task_queue.manager import get_redis

RATE_LIMIT = int(os.getenv("RATE_LIMIT", "60"))

PUBLIC_PATHS = {"/api/v1/health", "/", "/docs", "/openapi.json"}


async def rate_limit_middleware(request: Request, call_next):
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    if RATE_LIMIT <= 0:
        return await call_next(request)

    client_key = request.headers.get(
        "X-API-Key",
        request.client.host if request.client else "unknown",
    )
    redis_key = f"rate_limit:{client_key}"

    try:
        r = await get_redis()
        current = await r.incr(redis_key)
        if current == 1:
            await r.expire(redis_key, 60)
        if current > RATE_LIMIT:
            raise HTTPException(status_code=429, detail="rate limit exceeded")
    except HTTPException:
        raise
    except Exception:
        # Redis 不可用时放行（降级策略）
        pass

    return await call_next(request)
