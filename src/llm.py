"""OpenAI client and chat calls, shared by the baseline, the full agent, and the relevancy check.

Keeping the provider calls in one place means both agents talk to the model the same way.
"""

import os

from openai import OpenAI

from .config import Config
from .retry import with_retry


def make_client(cfg: Config) -> OpenAI:
    if not cfg.api_key:
        raise SystemExit("OPENAI_API_KEY is not set. Add it to .env.")
    # The SDK's own retries are off so with_retry is the only retry layer (no double waits).
    # The SDK's default timeout is 10 minutes; a shorter one stops a stuck call from stalling a run.
    return OpenAI(api_key=cfg.api_key, max_retries=0, timeout=float(os.getenv("LLM_TIMEOUT", "120")))


def generate(
    client: OpenAI,
    model: str,
    system: str,
    prompt: str,
    temperature: float,
    json_schema: dict | None = None,
    schema_name: str = "result",
) -> str:
    """One chat completion. With `json_schema`, the reply is forced to match it (strict structured output)."""
    kwargs = {}
    if json_schema is not None:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "schema": json_schema, "strict": True},
        }
    response = with_retry(
        lambda: client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            temperature=temperature,
            # Caps runaway output (strict JSON mode can repeat whitespace until the model's limit).
            max_completion_tokens=int(os.getenv("LLM_MAX_TOKENS", "4000")),
            **kwargs,
        )
    )
    choice = response.choices[0]
    if choice.finish_reason == "length":
        raise RuntimeError(f"{model} hit the LLM_MAX_TOKENS output cap; reply was cut off")
    return choice.message.content or ""
