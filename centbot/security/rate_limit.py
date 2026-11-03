"""Request rate limiting."""

from __future__ import annotations

import time
import threading
from collections import deque


class RateLimiter:
    def __init__(self, per_minute: int = 30):
        self.per_minute = per_minute
        self._events: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = time.time()
        with self._lock:
            while self._events and now - self._events[0] > 60:
                self._events.popleft()
            if len(self._events) >= self.per_minute:
                return False
            self._events.append(now)
            return True

    def wait_allow(self, timeout: float = 60.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.allow():
                return True
            time.sleep(0.2)
        return False
