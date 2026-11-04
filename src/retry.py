"""Retry Gemini calls on rate limits (429) and overload (500/503), with increasing waits."""

import time

from google.genai import errors

RETRYABLE = {429, 500, 503}


def with_retry(fn, attempts: int = 6, base_wait: float = 5):
    for attempt in range(attempts):
        try:
            return fn()
        except errors.APIError as e:
            if e.code not in RETRYABLE or attempt == attempts - 1:
                raise
            wait = base_wait * 2**attempt
            print(f"  Gemini {e.code}, retrying in {wait:.0f}s ({attempt + 1}/{attempts - 1})")
            time.sleep(wait)
