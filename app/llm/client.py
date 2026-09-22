"""Thin wrapper around the Groq API (PRD §9).

Groq exposes an OpenAI-compatible endpoint, so this uses the standard
`openai` SDK pointed at Groq's base URL rather than a separate `groq`
package. No agent logic here - this is just the call path.

Run standalone to sanity-check the connection:
    python -m app.llm.client
"""

from __future__ import annotations

import os
import re
import time

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

load_dotenv()

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# llama-3.3-70b-versatile (PRD's first choice) has been retired from Groq's
# lineup as of this writing; using the PRD's named fallback instead.
GROQ_MODEL = "openai/gpt-oss-120b"

# Node 2 alone can fire a dozen-plus calls for one EPIC (retrieval loop x2
# phases + generation), which routinely trips Groq's free-tier TPM limit.
# Groq's 429 body names the wait in its message ("try again in 3.2s"); back off
# for that long (plus margin), or a fixed schedule if the wait isn't parseable.
_RATE_LIMIT_MAX_RETRIES = 4
_RATE_LIMIT_FALLBACK_WAITS = (5, 10, 20, 30)
_RETRY_AFTER_RE = re.compile(r"try again in ([\d.]+)s", re.I)

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


def _call_with_rate_limit_retry(fn):
    for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
        try:
            return fn()
        except RateLimitError as e:
            if attempt == _RATE_LIMIT_MAX_RETRIES:
                raise
            match = _RETRY_AFTER_RE.search(str(e))
            wait = float(match.group(1)) + 0.5 if match else _RATE_LIMIT_FALLBACK_WAITS[attempt]
            print(f"[llm] rate limited, retrying in {wait:.1f}s ({attempt + 1}/{_RATE_LIMIT_MAX_RETRIES})...", flush=True)
            time.sleep(wait)


def chat(messages: list, response_format: str = None, temperature: float = 0.2) -> str:
    """Send `messages` (OpenAI chat-message dicts) to the Groq model and
    return the assistant's reply text.

    response_format: pass "json" to force the model to reply with a
    single valid JSON object (Groq/OpenAI JSON mode). Leave as None for
    plain free-text replies.
    temperature: defaults low (0.2) since this app's calls are structured
    extraction tasks (EPIC/Feature/Story shapes) where consistent,
    literally-grounded output matters more than creative variety.
    """
    client = _get_client()

    kwargs = {"temperature": temperature}
    if response_format == "json":
        kwargs["response_format"] = {"type": "json_object"}

    completion = _call_with_rate_limit_retry(
        lambda: client.chat.completions.create(model=GROQ_MODEL, messages=messages, **kwargs)
    )
    return completion.choices[0].message.content


def chat_with_tools(
    messages: list,
    tools: list,
    tool_choice="auto",
    temperature: float = 0.2,
) -> dict:
    """Like `chat`, but with OpenAI-style tool definitions. Returns the assistant
    message as a plain dict ({"role", "content", and "tool_calls" when the model
    called tools}) ready to append to `messages` before sending tool results back.

    tool_choice: "auto", "none", or {"type": "function", "function": {"name": ...}}
    to force a specific tool call.
    """
    client = _get_client()
    completion = _call_with_rate_limit_retry(
        lambda: client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
        )
    )
    message = completion.choices[0].message
    result: dict = {"role": "assistant", "content": message.content or ""}
    if message.tool_calls:
        result["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.function.name, "arguments": call.function.arguments},
            }
            for call in message.tool_calls
        ]
    return result


if __name__ == "__main__":
    reply = chat(
        [
            {"role": "user", "content": "Reply with exactly one short sentence confirming you received this test message."}
        ]
    )
    print(reply)
