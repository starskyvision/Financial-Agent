import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from services.llm_service import LLMService, get_llm_service, SimpleRateLimiter


class TestSimpleRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_within_limit(self):
        rl = SimpleRateLimiter(max_calls_per_minute=100)
        await rl.acquire()
        await rl.acquire()
        assert len(rl.timestamps) == 2


class TestGetLLMService:
    def test_singleton(self):
        s1 = get_llm_service()
        s2 = get_llm_service()
        assert s1 is s2


class TestLLMService:
    @pytest.fixture
    def svc(self):
        svc = LLMService()
        # Pre-set _primary to bypass lazy init (which requires env vars)
        mock_client = MagicMock()
        svc._primary = mock_client
        return svc

    @pytest.mark.asyncio
    async def test_invoke_returns_content(self, svc):
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "贵州茅台Q3 ROE为12.3%"
        mock_resp.choices[0].message.tool_calls = None
        mock_resp.model = "deepseek-chat"
        mock_resp.usage.prompt_tokens = 100
        mock_resp.usage.completion_tokens = 50
        mock_resp.usage.total_tokens = 150

        mock_create = AsyncMock(return_value=mock_resp)
        with patch.object(svc._primary.chat.completions, "create", mock_create):
            result = await svc.invoke("financial_analyzer", [
                {"role": "system", "content": "你是一个金融分析师"},
                {"role": "user", "content": "分析茅台Q3 ROE"}
            ])
            assert result["content"] == "贵州茅台Q3 ROE为12.3%"
            assert result["model"] == "deepseek-chat"

    @pytest.mark.asyncio
    async def test_invoke_raises_on_exhausted(self, svc):
        # Mock _ensure_clients to avoid re-init + simulate primary always failing
        svc._fallback = None  # disable fallback
        with patch.object(svc._primary.chat.completions, "create",
                          side_effect=Exception("always fails")):
            with pytest.raises(RuntimeError, match="LLM call exhausted"):
                await svc.invoke("default", [{"role": "user", "content": "hello"}])
