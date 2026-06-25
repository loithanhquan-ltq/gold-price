import time
from threading import Lock
from backend.config import CACHE_TTL_SECONDS

_store: dict = {}
_lock = Lock()


def get(key: str):
    with _lock:
        item = _store.get(key)
        if item and item["expires"] > time.time():
            return item["value"]
    return None


def set(key: str, value, ttl: int = CACHE_TTL_SECONDS):
    with _lock:
        _store[key] = {"value": value, "expires": time.time() + ttl}


def invalidate(key: str):
    with _lock:
        _store.pop(key, None)
