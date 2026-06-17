import os
from fastapi import Request
from fastapi.responses import JSONResponse

API_KEY = os.getenv("API_KEY", "")
IP_WHITELIST = [
    ip.strip() for ip in os.getenv("IP_WHITELIST", "").split(",") if ip.strip()
]

PUBLIC_PATHS = {"/api/v1/health", "/", "/docs", "/openapi.json"}


async def auth_middleware(request: Request, call_next):
    # IP 白名单（可选）
    if IP_WHITELIST:
        client_ip = request.client.host if request.client else "unknown"
        if client_ip not in IP_WHITELIST:
            return JSONResponse(status_code=403, content={"error": "ip not allowed"})

    # 公开路径不校验
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    # API Key 未配置时跳过（开发环境）
    if not API_KEY:
        return await call_next(request)

    # 校验 API Key
    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})

    return await call_next(request)
