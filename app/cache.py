import hashlib
import json
import logging
import os

logger = logging.getLogger(__name__)

# Module-level cache enabled flag
_cache_enabled = True


def is_cache_enabled() -> bool:
    """Check if disk caching is enabled. Override/hook for --no-cache switch."""
    return _cache_enabled


def toggle_cache(enabled: bool) -> None:
    """Enable or disable disk caching."""
    global _cache_enabled
    _cache_enabled = enabled
    logger.info(f"Cache {'enabled' if _cache_enabled else 'disabled'}")


def _cache_filename(key: str) -> str:
    """Compute SHA-256 hash of the key and return the .cache/ filename."""
    h = hashlib.sha256(key.encode()).hexdigest()
    return os.path.join(".cache", h + ".json")


def is_cache_enabled() -> bool:
    """Check if disk caching is enabled. Override/hook for --no-cache switch."""
    # Default: enabled; main.py toggles this via the toggle_cache function
    return True


def cache_get(key: str):
    """Get a value from disk cache keyed by the given string.

    Returns the parsed JSON value, or None if not found or cache disabled.
    """
    if not is_cache_enabled():
        return None
    try:
        path = _cache_filename(key)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Cache hit for key '{key[:16]}...'")
        return data
    except Exception as e:
        logger.warning(f"Cache read failed for key '{key[:16]}...': {e}")
        return None


def cache_set(key: str, value: object) -> None:
    """Set a value in disk cache keyed by the given string.

    Writes the JSON-serializable value to .cache/<sha256(key)>.json.
    Creates the .cache/ folder if missing.
    """
    if not is_cache_enabled():
        return
    try:
        os.makedirs(".cache", exist_ok=True)
        path = _cache_filename(key)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
        logger.info(f"Cached result for key '{key[:16]}...' to {path}")
    except Exception as e:
        logger.warning(f"Cache write failed for key '{key[:16]}...': {e}")