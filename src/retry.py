"""Retry Gemini calls on rate limits (429) and overload (500/503), with increasing waits.

Every call also waits until at least GEMINI_CALL_DELAY seconds (default 2) have passed since the
previous call started, so a loop of calls stays under the free-tier rate limit instead of
bursting into it. Waits double each attempt, capped at MAX_WAIT, with random jitter so retries
do not line up.
"""

import os
import random
import time

from google.genai import errors

RETRYABLE = {429, 500, 503}
MAX_WAIT = 120.0

_last_call = 0.0


def _pace() -> None:
    global _last_call
    delay = float(os.getenv("GEMINI_CALL_DELAY", "2"))
    wait = _last_call + delay - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def with_retry(fn, attempts: int = 6, base_wait: float = 5):
    for attempt in range(attempts):
        _pace()
        try:
            return fn()
        except errors.APIError as e:
            if e.code not in RETRYABLE or attempt == attempts - 1:
                raise
            wait = min(base_wait * 2**attempt, MAX_WAIT) * random.uniform(0.8, 1.2)
            print(f"  Gemini {e.code}, retrying in {wait:.0f}s ({attempt + 1}/{attempts - 1})")
            time.sleep(wait)
