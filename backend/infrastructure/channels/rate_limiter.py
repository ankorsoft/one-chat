"""
Circuit Breaker and Token Bucket implementations for rate limiting and fault tolerance.
Per-channel-account isolation to prevent cascading failures.
"""
import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional
from collections import defaultdict

import structlog

logger = structlog.get_logger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states."""
    
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    
    failure_threshold: int = 5  # failures before opening
    success_threshold: int = 3  # successes before closing
    timeout: float = 60.0  # seconds to wait before half-open
    expected_exceptions: tuple = (Exception,)


@dataclass
class CircuitBreaker:
    """
    Circuit breaker for external channel APIs.
    Prevents cascading failures when a provider is down.
    """
    
    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[float] = None
    last_state_change: float = field(default_factory=time.time)
    
    def record_success(self) -> None:
        """Record a successful call."""
        self.success_count += 1
        
        if self.state == CircuitState.HALF_OPEN:
            if self.success_count >= self.config.success_threshold:
                self._close()
        elif self.state == CircuitState.CLOSED:
            # Reset failure count on success
            self.failure_count = 0
    
    def record_failure(self) -> None:
        """Record a failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == CircuitState.HALF_OPEN:
            self._open()
        elif self.state == CircuitState.CLOSED:
            if self.failure_count >= self.config.failure_threshold:
                self._open()
    
    def can_execute(self) -> bool:
        """Check if a call can be executed."""
        if self.state == CircuitState.CLOSED:
            return True
        
        if self.state == CircuitState.OPEN:
            # Check if timeout has passed
            if time.time() - self.last_state_change >= self.config.timeout:
                self._half_open()
                return True
            return False
        
        # HALF_OPEN - allow one request to test
        return True
    
    async def execute(self, func, *args, **kwargs):
        """Execute a function with circuit breaker protection."""
        if not self.can_execute():
            raise CircuitBreakerOpenError(
                f"Circuit breaker is {self.state.value}"
            )
        
        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except self.config.expected_exceptions as e:
            self.record_failure()
            raise
    
    def _open(self) -> None:
        """Transition to OPEN state."""
        old_state = self.state
        self.state = CircuitState.OPEN
        self.last_state_change = time.time()
        self.success_count = 0
        
        logger.warning(
            "Circuit breaker opened",
            old_state=old_state,
            failure_count=self.failure_count,
        )
    
    def _half_open(self) -> None:
        """Transition to HALF_OPEN state."""
        old_state = self.state
        self.state = CircuitState.HALF_OPEN
        self.last_state_change = time.time()
        self.success_count = 0
        
        logger.info(
            "Circuit breaker half-open",
            old_state=old_state,
        )
    
    def _close(self) -> None:
        """Transition to CLOSED state."""
        old_state = self.state
        self.state = CircuitState.CLOSED
        self.last_state_change = time.time()
        self.failure_count = 0
        self.success_count = 0
        
        logger.info(
            "Circuit breaker closed",
            old_state=old_state,
        )


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


@dataclass
class TokenBucketConfig:
    """Configuration for token bucket rate limiter."""
    
    capacity: int = 30  # max tokens (requests per window)
    refill_rate: float = 1.0  # tokens per second
    initial_tokens: Optional[int] = None  # defaults to capacity


@dataclass
class TokenBucket:
    """
    Token bucket rate limiter for API rate limits.
    Per-channel-account to respect provider quotas.
    """
    
    config: TokenBucketConfig = field(default_factory=TokenBucketConfig)
    tokens: float = field(init=False)
    last_refill: float = field(default_factory=time.time)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    
    def __post_init__(self):
        self.tokens = (
            self.config.initial_tokens
            if self.config.initial_tokens is not None
            else self.config.capacity
        )
    
    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        tokens_to_add = elapsed * self.config.refill_rate
        self.tokens = min(self.config.capacity, self.tokens + tokens_to_add)
        self.last_refill = now
    
    async def acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens. Returns True if successful.
        Non-blocking - use wait_for_token() for blocking acquire.
        """
        async with self._lock:
            self._refill()
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    async def wait_for_token(self, tokens: int = 1, timeout: Optional[float] = None) -> bool:
        """
        Wait until tokens are available or timeout expires.
        Returns True if tokens were acquired.
        """
        start_time = time.time()
        
        while True:
            if await self.acquire(tokens):
                return True
            
            # Calculate wait time for next refill
            async with self._lock:
                tokens_needed = tokens - self.tokens
                wait_time = tokens_needed / self.config.refill_rate
            
            # Check timeout
            if timeout is not None:
                elapsed = time.time() - start_time
                if elapsed + wait_time > timeout:
                    return False
            
            # Wait for tokens to refill
            await asyncio.sleep(min(wait_time, 0.1))  # poll at most every 100ms
    
    def get_available_tokens(self) -> int:
        """Get current number of available tokens."""
        self._refill()
        return int(self.tokens)
    
    def get_retry_after(self) -> int:
        """Get seconds until at least 1 token is available."""
        if self.tokens >= 1:
            return 0
        
        tokens_needed = 1 - self.tokens
        return int(tokens_needed / self.config.refill_rate) + 1


class RateLimitExceededError(Exception):
    """Raised when rate limit is exceeded."""
    
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded, retry after {retry_after}s")


class RateLimiterRegistry:
    """
    Registry for managing per-channel-account rate limiters and circuit breakers.
    Thread-safe singleton pattern.
    """
    
    _instance: Optional["RateLimiterRegistry"] = None
    
    def __new__(cls) -> "RateLimiterRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._token_buckets: Dict[str, TokenBucket] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._initialized = True
    
    async def get_token_bucket(
        self,
        channel_account_id: str,
        capacity: int = 30,
        refill_rate: float = 1.0,
    ) -> TokenBucket:
        """Get or create a token bucket for a channel account."""
        async with self._locks[channel_account_id]:
            if channel_account_id not in self._token_buckets:
                self._token_buckets[channel_account_id] = TokenBucket(
                    config=TokenBucketConfig(
                        capacity=capacity,
                        refill_rate=refill_rate,
                    )
                )
            return self._token_buckets[channel_account_id]
    
    async def get_circuit_breaker(
        self,
        channel_account_id: str,
        failure_threshold: int = 5,
        timeout: float = 60.0,
    ) -> CircuitBreaker:
        """Get or create a circuit breaker for a channel account."""
        async with self._locks[channel_account_id]:
            if channel_account_id not in self._circuit_breakers:
                self._circuit_breakers[channel_account_id] = CircuitBreaker(
                    config=CircuitBreakerConfig(
                        failure_threshold=failure_threshold,
                        timeout=timeout,
                    )
                )
            return self._circuit_breakers[channel_account_id]
    
    def clear(self) -> None:
        """Clear all rate limiters and circuit breakers (for testing)."""
        self._token_buckets.clear()
        self._circuit_breakers.clear()
        self._locks.clear()


# Global registry instance
def get_rate_limiter_registry() -> RateLimiterRegistry:
    """Get the global rate limiter registry."""
    return RateLimiterRegistry()
