import os
import sys
import json
import structlog
import atexit
from dotenv import load_dotenv

# Ensure backend root is on sys.path when Celery runs standalone
_backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from celery import Celery
from services.env import env_int, env_str

load_dotenv()  # Celery worker 独立启动时需加载 .env

# ── PID 文件锁：防止重复启动 Celery Worker（仅在 Worker 启动时触发） ──
_PID_FILE = os.path.join(_backend_root, ".celery_worker.pid")


def _check_and_write_pid():
    """检查是否已有 Celery worker 在运行。若 PID 文件存在且进程存活则拒绝启动。"""
    if os.path.exists(_PID_FILE):
        try:
            with open(_PID_FILE) as f:
                old_pid = int(f.read().strip())
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x0400, False, old_pid)
            if handle:
                kernel32.CloseHandle(handle)
                print(f"ERROR: Celery worker already running (PID {old_pid}).")
                print(f"  Kill it first: taskkill //F //PID {old_pid}")
                print(f"  Or delete: {_PID_FILE}")
                sys.exit(1)
        except (ValueError, OSError):
            try:
                os.remove(_PID_FILE)
            except OSError:
                pass

    with open(_PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _cleanup_pid():
    try:
        if os.path.exists(_PID_FILE):
            os.remove(_PID_FILE)
    except OSError:
        pass



logger = structlog.get_logger()

REDIS_URL = env_str("REDIS_URL", "redis://localhost:6379/0")
TASK_TTL = env_int("TASK_TTL", "3600")
CELERY_RETRY_COUNTDOWN = env_int("CELERY_RETRY_COUNTDOWN", "10")

celery_app = Celery("financial_agent", broker=REDIS_URL, backend=REDIS_URL)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)

# ── PID 文件锁（仅 Worker 启动时触发，import 模块时不执行） ──
_pid_checked = False

import celery.signals

@celery.signals.worker_process_init.connect
def _on_worker_init(*args, **kwargs):
    global _pid_checked
    if not _pid_checked:
        _pid_checked = True
        _check_and_write_pid()

atexit.register(_cleanup_pid)


def _publish_progress(task_id: str, event_type: str, message: str = "", data: dict | None = None):
    """Publish a progress event to Redis pubsub AND persist it for late subscribers."""
    try:
        import redis
        r = redis.from_url(REDIS_URL, decode_responses=True)
        payload = {"type": event_type, "message": message, "task_id": task_id}
        if data:
            payload.update(data)
        payload_str = json.dumps(payload, ensure_ascii=False)
        # 1. Pubsub for live subscribers
        r.publish(f"task:{task_id}:events", payload_str)
        # 2. Append to a list so late-connecting subscribers can replay history
        r.rpush(f"task:{task_id}:progress_log", payload_str)
        r.expire(f"task:{task_id}:progress_log", TASK_TTL)
        r.close()
    except Exception as e:
        logger.warning("progress_publish_failed", task_id=task_id, error=str(e))


# Human-readable labels for each graph node
NODE_LABELS: dict[str, str] = {
    "intent_classifier":  "意图分类",
    "data_collector":     "数据收集",
    "financial_analyzer": "财务分析",
    "sentiment_analyzer": "舆情解读",
    "report_generator":   "报告生成",
    "rewriter":           "事实校验",
    "output":             "输出编排",
}

# Comprehensive pipeline: ordered list of expected nodes
PIPELINE_NODES = [
    "intent_classifier", "data_collector", "financial_analyzer",
    "sentiment_analyzer", "report_generator", "output",
]


@celery_app.task(bind=True, max_retries=env_int("CELERY_MAX_RETRIES", "2"))
def run_comprehensive_analysis(self, task_id: str, company_code: str, report_date: str = "", company_name: str = ""):
    """Celery async task: execute full pipeline with per-agent progress events."""
    import asyncio, sys, os as _os
    _backend = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    if _backend not in sys.path:
        sys.path.insert(0, _backend)
    from state import make_initial_state
    from graph import build_graph

    logger.info("celery_task_start", task_id=task_id, code=company_code, name=company_name)

    def _emit(stage: str, msg: str, **extra):
        _publish_progress(task_id, "progress", msg, {"stage": stage, **extra})

    try:
        state = make_initial_state(task_id)
        state["intent"] = "comprehensive"
        state["company_code"] = company_code
        state["company_name"] = company_name or company_code
        state["report_date"] = report_date

        graph = build_graph()

        # ── Run graph with per-node streaming ──
        async def run():
            completed: set[str] = set()
            retry_rounds = 0
            final = state

            _emit("pipeline", "✅ 意图分类 | 🔄 数据收集 进行中... | ⏳ 财务分析 | ⏳ 舆情解读 | ⏳ 报告生成 | ⏳ 输出")

            # astream yields {node_name: state_update} per node execution
            async for chunk in graph.astream(state, stream_mode="updates"):
                for node_name in chunk:
                    final = chunk[node_name]  # state update from this node
                    completed.add(node_name)

                    if node_name == "rewriter":
                        retry_rounds += 1

                    # Build status line
                    status_parts = []
                    for n in PIPELINE_NODES:
                        label = NODE_LABELS.get(n, n)
                        if n in completed:
                            status_parts.append(f"✅ {label}")
                        else:
                            next_up = _next_node(completed, PIPELINE_NODES)
                            if n == next_up:
                                status_parts.append(f"🔄 {label} 进行中...")
                            else:
                                status_parts.append(f"⏳ {label}")

                    status = " | ".join(status_parts)
                    if retry_rounds > 0:
                        status += f" | 🔄 第{retry_rounds}轮校验"
                    _emit(node_name, status)

            return final, len(completed), retry_rounds

        final_state, node_count, retries = asyncio.run(run())

        # ── Store result ──
        import redis
        r = redis.from_url(REDIS_URL, decode_responses=True)
        report = (final_state or {}).get("draft_report") or ""
        result_data = {
            "task_id": task_id, "company_code": company_code,
            "status": "done",
            "result": {"draft_report": report, "chat_reply": (final_state or {}).get("chat_reply") or ""},
        }
        r.setex(f"task:{task_id}", TASK_TTL, json.dumps(result_data, ensure_ascii=False))
        r.close()

        _publish_progress(task_id, "done",
                          f"✅ 全部完成 — {node_count} 个 Agent 节点 | {retries} 轮校验 | 报告 {len(report)} 字",
                          {"stage": "completed", "report_length": len(report)})

        logger.info("celery_task_done", task_id=task_id)
        return {"status": "done", "task_id": task_id}
    except Exception as e:
        logger.error("celery_task_error", task_id=task_id, error=str(e))
        _publish_progress(task_id, "failed", f"任务失败: {str(e)}", {"stage": "failed"})
        try:
            # Mark task as failed in Redis so frontend sees "failed" not "pending"
            import redis
            r = redis.from_url(REDIS_URL, decode_responses=True)
            existing = r.get(f"task:{task_id}")
            if existing:
                data = json.loads(existing)
                data["status"] = "failed"
                data["error"] = str(e)
                r.setex(f"task:{task_id}", TASK_TTL, json.dumps(data, ensure_ascii=False))
            r.close()
        except Exception:
            pass
        raise self.retry(exc=e, countdown=CELERY_RETRY_COUNTDOWN)


def _next_node(completed: set[str], pipeline: list[str]) -> str | None:
    """Return the first pipeline node not yet completed."""
    for n in pipeline:
        if n not in completed:
            return n
    return None
