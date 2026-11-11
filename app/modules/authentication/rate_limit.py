"""In-memory sliding-window rate limiter (per process) for sensitive endpoints."""

import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import Request

from app.core.dependencies import AppSettings
from app.shared.exceptions import TooManyRequestsError


class RateLimiter:
    def __init__(self, window_seconds: float = 60.0) -> None:
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self._window:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()


def rate_limit(scope: str) -> Callable[[Request, AppSettings], None]:
    def dependency(request: Request, settings: AppSettings) -> None:
        client = request.client.host if request.client else "unknown"
        if not rate_limiter.allow(f"{scope}:{client}", settings.rate_limit_per_minute):
            raise TooManyRequestsError("Too many requests, try again later")

    return dependency
