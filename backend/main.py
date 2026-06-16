import os
import json
import uuid
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from state import make_initial_state
from graph import build_graph
from services.task_queue.manager import TaskManager, get_redis

logger = structlog.get_logger()


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    attachments: list[str] = []


class TaskRequest(BaseModel):
    company_code: str
    report_date: str = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app_startup")
    yield
    logger.info("app_shutdown")


from fastapi.responses import RedirectResponse, HTMLResponse

app = FastAPI(title="金融多智能体协作系统", version="0.1.0", lifespan=lifespan)
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["*"], allow_headers=["*"])


@app.get("/", response_class=HTMLResponse)
async def root():
    frontend = os.getenv("FRONTEND_URL", "http://localhost:5173")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>金融多智能体协作系统</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 800px; margin: 60px auto; padding: 0 20px; background: #f5f7fa; }}
  h1 {{ font-size: 28px; color: #1a1a2e; }}
  .links {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 24px 0; }}
  .links a {{ padding: 12px 24px; background: #4a90d9; color: #fff; text-decoration: none; border-radius: 8px; }}
  code {{ background: #e8e8e8; padding: 2px 6px; border-radius: 4px; }}
</style>
</head>
<body>
<h1>金融多智能体协作系统</h1>
<p>基于 LangGraph 的多 Agent 投研辅助 Copilot</p>
<div class="links">
  <a href="/docs">Swagger API</a>
  <a href="{frontend}">前端界面</a>
  <a href="/api/v1/health">健康检查</a>
</div>
<p>启动前端: <code>cd frontend && npm run dev</code></p>
</body>
</html>"""


@app.post("/api/v1/chat")
async def chat(request: ChatRequest):
    """快速对话通道 - SSE 流式返回"""
    task_id = str(uuid.uuid4())[:8]
    logger.info("chat_request", task_id=task_id, message=request.message[:50])

    from agents.intent_classifier.classifier import classify_intent
    try:
        intent_result = await classify_intent(request.message)
    except Exception as e:
        logger.error("intent_classification_failed", error=str(e))
        err_text = f"Intent classification failed: {str(e)}"
        return StreamingResponse(
            iter([f"data: {json.dumps({'error': err_text})}\n\n"]),
            media_type="text/event-stream"
        )

    # chitchat → LLM 直接回复
    # 市场行情查询（金价/股价等）→ 走 data collector，不走 chitchat
    if intent_result.intent == "chitchat":
        DEFAULT_REPLY = (
            "Hello! I am a financial research AI assistant. "
            "Please provide a stock code or company name, e.g. analyze Moutai profitability."
        )
        FALLBACK_REPLY = (
            "Hello! I am a financial AI assistant. Try:\\n"
            "- Analyze stock profitability\\n"
            "- Latest news for a company\\n"
            "- Generate comprehensive research report"
        )
        CHITCHAT_SYSTEM = (
            "You are a helpful financial assistant. Answer the user's question directly and concisely. "
            "For prices (gold, commodities, currencies, indices), provide approximate levels based on "
            "your knowledge and note that they are indicative. "
            "For non-financial questions, respond naturally. "
            "Reply in the same language as the user (Chinese or English)."
        )
        async def chitchat_generator():
            try:
                from services.llm_service import get_llm_service
                llm = get_llm_service()
                result = await llm.invoke("default", [
                    {"role": "system", "content": CHITCHAT_SYSTEM},
                    {"role": "user", "content": request.message},
                ])
                reply = result.get("content", "") or DEFAULT_REPLY
            except Exception as e:
                logger.error("chitchat_llm_failed", error=str(e))
                reply = FALLBACK_REPLY
            intent_data = json.dumps({"intent": "chitchat"})
            yield f"event: intent\ndata: {intent_data}\n\n"
            for line in reply.split("\n"):
                chunk = json.dumps({"text": line + "\n"})
                yield f"event: chunk\ndata: {chunk}\n\n"
            yield f"event: done\ndata: {json.dumps({'task_id': task_id})}\n\n"
        return StreamingResponse(chitchat_generator(), media_type="text/event-stream")

    # 降级为 comprehensive 但没有有效 company_code 时，返回提示
    if intent_result.intent == "comprehensive" and not intent_result.company_code:
        hint_text = 'Please provide stock code or company name, e.g. "600519 financial analysis".'
        async def hint_generator():
            chunk = json.dumps({"text": hint_text})
            yield f"event: chunk\ndata: {chunk}\n\n"
            done_data = json.dumps({"task_id": task_id})
            yield f"event: done\ndata: {done_data}\n\n"
        return StreamingResponse(hint_generator(), media_type="text/event-stream")

    state = make_initial_state(task_id)
    state["intent"] = intent_result.intent
    state["company_code"] = intent_result.company_code
    state["company_name"] = intent_result.company_name
    state["report_date"] = intent_result.report_date
    state["query_type"] = intent_result.query_type

    async def event_generator():
        graph = build_graph()
        try:
            yield f"event: intent\ndata: {json.dumps({'intent': intent_result.intent})}\n\n"
            final_state = await graph.ainvoke(state)
            chat_reply = final_state.get("chat_reply", "")
            for line in chat_reply.split("\n"):
                chunk_data = json.dumps({"text": line + "\n"})
                yield f"event: chunk\ndata: {chunk_data}\n\n"
            yield f"event: done\ndata: {json.dumps({'task_id': task_id})}\n\n"
        except Exception as e:
            logger.error("chat_error", task_id=task_id, error=str(e))
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/v1/tasks")
async def submit_task(request: TaskRequest):
    if not request.company_code:
        raise HTTPException(status_code=400, detail="company_code is required")
    task_id = await TaskManager.submit(request.company_code, request.report_date)
    return {"task_id": task_id, "status": "pending"}


@app.get("/api/v1/tasks/{task_id}")
async def get_task_status(task_id: str):
    return await TaskManager.get_status(task_id)


@app.get("/api/v1/tasks/{task_id}/stream")
async def stream_task_progress(task_id: str):
    async def event_generator():
        r = await get_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe(f"task:{task_id}:events")
        try:
            status = await TaskManager.get_status(task_id)
            yield f"event: status\ndata: {json.dumps(status)}\n\n"
            if status.get("status") in ("done", "failed"):
                return
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
                    try:
                        event_data = json.loads(message['data'])
                        if event_data.get("type") in ("done", "failed"):
                            break
                    except json.JSONDecodeError:
                        pass
        finally:
            await pubsub.unsubscribe(f"task:{task_id}:events")

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/v1/reports/{task_id}")
async def get_report(task_id: str):
    status = await TaskManager.get_status(task_id)
    if status.get("status") != "done":
        raise HTTPException(status_code=404, detail="Report not ready")
    return {"task_id": task_id, "report": status.get("result", {}).get("draft_report", "")}


@app.get("/api/v1/health")
async def health():
    health_status = {
        "status": "healthy",
        "redis": "unknown",
        "mysql": "unknown",
        "milvus": "unknown",
    }
    # Redis
    try:
        r = await get_redis()
        await r.ping()
        health_status["redis"] = "connected"
    except Exception:
        health_status["redis"] = "disconnected"
    # MySQL
    try:
        import os, pymysql
        conn = pymysql.connect(
            host=os.getenv("MYSQL_HOST", "localhost"),
            port=int(os.getenv("MYSQL_PORT", "3307")),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.getenv("MYSQL_PASSWORD", ""),
            database=os.getenv("MYSQL_DATABASE", "financial_agent"),
            connect_timeout=3,
        )
        conn.ping()
        conn.close()
        health_status["mysql"] = "connected"
    except Exception:
        health_status["mysql"] = "disconnected"
    # Milvus
    try:
        from pymilvus import connections
        m_host = os.getenv("MILVUS_HOST", "localhost")
        m_port = os.getenv("MILVUS_PORT", "19530")
        connections.connect(host=m_host, port=m_port, timeout=3)
        connections.disconnect("default")
        health_status["milvus"] = "connected"
    except Exception:
        health_status["milvus"] = "disconnected"

    return health_status


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
