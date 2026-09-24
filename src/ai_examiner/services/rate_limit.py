"""In-process sliding-window rate limiter for the anonymous learner surface.

The learner endpoints are reachable without an account, so they need their own
admission control in addition to the organization's model budget. State lives
in the process; run one application process per host (the default Compose
profile does) or put a shared limiter in front of multiple processes.
"""

from __future__ import annotations

import threading
import time
from collections import deque

MAX_TRACKED_KEYS = 50_000


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float,
        now: float | None = None,
    ) -> float | None:
        """Record one event; return None if allowed, else seconds until retry."""
        current = time.monotonic() if now is None else now
        with self._lock:
            events = self._events.get(key)
            if events is None:
                if len(self._events) >= MAX_TRACKED_KEYS:
                    self._prune(current, window_seconds)
                events = self._events.setdefault(key, deque())
            while events and current - events[0] >= window_seconds:
                events.popleft()
            if len(events) >= limit:
                return max(0.0, window_seconds - (current - events[0]))
            events.append(current)
            return None

    def _prune(self, current: float, window_seconds: float) -> None:
        stale = [
            key
            for key, events in self._events.items()
            if not events or current - events[-1] >= window_seconds
        ]
        for key in stale:
            del self._events[key]
        if len(self._events) >= MAX_TRACKED_KEYS:
            self._events.clear()

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


class ModelCallGate:
    """Bounded waiting line in front of model calls made for learners.

    Organization model governance rejects calls above its concurrency limit.
    A class answering at the same moment would otherwise see errors; instead
    each request waits here (in memory, without touching the database) for
    one of ``capacity`` slots.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._capacity = 0
        self._semaphore: threading.BoundedSemaphore | None = None

    def _semaphore_for(self, capacity: int) -> threading.BoundedSemaphore:
        with self._lock:
            if self._semaphore is None or capacity != self._capacity:
                self._capacity = capacity
                self._semaphore = threading.BoundedSemaphore(capacity)
            return self._semaphore

    def acquire(self, *, capacity: int, timeout: float) -> threading.BoundedSemaphore | None:
        semaphore = self._semaphore_for(max(1, capacity))
        return semaphore if semaphore.acquire(timeout=timeout) else None


learner_limiter = SlidingWindowLimiter()
learner_model_gate = ModelCallGate()
