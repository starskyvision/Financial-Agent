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


app = FastAPI(title="金融多智能体协作系统", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.post("/api/v1/chat")
async def chat(request: ChatRequest):
    """快速对话通道 - SSE 流式返回"""
    task_id = str(uuid.uuid4())[:8]
    logger.info("chat_request", task_id=task_id, message=request.message[:50])

    from agents.intent_classifier.classifier import classify_intent
    intent_result = await classify_intent(request.message)

    if intent_result.intent == "comprehensive":
        tid = await TaskManager.submit(intent_result.company_code, intent_result.report_date)
        return {"task_id": tid, "status": "accepted",
                "message": "综合分析已转为异步任务"}

    state = make_initial_state(task_id)
    state["intent"] = intent_result.intent
    state["company_code"] = intent_result.company_code
    state["company_name"] = intent_result.company_name
    state["report_date"] = intent_result.report_date

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
    health_status = {"status": "healthy", "redis": "unknown"}
    try:
        r = await get_redis()
        await r.ping()
        health_status["redis"] = "connected"
    except Exception:
        health_status["redis"] = "disconnected"
    return health_status


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
