"""Thin wrapper around the Groq API (PRD §9).

Groq exposes an OpenAI-compatible endpoint, so this uses the standard
`openai` SDK pointed at Groq's base URL rather than a separate `groq`
package. No agent logic here - this is just the call path.

Run standalone to sanity-check the connection:
    python -m app.llm.client
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# llama-3.3-70b-versatile (PRD's first choice) has been retired from Groq's
# lineup as of this writing; using the PRD's named fallback instead.
GROQ_MODEL = "openai/gpt-oss-120b"

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

    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        **kwargs,
    )
    return completion.choices[0].message.content


if __name__ == "__main__":
    reply = chat(
        [
            {"role": "user", "content": "Reply with exactly one short sentence confirming you received this test message."}
        ]
    )
    print(reply)
