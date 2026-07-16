from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any


class TVQueryCache:
    """Small bounded process cache for expensive catalogue queries."""

    def __init__(self, max_entries: int = 512) -> None:
        self.max_entries = max_entries
        self._lock = threading.RLock()
        self._generation = 0
        self._entries: OrderedDict[str, tuple[float, int, Any]] = OrderedDict()

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def invalidate(self) -> None:
        with self._lock:
            self._generation += 1
            self._entries.clear()

    def get_or_set(
        self, key: str, factory: Callable[[], Any], *, ttl_seconds: int
    ) -> tuple[Any, bool]:
        now = time.monotonic()
        with self._lock:
            cached = self._entries.get(key)
            if cached and cached[0] > now and cached[1] == self._generation:
                self._entries.move_to_end(key)
                return cached[2], True
            generation = self._generation

        value = factory()
        with self._lock:
            if generation == self._generation:
                self._entries[key] = (now + ttl_seconds, generation, value)
                self._entries.move_to_end(key)
                while len(self._entries) > self.max_entries:
                    self._entries.popitem(last=False)
        return value, False


query_cache = TVQueryCache()
