import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import json
import time
import hashlib

def _cache_path(key: str) -> str:
    h = hashlib.md5(key.encode()).hexdigest()
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    return os.path.join(config.CACHE_DIR, f"{h}.json")

def get(key: str, ttl: int):
    """Return cached value if fresh, else None."""
    path = _cache_path(key)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            entry = json.load(f)
        if time.time() - entry["ts"] < ttl:
            return entry["data"]
    except Exception:
        pass
    return None

def set(key: str, data):
    """Write data to cache."""
    path = _cache_path(key)
    try:
        with open(path, "w") as f:
            json.dump({"ts": time.time(), "data": data}, f)
    except Exception:
        pass

def invalidate(key: str):
    """Remove a cache entry."""
    path = _cache_path(key)
    if os.path.exists(path):
        os.remove(path)
