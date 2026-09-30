from __future__ import annotations

from datetime import timedelta
from typing import Optional, Any
import time
import importlib

from app.core.config import settings

redis: Any | None
try:
    redis = importlib.import_module("redis")
except ImportError:  # pragma: no cover - redis optional
    redis = None

class ExposureCache:
    def __init__(self, ttl_seconds: int = 600) -> None:
        self.ttl = timedelta(seconds=ttl_seconds)
        self._store: dict[str, tuple[float, dict]] = {}
        self._redis = None
        redis_url = getattr(settings, "REDIS_URL", None)
        if redis and redis_url:
            try:
                self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
            except Exception:  # pragma: no cover - redis misconfig
                self._redis = None

    def get(self, key: str) -> Optional[dict]:
        if self._redis:
            try:
                payload = self._redis.get(key)
                if payload:
                    import json

                    return json.loads(payload)
            except Exception:
                pass
        entry = self._store.get(key)
        if not entry:
            return None
        stored_ts, payload = entry
        if (time.time() - stored_ts) > self.ttl.total_seconds():
            self._store.pop(key, None)
            return None
        return payload

    def set(self, key: str, payload: dict, expires_at: float) -> None:
        if self._redis:
            try:
                import json

                self._redis.setex(key, int(self.ttl.total_seconds()), json.dumps(payload, default=str))
                return
            except Exception:
                pass
        self._store[key] = (time.time(), payload)

    def clear(self, key: Optional[str] = None) -> None:
        if key:
            if self._redis:
                try:
                    self._redis.delete(key)
                except Exception:
                    pass
            self._store.pop(key, None)
        else:
            if self._redis:
                try:
                    self._redis.flushdb()
                except Exception:
                    pass
            self._store.clear()

