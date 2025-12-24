"""
Resilience utilities including retry logic and circuit breakers.
"""

import logging
import asyncio
import functools
from typing import Any, Callable, Dict, Optional, Type, TypeVar
from dataclasses import dataclass

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from src.core.config import config

logger = logging.getLogger(__name__)

T = TypeVar("T")

@dataclass
class RetryConfig:
    """Configuration for retry logic."""
    max_attempts: int = config.MAX_RETRIES
    backoff_base: float = config.RETRY_BACKOFF_BASE
    retryable_status_codes: tuple = (429, 500, 502, 503, 504)

class CircuitBreaker:
    """
    Simple circuit breaker to prevent repeated calls to a failing service.
    """
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = asyncio.get_event_loop().time()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.error(f"Circuit breaker opened after {self.failure_count} failures")

    def record_success(self):
        self.failure_count = 0
        self.state = "CLOSED"

    def can_call(self) -> bool:
        import time
        if self.state == "CLOSED":
            return True

        now = time.monotonic()  # Better for timing
        if now - self.last_failure_time > self.recovery_timeout:
            self.state = "HALF_OPEN"
            return True

        return False

def with_resilience(
    retry_config: Optional[RetryConfig] = None,
    circuit_breaker: Optional[CircuitBreaker] = None
):
    """
    Decorator to apply retry logic and circuit breaker to an async function.
    """
    if retry_config is None:
        retry_config = RetryConfig()

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        
        # Define the retry wrapper using tenacity
        tenacity_retry = retry(
            stop=stop_after_attempt(retry_config.max_attempts),
            wait=wait_exponential(multiplier=retry_config.backoff_base),
            retry=(
                retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)) |
                retry_if_exception_type(httpx.HTTPStatusError)
            ),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True
        )

        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            if circuit_breaker and not circuit_breaker.can_call():
                raise RuntimeError("Circuit breaker is OPEN. Service unavailable.")

            try:
                # Apply tenacity retry to the function call
                # Note: tenacity retry works on the decorated function
                result = await tenacity_retry(func)(*args, **kwargs)
                
                if circuit_breaker:
                    circuit_breaker.record_success()
                return result
                
            except httpx.HTTPStatusError as e:
                # Only retry on specific status codes if it's an HTTPStatusError
                if e.response.status_code not in retry_config.retryable_status_codes:
                    raise e
                
                if circuit_breaker:
                    circuit_breaker.record_failure()
                raise e
            except Exception as e:
                if circuit_breaker:
                    circuit_breaker.record_failure()
                raise e

        return wrapper

    return decorator

