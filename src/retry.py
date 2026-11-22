"""Retry OpenAI calls on rate limits (429), server errors (500/502/503), and dropped connections.

Every call also waits until at least LLM_CALL_DELAY seconds (default 0) have passed since the
previous call started, so a loop of calls can be slowed down if it hits rate limits. Waits double
each attempt, capped at MAX_WAIT, with random jitter so retries do not line up.
"""

import os
import random
import time

import openai

RETRYABLE = {429, 500, 502, 503}
MAX_WAIT = 120.0

_last_call = 0.0


def _pace() -> None:
    global _last_call
    delay = float(os.getenv("LLM_CALL_DELAY", "0"))
    wait = _last_call + delay - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _retryable(e: Exception) -> str | None:
    """A short label if the error is worth retrying, else None."""
    if isinstance(e, openai.APIStatusError) and e.status_code in RETRYABLE:
        return str(e.status_code)
    if isinstance(e, openai.APIConnectionError):  # includes timeouts
        return "connection error"
    return None


def with_retry(fn, attempts: int = 6, base_wait: float = 5):
    for attempt in range(attempts):
        _pace()
        try:
            return fn()
        except openai.OpenAIError as e:
            label = _retryable(e)
            if label is None or attempt == attempts - 1:
                raise
            wait = min(base_wait * 2**attempt, MAX_WAIT) * random.uniform(0.8, 1.2)
            print(f"  OpenAI {label}, retrying in {wait:.0f}s ({attempt + 1}/{attempts - 1})")
            time.sleep(wait)
