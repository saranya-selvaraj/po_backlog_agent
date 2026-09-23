"""Thin wrapper around the Groq API (PRD §9).

Groq exposes an OpenAI-compatible endpoint, so this uses the standard
`openai` SDK pointed at Groq's base URL rather than a separate `groq`
package. No agent logic here - this is just the call path.

LangSmith tracing: chat() is wrapped with @traceable so every call (EPIC,
Feature, and Story generation all route through it) shows up as a run in
LangSmith. Tracing only activates when LANGSMITH_TRACING=true is set in
the environment - LANGSMITH_API_KEY and LANGSMITH_PROJECT are also read
directly from the environment by the langsmith SDK, nothing to configure
here. With no LangSmith env vars set at all, @traceable is a no-op and
chat() behaves exactly as before.

Run standalone to sanity-check the connection:
    python -m app.llm.client
"""

from __future__ import annotations

import os
import re
import time

from dotenv import load_dotenv
from langsmith import traceable
from openai import OpenAI, RateLimitError

load_dotenv()

# Retry-with-backoff for Groq's 429 rate-limit responses (seen in practice
# on output-tokens-per-minute limits during story generation). Groq's error
# message names its own suggested wait, e.g. "Please try again in 1.14s"
# or "...in 9m0.864s" - honor that when present rather than guessing.
_MAX_RETRIES = 2
_DEFAULT_RETRY_WAIT_SECONDS = 5.0
# Groq formats the wait as "9m0.864s", "1.14s", or, for sub-second waits,
# "142.5ms" - handle all three (order in the alternation matters: "ms"
# must be tried before "s" or "s" would match the "s" inside "ms" first).
_RETRY_WAIT_RE = re.compile(r"try again in (?:(\d+)m)?([\d.]+)(ms|s)", re.IGNORECASE)


def _parse_retry_wait_seconds(error: RateLimitError) -> float:
    """Best-effort extraction of the wait time from a Groq rate-limit
    error's message. Falls back to _DEFAULT_RETRY_WAIT_SECONDS if the
    message doesn't match the expected "...try again in <X>(m)(s|ms)" shape.
    """
    message = ""
    if isinstance(error.body, dict):
        message = str(error.body.get("error", {}).get("message", ""))
    if not message:
        message = str(error)

    match = _RETRY_WAIT_RE.search(message)
    if not match:
        return _DEFAULT_RETRY_WAIT_SECONDS

    minutes_str, value_str, unit = match.groups()
    value = float(value_str)
    if unit.lower() == "ms":
        return value / 1000.0

    minutes = float(minutes_str) if minutes_str else 0.0
    return minutes * 60 + value


GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# llama-3.3-70b-versatile (PRD's first choice) has been retired from Groq's
# lineup as of this writing; using the PRD's named fallback instead.
# TEMPORARY: openai/gpt-oss-120b hit its Groq daily token-per-day quota
# (200k TPD) during eval development. Its smaller sibling openai/gpt-oss-20b
# was tried first (separate quota bucket) but proved unreliable for this
# app's multi-story JSON generation - draft_stories() repeatedly produced
# a JSON object with a duplicate "stories" key (one entry per story instead
# of one array of stories), which Groq's own JSON validator then rejected
# or which silently collapsed to 1 story on parse. qwen/qwen3.8-27b does
# not have this failure mode in testing. Switch back to
# "openai/gpt-oss-120b" once its quota resets.
GROQ_MODEL = "qwen/qwen3.8-27b"

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY not set. Add it to a .env file at the project root."
            )
        _client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
    return _client


@traceable(name="groq_chat", run_type="llm")
def chat(messages: list, response_format: str = None, temperature: float = 0.2) -> str:
    """Send `messages` (OpenAI chat-message dicts) to the Groq model and
    return the assistant's reply text.

    response_format: pass "json" to force the model to reply with a
    single valid JSON object (Groq/OpenAI JSON mode). Leave as None for
    plain free-text replies.
    temperature: defaults low (0.2) since this app's calls are structured
    extraction tasks (EPIC/Feature/Story shapes) where consistent,
    literally-grounded output matters more than creative variety.

    On a 429 rate-limit response, retries up to _MAX_RETRIES times,
    sleeping for the wait Groq's own error message suggests each time.
    Raises RuntimeError with a clear message if still rate-limited after
    all retries.
    """
    client = _get_client()

    kwargs = {"temperature": temperature}
    if response_format == "json":
        kwargs["response_format"] = {"type": "json_object"}

    last_error: RateLimitError | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                **kwargs,
            )
            return completion.choices[0].message.content
        except RateLimitError as e:
            last_error = e
            if attempt == _MAX_RETRIES:
                break
            time.sleep(_parse_retry_wait_seconds(e))

    raise RuntimeError(
        f"Groq rate limit hit and still failing after {_MAX_RETRIES} retries. "
        f"Please wait a bit and try again. ({last_error})"
    ) from last_error


if __name__ == "__main__":
    reply = chat(
        [
            {"role": "user", "content": "Reply with exactly one short sentence confirming you received this test message."}
        ]
    )
    print(reply)
