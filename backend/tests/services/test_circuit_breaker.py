import pytest
import asyncio
from services.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_passes_when_closed(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)

        async def ok():
            return "ok"

        result = await cb.call(ok())
        assert result == "ok"
        assert cb.state == "closed"
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=60)

        async def fail():
            raise ValueError("fail")

        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(fail())
        assert cb.state == "open"
        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(fail())

    @pytest.mark.asyncio
    async def test_half_open_recovery(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0)

        async def fail():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            await cb.call(fail())
        assert cb.state == "open"

        async def ok():
            return "recovered"

        result = await cb.call(ok())
        assert result == "recovered"
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_half_open_fails_back_to_open(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0)

        async def fail():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            await cb.call(fail())
        assert cb.state == "open"
        with pytest.raises(ValueError):
            await cb.call(fail())
        assert cb.state == "open"
