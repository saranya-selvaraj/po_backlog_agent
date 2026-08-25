"""Agent 1 - Synthesizer (PRD FR1 / §6).

Turns raw, unstructured initiative text into a structured EPIC. Pure
generation - no tools, no RAG, no chaining to Agent 2 yet.

Run standalone to sanity-check extraction against a hardcoded example:
    python -m app.agent.epic
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field, ValidationError

from app.llm.client import chat

SYSTEM_PROMPT = """You are a Product Owner assistant that turns a raw, \
unstructured initiative description (meeting notes, a ticket, or a \
business-case excerpt) into a structured EPIC.

Respond with a single JSON object and nothing else, with exactly these keys:
- "title": short string naming the epic
- "problem_statement": string describing the problem being solved
- "business_value": string describing why this matters / the expected value
- "in_scope": array of strings, each a distinct item explicitly covered by the initiative
- "out_of_scope": array of strings, each a distinct item explicitly excluded or clearly implied as not covered

Rules:
- Ground every field strictly in the input. Do not invent numbers, dates, \
metrics, names, or claims that are not stated or clearly implied in the text.
- If the input does not mention anything out of scope, infer a short, \
reasonable out_of_scope list only from things the text clearly does NOT \
cover (e.g. adjacent features it explicitly declines to address) - never \
fabricate specifics.
- Distinguish a settled decision from an open question. If the input \
raises something as unresolved - phrased as a question, a "TBD", "not \
sure if...", "open question is...", or similar hedging - do NOT convert \
it into a firm in_scope or out_of_scope item. Leave genuinely unresolved \
points out of both lists entirely; only list items the input treats as a \
decided inclusion or a decided exclusion.
- All five fields must be non-empty.
- Output raw JSON only - no markdown code fences, no commentary.
"""


class Epic(BaseModel):
    title: str
    problem_statement: str
    business_value: str
    in_scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)


class EpicDraftError(Exception):
    """Raised when the model's response can't be parsed/validated into an Epic."""


def draft_epic(initiative_text: str) -> dict:
    """Call the LLM to extract a structured EPIC from raw initiative text.

    Returns a dict matching the Epic shape (title, problem_statement,
    business_value, in_scope, out_of_scope). Raises EpicDraftError if the
    model's reply isn't valid JSON or doesn't match that shape.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": initiative_text},
    ]

    raw_reply = chat(messages, response_format="json")

    try:
        data = json.loads(raw_reply)
    except json.JSONDecodeError as e:
        raise EpicDraftError(
            f"Model did not return valid JSON: {e}\n--- raw reply ---\n{raw_reply}"
        ) from e

    try:
        epic = Epic(**data)
    except ValidationError as e:
        raise EpicDraftError(
            f"Model's JSON didn't match the expected EPIC shape: {e}\n--- raw reply ---\n{raw_reply}"
        ) from e

    return epic.model_dump()


EXAMPLE_INITIATIVE = """
Ok so coming out of yesterday's review of our CSAT (customer satisfaction)
survey results - customers keep telling us they don't understand WHY a
product got the health & safety score it did. support tickets are up again
this month specifically people asking "why is this rated lower than a
similar product" and we don't have a good answer for them in app right now.
marketing also flagged this as a blocker for the Q3 partnership push bc
partner brands want to know how their products' scores will be explained to
shoppers. idea floated in the meeting: show a short plain-language breakdown
alongside each product's score - what factors pushed it up or down, in
customer-friendly language, not our internal scoring jargon. should work on
both the product detail page and the comparison view since that's where
people are asking the question. NOT trying to let users override or edit
the score themselves - that's a different (and much scarier) conversation
for another day, and we're also explicitly not touching the underlying
scoring algorithm itself, just how it's explained. biggest open question is
whether legal needs to review the language since it's basically explaining
a rating methodology to consumers.
""".strip()


if __name__ == "__main__":
    result = draft_epic(EXAMPLE_INITIATIVE)
    print(json.dumps(result, indent=2))
