"""
Production Rate Limiter for Expo Design AI.

Implements an in-memory, thread-safe, sliding-window rate limiter.
Can be used directly as a utility function or mounted as a FastAPI dependency.
Requires zero external dependencies (Redis-free, pure Python, offline-safe).
"""
import time
import threading
from typing import Dict, List, Optional, Callable
from fastapi import Request, HTTPException, status
from loguru import logger


class SlidingWindowRateLimiter:
    """Thread-safe sliding-window rate limiter."""

    def __init__(self, cleanup_interval_seconds: float = 300.0):
        self._lock = threading.Lock()
        self._buckets: Dict[str, List[float]] = {}
        self._last_cleanup = time.time()
        self._cleanup_interval = cleanup_interval_seconds

    def is_allowed(self, key: str, max_requests: int, window_seconds: float) -> tuple[bool, int]:
        """
        Check if request under `key` is allowed.
        Returns:
            (allowed: bool, retry_after: int)
        """
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            # Periodic cleanup of completely stale keys to bound memory
            if now - self._last_cleanup > self._cleanup_interval:
                self._cleanup_stale_buckets(now)
                self._last_cleanup = now

            timestamps = self._buckets.get(key, [])
            # Filter timestamps outside the sliding window
            valid_timestamps = [t for t in timestamps if t > cutoff]

            if len(valid_timestamps) >= max_requests:
                # Earliest timestamp in the current window determines retry-after
                oldest_in_window = valid_timestamps[0]
                retry_after = max(1, int(oldest_in_window + window_seconds - now))
                self._buckets[key] = valid_timestamps
                return False, retry_after

            valid_timestamps.append(now)
            self._buckets[key] = valid_timestamps
            return True, 0

    def _cleanup_stale_buckets(self, now: float):
        """Remove keys that have had no activity for more than 1 hour."""
        threshold = now - 3600.0
        keys_to_delete = [
            k for k, timestamps in self._buckets.items()
            if not timestamps or timestamps[-1] < threshold
        ]
        for k in keys_to_delete:
            del self._buckets[k]

    def reset(self, key: Optional[str] = None):
        """Reset rate limit buckets (useful for tests)."""
        with self._lock:
            if key is not None:
                self._buckets.pop(key, None)
            else:
                self._buckets.clear()


# Global limiter instance
_global_limiter = SlidingWindowRateLimiter()


def get_client_identifier(request: Request) -> str:
    """Extract a reliable client identifier from request (user ID, header, or IP)."""
    # Prefer authenticated user ID if present
    user = getattr(request.state, "user", None)
    if user and isinstance(user, dict) and user.get("username"):
        return f"user:{user['username']}"

    # Fallback to forwarded header or client host
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
        if client_ip:
            return f"ip:{client_ip}"

    if request.client and request.client.host:
        return f"ip:{request.client.host}"

    return "ip:unknown"


def rate_limit(max_requests: int = 60, window_seconds: float = 60.0) -> Callable:
    """
    FastAPI dependency factory for rate limiting.

    Usage:
        @router.post("/endpoint", dependencies=[Depends(rate_limit(10, 60))])
    """
    async def dependency(request: Request):
        client_id = get_client_identifier(request)
        route_key = f"{client_id}:{request.url.path}"

        allowed, retry_after = _global_limiter.is_allowed(
            route_key, max_requests=max_requests, window_seconds=window_seconds
        )
        if not allowed:
            logger.warning(
                f"Rate limit exceeded for {client_id} on {request.url.path}. "
                f"Limit: {max_requests} req / {window_seconds}s. Retry after {retry_after}s."
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Please retry in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency


def check_rate_limit(key: str, max_requests: int = 10, window_seconds: float = 300.0) -> bool:
    """
    Direct function call rate limiter (drop-in replacement for legacy _check_rate_limit).
    """
    allowed, _ = _global_limiter.is_allowed(key, max_requests=max_requests, window_seconds=window_seconds)
    return allowed


def reset_rate_limit(key: Optional[str] = None):
    """
    Resets the rate limit bucket for a key (or all keys if key is None).
    """
    _global_limiter.reset(key)

