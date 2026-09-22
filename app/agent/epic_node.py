"""Node 1 - EPIC Generator (PRD §6, Build Guide Stage 2).

One Groq call, no tools, no loop: sanitized initiative text -> structured EPIC.
The output shape is the v1 FR1 shape (reused from app.agent.epic.Epic), so it
matches the mock Backlog API's EpicCreate model.

The prompt is the Epic prompt from docs/system_prompts.md mapped onto the
5-field JSON, with v1's grounding rules carried over. Success Metrics/KPIs is
deliberately not a field. Node 0 already handled blank/gibberish/PII/injection,
so no guardrail branch lives in this prompt.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from app.agent.epic import Epic
from app.agent.state import GraphState
from app.llm.client import chat

EPIC_TEMPERATURE = 0.3  # PM-confirmed for Stage 2; model stays the client default (openai/gpt-oss-120b)

SYSTEM_PROMPT = """You are an expert Agile Product Manager. Your task is to \
generate a comprehensive Agile Epic based on a high-level business \
initiative provided by the user (meeting notes, a ticket, or a business-case \
excerpt). The Epic must be based only on the input text from the user.

Respond with a single JSON object and nothing else, with exactly these keys:
- "title": Epic Title. Short, punchy, and outcome-oriented.
- "problem_statement": The "Why" behind this epic: the user problem it \
solves and the strategic objective, as a short narrative.
- "business_value": The business value this epic delivers.
- "in_scope": array of strings, each a distinct In-Scope item the \
initiative explicitly covers.
- "out_of_scope": array of strings, each a distinct Out-of-Scope item the \
initiative explicitly excludes or clearly does not cover.

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
- Placeholders such as [REDACTED_NAME] or [REDACTED_EMAIL] stand for \
personal details removed for privacy. Never guess what they were, and do \
not put them in the Epic unless unavoidable.
- All five fields must be non-empty.
- Output raw JSON only - no markdown code fences, no commentary.
"""


def _error(code: str, message: str) -> dict:
    return {"error": {"stage": "epic_generator", "code": code, "message": message}}


def epic_generator_node(state: GraphState) -> dict:
    """LangGraph node: reads state['clean_text'], writes state['epic'].

    A bad model reply (invalid JSON / wrong shape / empty required fields) is
    reported in state['error'] rather than raised. Transport/API failures from
    the Groq call still raise.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": state["clean_text"]},
    ]
    raw_reply = chat(messages, response_format="json", temperature=EPIC_TEMPERATURE)

    try:
        epic = Epic(**json.loads(raw_reply))
    except (json.JSONDecodeError, TypeError, ValidationError) as e:
        return _error(
            "invalid_model_output",
            f"Model reply was not a valid EPIC ({type(e).__name__}): {str(e)[:300]}\n--- raw reply ---\n{raw_reply}",
        )

    if not (epic.title.strip() and epic.problem_statement.strip() and epic.business_value.strip() and epic.in_scope):
        return _error(
            "incomplete_epic",
            f"Model returned an EPIC with empty required fields.\n--- raw reply ---\n{raw_reply}",
        )

    return {"epic": epic.model_dump()}
