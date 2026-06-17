import time
import structlog

logger = structlog.get_logger()


class CircuitBreakerOpenError(Exception):
    """熔断器打开时抛出，调用方应降级处理。"""
    def __init__(self, service_name: str):
        self.service_name = service_name
        super().__init__(f"Circuit breaker open for '{service_name}'")


class CircuitBreaker:
    """标准三态熔断器：closed → open → half_open → closed"""

    def __init__(self, name: str, failure_threshold: int = 5,
                 recovery_timeout: float = 30.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.state = "closed"
        self._last_failure_time: float = 0.0

    async def call(self, coro):
        now = time.time()

        if self.state == "open":
            if now - self._last_failure_time < self.recovery_timeout:
                raise CircuitBreakerOpenError(self.name)
            self.state = "half_open"
            logger.info("circuit_half_open", service=self.name)

        try:
            result = await coro
            self.failure_count = 0
            self.state = "closed"
            return result
        except Exception:
            self.failure_count += 1
            self._last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "open"
                logger.error("circuit_breaker_open", service=self.name,
                             failures=self.failure_count)
            raise
