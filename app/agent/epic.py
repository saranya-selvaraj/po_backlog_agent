"""Agent 1 - Synthesizer (PRD FR1 / §6).

Turns raw, unstructured initiative text into a structured EPIC. Pure
generation - no tools, no RAG, no chaining to Agent 2 yet.

Run standalone to sanity-check extraction against a hardcoded example:
    python -m app.agent.epic
"""

from __future__ import annotations

import json
import re

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

GUARDRAILS - negative-scenario handling.
A lightweight code check (check_input_guardrails) already runs before you
see the input, but apply the same judgement as a second line of defence.
Instead of the EPIC object above, return ONLY this shape when a guardrail
applies:  {"error": "<code>", "message": "<user-facing message>"}

1. Invalid or empty input. If the input is blank, whitespace, a random
   key-mash (e.g. "asdfghjk"), punctuation noise (e.g. "%%%"), or otherwise
   contains no real initiative content, do NOT invent an EPIC. Return:
   {"error": "invalid_input", "message": "We couldn't process your input. \
Please provide a valid initiative description, such as relevant meeting \
notes, JIRA ticket summaries, or project outlines, and try again."}

2. Sensitive data. If the input contains data that looks like a credit-card
   number, a Social Security / national ID number, or an API key / access
   token / password, do NOT process it. Return:
   {"error": "sensitive_data", "message": "Epic conversion paused. We \
detected potential sensitive data (such as a credit card or identification \
number) within your input. For security compliance, please remove this \
information before proceeding."}
"""

# --- Negative-scenario guardrails (POC-level) ------------------------------
# Kept deliberately simple: a couple of cheap regex checks that run before
# any LLM call, matching the two scenarios in
# handling_negative_cases_scenarios.txt. Not a real DLP / validation engine.

_MIN_CHARS = 20
_MIN_REAL_WORDS = 5

INVALID_INPUT_MESSAGE = (
    "We couldn't process your input. Please provide a valid initiative "
    "description, such as relevant meeting notes, JIRA ticket summaries, or "
    "project outlines, and try again."
)
SENSITIVE_DATA_MESSAGE = (
    "Epic conversion paused. We detected potential sensitive data (such as a "
    "credit card or identification number) within your input. For security "
    "compliance, please remove this information before proceeding."
)

# label -> pattern. Labels are used only in the (masked) server-side log line.
_SENSITIVE_PATTERNS = {
    "credit-card-like number": re.compile(r"\b(?:\d[ -]?){12,18}\d\b"),
    "Social Security / national ID number": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "AWS access key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "provider secret key": re.compile(
        r"\b[sprk]k_(?:live|test|prod)_[A-Za-z0-9]{8,}", re.IGNORECASE
    ),
    "API key / token / password": re.compile(
        r"\b(?:api[_-]?key|secret|token|password|passwd|bearer)\b\s*[:=]\s*\S{8,}",
        re.IGNORECASE,
    ),
}


class InputGuardrailError(Exception):
    """Raised when initiative input fails a pre-flight guardrail check.

    `user_message` is safe to show verbatim in the UI; `code` is one of
    "invalid_input" | "sensitive_data".
    """

    def __init__(self, user_message: str, code: str):
        super().__init__(user_message)
        self.user_message = user_message
        self.code = code


def check_input_guardrails(initiative_text: str) -> None:
    """Cheap pre-flight validation, run before any model call.

    Scenario 1 - invalid/empty input: reject blank, too-short, or gibberish
    text so we don't spend a model call on it.
    Scenario 2 - sensitive data: block obvious credit-card / SSN / API-key
    shapes before the text leaves the process, and log a masked alert.

    Raises InputGuardrailError on a hit; returns None when the input is OK.
    """
    text = (initiative_text or "").strip()
    real_words = re.findall(r"[A-Za-z]{2,}", text)

    if not text or len(text) < _MIN_CHARS or len(real_words) < _MIN_REAL_WORDS:
        raise InputGuardrailError(INVALID_INPUT_MESSAGE, code="invalid_input")

    for label, pattern in _SENSITIVE_PATTERNS.items():
        if pattern.search(text):
            # Masked alert only - never log the matched value itself.
            print(f"[guardrail] blocked initiative input: suspected {label}", flush=True)
            raise InputGuardrailError(SENSITIVE_DATA_MESSAGE, code="sensitive_data")


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
    model's reply isn't valid JSON or doesn't match that shape, and
    InputGuardrailError if the input is empty/nonsensical or looks like it
    contains sensitive data.
    """
    # Guardrail 1: pre-flight check, no model call spent on bad input.
    check_input_guardrails(initiative_text)

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

    # Guardrail 2: the model itself flagged the input (see SYSTEM_PROMPT).
    if isinstance(data, dict) and data.get("error") in {"invalid_input", "sensitive_data"}:
        raise InputGuardrailError(
            data.get("message") or INVALID_INPUT_MESSAGE, code=data["error"]
        )

    try:
        epic = Epic(**data)
    except ValidationError as e:
        raise EpicDraftError(
            f"Model's JSON didn't match the expected EPIC shape: {e}\n--- raw reply ---\n{raw_reply}"
        ) from e

    return epic.model_dump()


# Default example shown in the UI on load - a multi-person meeting
# transcript about making ultra-processing visible after a barcode scan.
EXAMPLE_INITIATIVE = """
Elena (Customer Satisfaction SME): Wait, sorry to interrupt Sarah, but look - the queues are literally burning up with this exact issue right now. Users do not care about the standard calorie counts or macro breakdowns anymore. They are opening tickets left and right because they scan something that looks completely healthy on paper, but then they read the fine print and see it's packed with industrial emulsifiers and shelf-stabilizers. They feel completely tricked by us if our app doesn't call out that it's heavy ultra-processed junk. If we want to save our App Store rating this quarter, this entire feature needs to focus strictly on stripping back the curtain on ultra-processing. Nothing else.

Sarah (Product Owner): No, you're 100% right, let's pivot. Let's completely freeze any work on other features or general nutrition adjustments for this sprint. We focus solely on ultra-processing visibility. So, high level... when someone scans a barcode, the backend engine has to instantly tell them if the item has low, moderate, or high industrial manipulation.

Elena (Customer Satisfaction SME): Yes! But look, it can't just be a random badge or a vague score, or my team is just going to get flooded with a million "Why did my food get this rating?" emails anyway. The system has to actually dig into the raw text string of the ingredients and explicitly flag the actual culprits. Like, if it sees high-fructose corn syrup, hydrolyzed proteins, or cosmetic texturizers, it needs to isolate those specific chemical markers instantly. Display this on home screen with a slider showing high, medium and low and a marker arrow to indicate where the product score lies.

Sarah (Product Owner): Okay, let me write this down. So the pipeline has to ingest the vendor catalogs, tokenize the messy ingredient text arrays, and cross-reference them against a master additive risk dictionary to count the industrial markers. It calculates the tier based only on that processing depth, writes the classification to the database, and pushes it out. I'll make sure the engineering documentation is explicitly locked down to just this ultra-processing logic so the dev team doesn't get sidetracked by other metrics. I will have a chat with UX designer as well and include the change for both web and mobile versions.
""".strip()

# A second valid initiative, kept for the "happy path" demo buttons in the UI.
EXAMPLE_INITIATIVE_SCORE_EXPLAINER = """
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
