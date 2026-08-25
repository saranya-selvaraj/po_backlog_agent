"""Agent 2 (part 2) - Feature -> Stories + Acceptance Criteria (PRD FR4 / §6).

Decomposes a single Feature into 2-4 user stories, each with Given/When/Then
acceptance criteria. No RAG here - the Feature (already grounded via
app.agent.features) is the sole input.

Run standalone to sanity-check against a Feature produced by app.agent.features:
    python -m app.agent.stories
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.llm.client import chat

SYSTEM_PROMPT = """You are a Product Owner assistant that decomposes a \
single Feature into user Stories with Acceptance Criteria.

You will be given a Feature (title, description, and optional tech_notes).

Respond with a single JSON object and nothing else, shaped like:
{"stories": [{"story": "string", "acceptance_criteria": ["string", "string", ...]}, ...]}

Rules:
- Produce between 2 and 4 stories.
- Each "story" must follow exactly this shape: "As a [role], I want \
[capability], so that [benefit]".
- Each story must have at least 2 acceptance criteria.
- Each acceptance criterion must be a single sentence in Given/When/Then \
form, e.g. "Given <context>, When <action>, Then <outcome>".
- Ground every story and criterion in the Feature's title, description, \
and tech_notes. Do not invent requirements, roles, or constraints not \
implied by the Feature.
- Output raw JSON only - no markdown code fences, no commentary.
"""


class Story(BaseModel):
    story: str
    acceptance_criteria: list[str] = Field(default_factory=list)

    @field_validator("story")
    @classmethod
    def _check_story_shape(cls, v: str) -> str:
        lower = v.lower()
        if "as a" not in lower or "i want" not in lower or "so that" not in lower:
            raise ValueError(
                f"Story must follow 'As a [role], I want [capability], so that [benefit]': {v!r}"
            )
        return v

    @field_validator("acceptance_criteria")
    @classmethod
    def _check_acceptance_criteria(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError(f"Expected at least 2 acceptance criteria, got {len(v)}")
        for ac in v:
            lower = ac.lower()
            if "given" not in lower or "when" not in lower or "then" not in lower:
                raise ValueError(f"Acceptance criterion not in Given/When/Then form: {ac!r}")
        return v


class StoryList(BaseModel):
    stories: list[Story] = Field(default_factory=list)


class StoryDraftError(Exception):
    """Raised when the model's response can't be parsed/validated into Stories."""


def draft_stories(feature: dict) -> list[dict]:
    """Decompose a single Feature into 2-4 Stories with Acceptance Criteria.

    Returns a list of dicts, each shaped {story, acceptance_criteria}.
    Raises StoryDraftError if the model's reply isn't valid JSON or doesn't
    match the expected shape (including the As a/I want/so that and
    Given/When/Then format rules).
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Feature:\n{json.dumps(feature, indent=2)}"},
    ]

    raw_reply = chat(messages, response_format="json")

    try:
        data = json.loads(raw_reply)
    except json.JSONDecodeError as e:
        raise StoryDraftError(
            f"Model did not return valid JSON: {e}\n--- raw reply ---\n{raw_reply}"
        ) from e

    try:
        story_list = StoryList(**data)
    except ValidationError as e:
        raise StoryDraftError(
            f"Model's JSON didn't match the expected Stories shape: {e}\n--- raw reply ---\n{raw_reply}"
        ) from e

    if not (2 <= len(story_list.stories) <= 4):
        raise StoryDraftError(
            f"Expected 2-4 Stories, got {len(story_list.stories)}.\n--- raw reply ---\n{raw_reply}"
        )

    return [s.model_dump() for s in story_list.stories]


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from app.agent.epic import EXAMPLE_INITIATIVE, draft_epic
    from app.agent.features import draft_features

    epic = draft_epic(EXAMPLE_INITIATIVE)
    features = draft_features(epic)

    feature = features[0]
    print("=== Feature (input, from Stage 6) ===")
    print(json.dumps(feature, indent=2))

    stories = draft_stories(feature)
    print(f"\n=== Stories ({len(stories)}) ===")
    print(json.dumps(stories, indent=2))
