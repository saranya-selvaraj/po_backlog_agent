"""Node 2 - Agentic RAG Decomposer, assembled (PRD §8).

Wires together, per EPIC:
  1. retrieval_loop.run_retrieval_loop(PHASE_FEATURE, ...)  - Epic-level context
  2. decompose.generate_features(...)                        - 2-5 Features
  3. per Feature: retrieval_loop.run_retrieval_loop(PHASE_STORY, ...) - Feature-level context
  4. decompose.generate_stories(...)                          - 2-4 Stories each
  5. validator.validate_decomposition(...)                    - flags, never blocks (PM: flag only)

`retrieval_attempts` in the SQL table (PRD §7) is the Feature-loop's attempt
count; each Feature's own Story-loop attempt count travels in that Feature's
`story_retrieval` trace, since the table has one row per initiative, not per
Feature.
"""

from __future__ import annotations

from app.agent.decompose import generate_features, generate_stories
from app.agent.retrieval_loop import (
    PHASE_FEATURE,
    PHASE_STORY,
    epic_to_text,
    feature_to_text,
    run_retrieval_loop,
)
from app.agent.state import GraphState
from app.agent.validator import validate_decomposition


def _error(code: str, message: str) -> dict:
    return {"error": {"stage": "decomposer", "code": code, "message": message}}


def run_node2(epic: dict) -> dict:
    """Returns {"features": [...], "retrieval_attempts": int, "node2_trace": {...}}
    on success, or {"error": {...}} if a generation step fails."""
    epic_text = epic_to_text(epic)
    feature_retrieval = run_retrieval_loop(PHASE_FEATURE, epic_text, epic_text)

    try:
        features = generate_features(epic, feature_retrieval.context_text)
    except Exception as e:
        return _error("feature_generation_failed", str(e))

    features_with_stories: list[dict] = []
    story_sources: list[set[str]] = []
    story_traces: list[dict] = []

    for feature in features:
        feature_text = feature_to_text(feature, epic)
        story_retrieval = run_retrieval_loop(PHASE_STORY, feature_text, feature_text)
        try:
            stories = generate_stories(feature, story_retrieval.context_text)
        except Exception as e:
            return _error("story_generation_failed", f"Feature {feature['title']!r}: {e}")

        features_with_stories.append({**feature, "stories": stories})
        story_sources.append(set(story_retrieval.sources))
        story_traces.append(story_retrieval.trace())

    # useful_documents is generated alongside the Feature itself, grounded in the
    # Feature-phase (Epic-level) retrieval - not each Feature's own Story-phase
    # retrieval - so every Feature is checked against the same source set.
    feature_phase_sources = [set(feature_retrieval.sources)] * len(features_with_stories)
    validated_features = validate_decomposition(epic, features_with_stories, feature_phase_sources)

    return {
        "features": validated_features,
        "retrieval_attempts": feature_retrieval.attempts,
        "node2_trace": {
            "feature_retrieval": feature_retrieval.trace(),
            "story_retrieval_by_feature": story_traces,
        },
    }


def decomposer_node(state: GraphState) -> dict:
    """LangGraph node: reads state['epic'], writes state['features'] (+ trace),
    or state['error'] if generation fails."""
    return run_node2(state["epic"])


# ---------------------------------------------------------------------------
# Manual testing - two EPICs picked from live Stage 3 testing against the
# current 3-doc knowledge base (see chat log for the full test matrix).
# ---------------------------------------------------------------------------
SAMPLE_EPIC_ONE_RETRIEVAL = {
    "title": "Ultra-Processing Level Visibility",
    "problem_statement": (
        "Shoppers cannot tell how heavily processed a scanned product is, so they feel misled "
        "by products that look healthy on paper and open support tickets."
    ),
    "business_value": "Restores customer trust, reduces support tickets and protects the app store rating.",
    "in_scope": [
        "Classify scanned products as low, moderate or high ultra-processing",
        "Flag the specific industrial additives found in the ingredient list",
        "Show the level on the home screen for web and mobile",
    ],
    "out_of_scope": ["Changes to the overall food score", "General nutrition adjustments"],
}
# Observed 4/4 test runs at 1 attempt: the design doc's "Ultra-Processing Level
# Enrichment Engine" section is a strong, immediate match for this EPIC.

SAMPLE_EPIC_TWO_RETRIEVALS = {
    "title": "Keep Product Information Fresh After Catalogue Updates",
    "problem_statement": (
        "After a vendor corrects a product's data, shoppers keep seeing the old information in "
        "the mobile app for days."
    ),
    "business_value": "Customers see accurate product information sooner, which reduces complaints.",
    "in_scope": [
        "Refresh the information shown in the app soon after a product is updated",
        "Make sure the app shows the latest version on the next session",
    ],
    "out_of_scope": ["Changes to how vendors submit catalogues"],
}
# Observed mostly 2 attempts, occasionally 3, across test runs: the design doc's
# cache-eviction workflow is relevant but not an exact phrase match, so the first
# query sometimes needs refining, and how many times is the model's own judgment
# call - see the note in the chat log on why this isn't perfectly deterministic.


def _print_node2_result(label: str, epic: dict, result: dict) -> None:
    import json

    print(f"\n=== {label} ===")
    print(f"EPIC: {epic['title']}")
    if "error" in result:
        err = result["error"]
        print(f"STOPPED ({err['code']}): {err['message']}")
        return

    trace = result["node2_trace"]["feature_retrieval"]
    for s in trace["searches"]:
        print(f"  feature-phase attempt {s['attempt']}: query = {s['query']!r}")
    print(f"  retrieval_attempts = {result['retrieval_attempts']}  (capped={trace['capped']})")
    print(f"  verdict: sufficient={trace['sufficient']} - {trace['reason']}")

    for feature, story_trace in zip(result["features"], result["node2_trace"]["story_retrieval_by_feature"]):
        print(f"\n  --- Feature: {feature['title']} (story-phase attempts={story_trace['attempts']}) ---")
        if feature["validation_flags"]:
            print(f"    [FEATURE FLAGS] {feature['validation_flags']}")
        for story in feature["stories"]:
            print(f"    * {story['story']}")
            if story["validation_flags"]:
                print(f"      [STORY FLAGS] {story['validation_flags']}")
            for ac in story["acceptance_criteria"]:
                print(f"        - {ac}")


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    which = sys.argv[1:] or ["one", "two"]
    if "one" in which:
        _print_node2_result("Expected 1 retrieval", SAMPLE_EPIC_ONE_RETRIEVAL, run_node2(SAMPLE_EPIC_ONE_RETRIEVAL))
    if "two" in which:
        _print_node2_result("Expected 2 retrievals", SAMPLE_EPIC_TWO_RETRIEVALS, run_node2(SAMPLE_EPIC_TWO_RETRIEVALS))
