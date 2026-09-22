"""Node 2, part 2 - Feature and Story generation (PRD §8 step 6).

Uses the Feature/Story system prompts from docs/system_prompts.md verbatim,
including their in-prompt guardrail checklists, with two changes the PM
confirmed for Stage 3:
  - a JSON output block appended, since the deterministic validator (part 3)
    needs machine-readable fields, not markdown prose;
  - the docs prompt's own "5 to 8 features" line replaced with the confirmed
    2-5 (keeping both would contradict the code-enforced range below).
Story count (2-4) and the Given/When/Then acceptance-criteria rule reuse the
v1 shape; the docs prompt gives no story count.
"""

from __future__ import annotations

import json

import openai
from pydantic import BaseModel, Field, ValidationError

from app.llm.client import chat

MIN_FEATURES, MAX_FEATURES = 2, 5
MIN_STORIES, MAX_STORIES = 2, 4
GENERATION_TEMPERATURE = 0.3

FEATURE_SYSTEM_PROMPT = """You are an expert Agile Product Manager. Your task is to take a strategic Epic and break it down into functional Features (system capabilities) that can be delivered over a few sprints.

For each Feature generated, you must provide:
1. **Feature Name**: Clear, descriptive capability name (e.g., "One-Click Purchasing").
2. **Value Statement**: A 1-2 sentence explanation of why this capability matters to the user or business.
3. **High-Level Requirements**: A list of core business logic rules or system behaviors needed to support this feature.
4. Do not decompose too much and keep it optimal. Produce between 2 and 5 Features for this Epic.
5. Should display the relevant documents' title it retrieved from knowledgebase under section **Useful Documents to Refer**.
6. Epic Alignment: Verify that the feature directly traces back to solving one of the "In-Scope" boundaries of the parent Epic.

Guardrails to Check (Feature Verification)
- Shippable Value: Can this feature be completely tested and deployed on its own (even if hidden behind a feature flag)?
- No Technical Prescriptions: Does the feature focus on what the system should do, rather than how the code should be written?

Grounding rules:
- You will be given the Epic and a set of context chunks retrieved from an internal knowledge base, each labeled with its source filename, or a note that no relevant context was found.
- Under "Useful Documents to Refer", list ONLY the source filenames of chunks you actually drew on - never invent a document name, and leave the list empty if none of the provided chunks were used.
- If no relevant context was found, decompose from the Epic alone - do not fabricate facts to compensate.
- Do not invent requirements, numbers, or constraints not present in the Epic or the retrieved context.

Respond with a single JSON object and nothing else, shaped like:
{"features": [{"title": "string (Feature Name)", "value_statement": "string", "high_level_requirements": ["string", ...], "useful_documents": ["string", ...], "epic_alignment": "string explaining which In-Scope item this traces to"}, ...]}
Output raw JSON only - no markdown code fences, no commentary.
"""

STORY_SYSTEM_PROMPT = """You are an expert Agile Product Owner. Your task is to break down a product feature into small, ready-to-develop User Stories.

Every User Story you generate must strictly adhere to these rules:
1. **The User Story Template**: Format it exactly as:
   "As a [type of user], I want to [perform an action], so that [achieve a benefit/value]."
2. **The INVEST Framework**: Ensure the story is Independent, Negotiable, Valuable, Estimable, Small (can be completed in 1-3 days), and Testable.
3. **Acceptance Criteria**: Provide 2-3 concrete testing scenarios using the Behavior-Driven Development (BDD) **Given-When-Then** format:
   - **Given** [the initial context/state]
   - **When** [the user takes an action]
   - **Then** [the expected system response]

Do not group multiple separate features into a single user story. Keep them granular and customer-centric. Produce between 2 and 4 Stories for this Feature.

Guardrails to Check (User Story Verification)
- The "So That" Test: Does the "so that" clause articulate true value to the user, or is it just fluff? (e.g., "so that I can use the app" is poor; "so that I don't have to re-enter my address" is strong).
- BDD Completeness: Do the acceptance criteria explicitly map out the Given-When-Then variables without gaps?
- The Sprint Sizing Rule: Is the scope small enough for a single developer to build and test within 1-3 days? If not, break it down further.

Grounding rules:
- Ground every story and criterion in the given Feature (its title, value statement, and requirements).
- You will also be given context chunks retrieved from the internal knowledge base with granular detail (use cases, data models, API behavior, business rules), or a note that none were found. Where a chunk is relevant, let it sharpen an acceptance criterion's Given/When/Then with a real constraint or rule - do not treat it as decoration.
- Do not invent requirements, roles, or constraints not implied by the Feature or the retrieved context.

Respond with a single JSON object and nothing else, shaped like:
{"stories": [{"story": "As a ..., I want ..., so that ...", "acceptance_criteria": ["Given ..., When ..., Then ...", ...]}, ...]}
Output raw JSON only - no markdown code fences, no commentary.
"""


class Feature(BaseModel):
    title: str
    value_statement: str
    high_level_requirements: list[str] = Field(default_factory=list)
    useful_documents: list[str] = Field(default_factory=list)
    epic_alignment: str = ""


class FeatureList(BaseModel):
    features: list[Feature] = Field(default_factory=list)


class Story(BaseModel):
    story: str
    acceptance_criteria: list[str] = Field(default_factory=list)


class StoryList(BaseModel):
    stories: list[Story] = Field(default_factory=list)


class DecomposeError(Exception):
    """Raised when a model reply can't be parsed/validated into Features or Stories."""


def _chat_json_with_retry(messages: list[dict], temperature: float) -> str:
    """Groq's JSON mode occasionally fails server-side (`json_validate_failed`) on a
    well-formed request - observed in practice with elaborate nested acceptance
    criteria. One quiet retry before surfacing it as a DecomposeError."""
    last_error: Exception | None = None
    for _ in range(2):
        try:
            return chat(messages, response_format="json", temperature=temperature)
        except openai.BadRequestError as e:
            last_error = e
    raise DecomposeError(f"Model failed to generate valid JSON, even after a retry: {last_error}")


def generate_features(epic: dict, context_text: str) -> list[dict]:
    """One Groq call: Epic + retrieved context -> 2-5 Features."""
    from app.agent.epic import Epic  # local import: avoids a cycle with epic_node

    user_content = (
        f"EPIC:\n{json.dumps(Epic(**epic).model_dump(), indent=2)}\n\n"
        f"Retrieved context:\n{context_text}"
    )
    raw_reply = _chat_json_with_retry(
        [
            {"role": "system", "content": FEATURE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=GENERATION_TEMPERATURE,
    )
    try:
        feature_list = FeatureList(**json.loads(raw_reply))
    except (json.JSONDecodeError, ValidationError) as e:
        raise DecomposeError(
            f"Model's Feature reply was invalid ({type(e).__name__}): {e}\n--- raw reply ---\n{raw_reply}"
        ) from e
    if not (MIN_FEATURES <= len(feature_list.features) <= MAX_FEATURES):
        raise DecomposeError(
            f"Expected {MIN_FEATURES}-{MAX_FEATURES} Features, got {len(feature_list.features)}.\n"
            f"--- raw reply ---\n{raw_reply}"
        )
    return [f.model_dump() for f in feature_list.features]


def generate_stories(feature: dict, context_text: str) -> list[dict]:
    """One Groq call: a single Feature + its granular retrieved context -> 2-4 Stories."""
    user_content = f"Feature:\n{json.dumps(feature, indent=2)}\n\nRetrieved context:\n{context_text}"
    raw_reply = _chat_json_with_retry(
        [
            {"role": "system", "content": STORY_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=GENERATION_TEMPERATURE,
    )
    try:
        story_list = StoryList(**json.loads(raw_reply))
    except (json.JSONDecodeError, ValidationError) as e:
        raise DecomposeError(
            f"Model's Story reply was invalid ({type(e).__name__}): {e}\n--- raw reply ---\n{raw_reply}"
        ) from e
    if not (MIN_STORIES <= len(story_list.stories) <= MAX_STORIES):
        raise DecomposeError(
            f"Expected {MIN_STORIES}-{MAX_STORIES} Stories, got {len(story_list.stories)}.\n"
            f"--- raw reply ---\n{raw_reply}"
        )
    return [s.model_dump() for s in story_list.stories]
