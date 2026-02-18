"""
Token bucket rate limiter for Polymarket API calls.
Provides category-based rate limiting with automatic backoff.
"""
import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class EndpointCategory(Enum):
    """Polymarket API endpoint categories with different rate limits"""
    CLOB_GENERAL = "clob_general"      # 5000/10s
    MARKET_DATA = "market_data"        # 200/10s (/book, /price)
    GAMMA_API = "gamma_api"            # 750/10s
    BINANCE_WS = "binance_ws"          # No limit (WebSocket)
    COINGECKO = "coingecko"            # 10-30 calls/min (free tier)


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit bucket"""
    max_tokens: int
    refill_rate: float  # tokens per second
    window_seconds: float


# Rate limit configurations
RATE_LIMITS: Dict[EndpointCategory, RateLimitConfig] = {
    EndpointCategory.CLOB_GENERAL: RateLimitConfig(
        max_tokens=5000,
        refill_rate=500.0,  # 5000/10s
        window_seconds=10.0
    ),
    EndpointCategory.MARKET_DATA: RateLimitConfig(
        max_tokens=200,
        refill_rate=20.0,  # 200/10s
        window_seconds=10.0
    ),
    EndpointCategory.GAMMA_API: RateLimitConfig(
        max_tokens=750,
        refill_rate=75.0,  # 750/10s
        window_seconds=10.0
    ),
    EndpointCategory.BINANCE_WS: RateLimitConfig(
        max_tokens=10000,  # Effectively unlimited
        refill_rate=1000.0,
        window_seconds=10.0
    ),
    EndpointCategory.COINGECKO: RateLimitConfig(
        max_tokens=30,      # 30/min for free tier
        refill_rate=0.5,    # 30/60s
        window_seconds=60.0
    ),
}


class TokenBucket:
    """Token bucket implementation for rate limiting"""

    def __init__(self, config: RateLimitConfig):
        self.max_tokens = config.max_tokens
        self.refill_rate = config.refill_rate
        self.tokens = float(config.max_tokens)
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time"""
        now = time.monotonic()
        elapsed = now - self.last_refill
        new_tokens = elapsed * self.refill_rate
        self.tokens = min(self.max_tokens, self.tokens + new_tokens)
        self.last_refill = now

    async def acquire(self, tokens: int = 1) -> float:
        """
        Acquire tokens from the bucket.
        Blocks if insufficient tokens available.
        
        Returns:
            float: Time waited in seconds
        """
        async with self._lock:
            wait_time = 0.0

            while True:
                self._refill()

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    logger.debug(
                        f"Acquired {tokens} tokens. Remaining: {self.tokens:.2f}/{self.max_tokens}"
                    )
                    return wait_time

                # Calculate wait time for sufficient tokens
                tokens_needed = tokens - self.tokens
                sleep_time = tokens_needed / self.refill_rate
                sleep_time = max(sleep_time, 0.01)  # Minimum 10ms

                logger.debug(
                    f"Insufficient tokens ({self.tokens:.2f}/{tokens}). "
                    f"Waiting {sleep_time:.2f}s"
                )

                await asyncio.sleep(sleep_time)
                wait_time += sleep_time

    def available_tokens(self) -> int:
        """Get current number of available tokens"""
        self._refill()
        return int(self.tokens)


class RateLimiter:
    """
    Rate limiter managing multiple token buckets for different endpoint categories.
    """

    def __init__(self):
        self.buckets: Dict[EndpointCategory, TokenBucket] = {}
        self._429_backoff: Dict[EndpointCategory, float] = defaultdict(float)
        self._backoff_lock = asyncio.Lock()

        # Initialize buckets for each category
        for category, config in RATE_LIMITS.items():
            self.buckets[category] = TokenBucket(config)

    async def acquire(
        self,
        category: EndpointCategory,
        tokens: int = 1,
        retry_on_429: bool = True
    ) -> float:
        """
        Acquire rate limit tokens before making API request.
        
        Returns:
            float: Total time waited in seconds
        """
        bucket = self.buckets.get(category)
        if not bucket:
            logger.warning(f"Unknown category: {category}. No rate limiting applied.")
            return 0.0

        total_wait = 0.0

        # Apply 429 backoff if needed
        if retry_on_429:
            async with self._backoff_lock:
                backoff_until = self._429_backoff.get(category, 0.0)
                now = time.monotonic()

                if backoff_until > now:
                    wait_time = backoff_until - now
                    logger.warning(
                        f"429 backoff active for {category.value}. "
                        f"Waiting {wait_time:.2f}s"
                    )
                    await asyncio.sleep(wait_time)
                    total_wait += wait_time

        # Acquire tokens from bucket
        wait_time = await bucket.acquire(tokens)
        total_wait += wait_time

        return total_wait

    async def handle_429_error(
        self,
        category: EndpointCategory,
        retry_after: Optional[int] = None
    ) -> None:
        """Handle 429 Too Many Requests error with exponential backoff"""
        async with self._backoff_lock:
            now = time.monotonic()
            current_backoff = self._429_backoff.get(category, 0.0)

            if retry_after:
                backoff_time = float(retry_after)
            else:
                # Exponential backoff: start at 1s, double each time, max 60s
                if current_backoff > now:
                    remaining = current_backoff - now
                    backoff_time = min(remaining * 2, 60.0)
                else:
                    backoff_time = 1.0

            backoff_until = now + backoff_time
            self._429_backoff[category] = backoff_until

            logger.warning(
                f"429 error for {category.value}. "
                f"Setting backoff for {backoff_time:.2f}s"
            )

    def get_status(self) -> Dict[str, Dict]:
        """Get current status of all rate limit buckets"""
        status = {}
        now = time.monotonic()

        for category, bucket in self.buckets.items():
            backoff_remaining = max(0.0, self._429_backoff.get(category, 0.0) - now)

            status[category.value] = {
                "available_tokens": bucket.available_tokens(),
                "max_tokens": bucket.max_tokens,
                "refill_rate_per_sec": bucket.refill_rate,
                "backoff_remaining_sec": backoff_remaining,
                "is_throttled": backoff_remaining > 0
            }

        return status


# Singleton instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create the singleton rate limiter instance"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter
