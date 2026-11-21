"""
In-Memory TTL Cache
===================
Thread-safe, lightweight, in-memory caching with Time-To-Live (TTL) expiration.
Provides cached routing, elevation, and weather responses to avoid redundant external network calls.
"""
from __future__ import annotations

import time
import threading
from typing import Any, Dict, Optional, Tuple


class SimpleTTLCache:
    """Thread-safe in-memory key-value cache with per-item TTL expiration."""

    def __init__(self, default_ttl_seconds: float = 3600.0, max_entries: int = 1000):
        self._default_ttl = default_ttl_seconds
        self._max_entries = max_entries
        self._cache: Dict[str, Tuple[Any, float]] = {}  # key -> (value, expiry_time)
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        """Retrieve value if key exists and has not expired; returns None otherwise."""
        with self._lock:
            if key not in self._cache:
                return None
            value, expiry = self._cache[key]
            if time.time() > expiry:
                del self._cache[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        """Store key-value pair with TTL expiration."""
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        expiry = time.time() + ttl
        with self._lock:
            # Simple eviction of oldest entries if size limit reached
            if len(self._cache) >= self._max_entries and key not in self._cache:
                # Remove expired entries first
                now = time.time()
                expired_keys = [k for k, (_, exp) in self._cache.items() if now > exp]
                for k in expired_keys:
                    del self._cache[k]
                # If still over limit, evict first item
                if len(self._cache) >= self._max_entries:
                    oldest_key = next(iter(self._cache))
                    del self._cache[oldest_key]
            self._cache[key] = (value, expiry)

    def delete(self, key: str) -> bool:
        """Remove key from cache. Returns True if deleted, False if not present."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all entries."""
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)
