"""
Process-local time-bounded cache for health probes.
Successes are cached; failures are not. Lost on process restart — fine,
next request just re-warms the entries.
"""
import time
from threading import Lock
from typing import Any, Optional


class TTLCache:
    """Thread-safe TTL cache. Keys are tuples. Values are arbitrary Python objects."""

    def __init__(self, ttl_seconds: int):
        self._ttl = ttl_seconds
        self._store: dict[tuple, tuple[float, Any]] = {}
        self._lock = Lock()

    def get(self, key: tuple) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if time.monotonic() >= expires_at:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: tuple, value: Any) -> None:
        with self._lock:
            self._store[key] = (time.monotonic() + self._ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_probe_cache = TTLCache(ttl_seconds=300)         # 5-min default for most probes
_membership_cache = TTLCache(ttl_seconds=60)     # 1-min — destination access surfaces fixes fast
_bot_self_cache = TTLCache(ttl_seconds=3600)     # 1-hour — bot user_id rarely changes
