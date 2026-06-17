"""A small, thread-safe fixed-window rate limiter.

Combined with the shared-snapshot TTL cache, this stops request floods from
amplifying load: even if a client hammers the API, collection is coalesced and
excess requests get a fast 429.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_requests: int = 60, window_seconds: float = 10.0) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, client: str, *, now: float | None = None) -> bool:
        """Record a request from ``client``; return False if over the limit."""
        ts = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._hits[client]
            cutoff = ts - self.window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                return False
            bucket.append(ts)
            # Opportunistically drop empty buckets to bound memory.
            if len(self._hits) > 1024:
                self._gc(cutoff)
            return True

    def _gc(self, cutoff: float) -> None:
        for client in list(self._hits):
            bucket = self._hits[client]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if not bucket:
                del self._hits[client]
