"""Agent 2 (part 1) - EPIC -> Features, grounded in RAG context (PRD FR3 / §6).

Retrieves relevant knowledge-base chunks for the EPIC, then asks the LLM
to decompose the EPIC into 2-5 Features using both the EPIC and that
context. No write-back here yet - just the decomposition step.

Run standalone to sanity-check against the EPIC produced by app.agent.epic:
    python -m app.agent.features
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field, ValidationError

from app.llm.client import chat
from app.rag.retrieve import RetrievedChunk, retrieve

RETRIEVAL_K = 3

SYSTEM_PROMPT = """You are a Product Owner assistant that decomposes an \
EPIC into Features.

You will be given an EPIC (title, problem_statement, business_value, \
in_scope, out_of_scope) and a set of context chunks retrieved from an \
internal knowledge base (business case notes, design docs, policy docs), \
each labeled with its source filename.

Respond with a single JSON object and nothing else, shaped like:
{"features": [{"title": "string", "description": "string", "tech_notes": "string or null"}, ...]}

Rules:
- Produce between 2 and 5 Features.
- "description" must cover both the Why and the What of the feature.
- "tech_notes" is optional - set it to null unless the feature involves a \
bug fix or a specific technical constraint, in which case note it briefly.
- Ground every feature in the EPIC. Where the retrieved context is \
relevant, let it visibly shape the features (constraints, policies, or \
technical details from the context should show up in descriptions or \
tech_notes) - do not treat the context as decoration.
- If the retrieved context says no strongly relevant context was found, \
decompose from the EPIC alone - do not invent facts to compensate.
- Do not fabricate requirements, numbers, or constraints not present in \
the EPIC or the retrieved context.
- Output raw JSON only - no markdown code fences, no commentary.
"""

NO_CONTEXT_MESSAGE = "No strongly relevant context found in the knowledge base."


class Feature(BaseModel):
    title: str
    description: str
    tech_notes: str | None = None


class FeatureList(BaseModel):
    features: list[Feature] = Field(default_factory=list)


class FeatureDraftError(Exception):
    """Raised when the model's response can't be parsed/validated into Features."""


def _build_query(epic: dict) -> str:
    return f"{epic.get('title', '')}. {epic.get('problem_statement', '')}".strip()


def _format_context(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return NO_CONTEXT_MESSAGE
    return "\n\n".join(f"[Source: {c.source}]\n{c.text}" for c in chunks)


def draft_features(epic: dict) -> list[dict]:
    """Retrieve context for `epic` and decompose it into 2-5 Features.

    Returns a list of dicts, each shaped {title, description, tech_notes}.
    Raises FeatureDraftError if the model's reply isn't valid JSON or
    doesn't match the expected shape.
    """
    query = _build_query(epic)
    chunks = retrieve(query, k=RETRIEVAL_K)
    context_text = _format_context(chunks)

    user_content = (
        f"EPIC:\n{json.dumps(epic, indent=2)}\n\n"
        f"Retrieved context:\n{context_text}"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    raw_reply = chat(messages, response_format="json")

    try:
        data = json.loads(raw_reply)
    except json.JSONDecodeError as e:
        raise FeatureDraftError(
            f"Model did not return valid JSON: {e}\n--- raw reply ---\n{raw_reply}"
        ) from e

    try:
        feature_list = FeatureList(**data)
    except ValidationError as e:
        raise FeatureDraftError(
            f"Model's JSON didn't match the expected Features shape: {e}\n--- raw reply ---\n{raw_reply}"
        ) from e

    if not (2 <= len(feature_list.features) <= 5):
        raise FeatureDraftError(
            f"Expected 2-5 Features, got {len(feature_list.features)}.\n--- raw reply ---\n{raw_reply}"
        )

    return [f.model_dump() for f in feature_list.features]


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from app.agent.epic import EXAMPLE_INITIATIVE, draft_epic

    epic = draft_epic(EXAMPLE_INITIATIVE)
    print("=== EPIC (input) ===")
    print(json.dumps(epic, indent=2))

    query = _build_query(epic)
    chunks = retrieve(query, k=RETRIEVAL_K)
    print(f"\n=== Retrieved context (query: {query!r}) ===")
    if not chunks:
        print(NO_CONTEXT_MESSAGE)
    else:
        for c in chunks:
            print(f"[{c.score:.4f}] {c.source} (chunk {c.chunk_index})")
            print(f"  {c.text[:150]}...")

    features = draft_features(epic)
    print(f"\n=== Features ({len(features)}) ===")
    print(json.dumps(features, indent=2))
