import os
import time
import asyncio
import structlog
from openai import AsyncOpenAI
from collections import deque

logger = structlog.get_logger()

AGENT_LLM_CONFIG = {
    "intent_classifier":    {"model": "deepseek-chat", "temperature": 0.0, "max_tokens": 512},
    "financial_analyzer":   {"model": "deepseek-chat", "temperature": 0.3, "max_tokens": 2048},
    "sentiment_analyzer":   {"model": "deepseek-chat", "temperature": 0.3, "max_tokens": 2048},
    "reviewer":             {"model": "deepseek-chat", "temperature": 0.5, "max_tokens": 8192},
    "default":              {"model": "deepseek-chat", "temperature": 0.2, "max_tokens": 2048},
}

FALLBACK_CONFIG = {
    "model": os.getenv("QWEN_MODEL", "qwen-turbo"),
    "api_base": os.getenv("QWEN_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
}


class SimpleRateLimiter:
    """简易 token bucket 限流器"""
    def __init__(self, max_calls_per_minute: int = 30):
        self.max_calls = max_calls_per_minute
        self.timestamps: deque[float] = deque()

    async def acquire(self):
        now = time.time()
        while self.timestamps and self.timestamps[0] < now - 60:
            self.timestamps.popleft()
        if len(self.timestamps) >= self.max_calls:
            wait = self.timestamps[0] + 60 - now
            if wait > 0:
                logger.info("rate_limit_wait", seconds=wait)
                await asyncio.sleep(wait)
        self.timestamps.append(time.time())


class LLMService:
    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        base_url = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
        self._primary = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._fallback: AsyncOpenAI | None = None
        if os.getenv("QWEN_API_KEY"):
            self._fallback = AsyncOpenAI(
                api_key=os.getenv("QWEN_API_KEY"),
                base_url=FALLBACK_CONFIG["api_base"],
            )
        self._rate_limiter = SimpleRateLimiter(max_calls_per_minute=30)

    async def invoke(
        self, agent: str, messages: list[dict],
        tools: list[dict] | None = None,
        response_format: type | None = None,
    ) -> dict:
        """统一 LLM 调用入口"""
        config = AGENT_LLM_CONFIG.get(agent, AGENT_LLM_CONFIG["default"])
        await self._rate_limiter.acquire()

        t0 = time.time()
        last_error = None
        for attempt in range(3):
            try:
                kwargs = {
                    "model": config["model"],
                    "messages": messages,
                    "temperature": config["temperature"],
                    "max_tokens": config["max_tokens"],
                }
                if tools:
                    kwargs["tools"] = tools
                if response_format:
                    kwargs["response_format"] = {"type": "json_object"}

                resp = await self._primary.chat.completions.create(**kwargs)
                elapsed = (time.time() - t0) * 1000
                choice = resp.choices[0]

                result = {
                    "content": choice.message.content,
                    "tool_calls": choice.message.tool_calls,
                    "model": resp.model,
                    "usage": {
                        "prompt_tokens": resp.usage.prompt_tokens,
                        "completion_tokens": resp.usage.completion_tokens,
                    },
                }
                logger.info("llm_call_done", agent=agent, latency_ms=int(elapsed),
                            tokens=resp.usage.total_tokens)
                return result

            except Exception as e:
                last_error = e
                logger.warning("llm_call_retry", agent=agent, attempt=attempt, error=str(e))
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                # 最后一次重试尝试 fallback
                if attempt == 1 and self._fallback:
                    logger.info("llm_fallback_switch", from_model=config["model"],
                                to_model=FALLBACK_CONFIG["model"])
                    try:
                        kwargs["model"] = FALLBACK_CONFIG["model"]
                        resp = await self._fallback.chat.completions.create(**kwargs)
                        elapsed = (time.time() - t0) * 1000
                        return {
                            "content": resp.choices[0].message.content,
                            "tool_calls": resp.choices[0].message.tool_calls,
                            "model": resp.model,
                            "usage": {"prompt_tokens": resp.usage.prompt_tokens,
                                       "completion_tokens": resp.usage.completion_tokens},
                        }
                    except Exception as fe:
                        last_error = fe
                        logger.error("llm_fallback_failed", error=str(fe))

        logger.error("llm_call_exhausted", agent=agent, error=str(last_error))
        return {"content": "", "tool_calls": None, "model": "none",
                "usage": {"prompt_tokens": 0, "completion_tokens": 0}}


_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
