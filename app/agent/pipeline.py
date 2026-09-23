"""Full pipeline: Initiative -> EPIC -> Features -> Stories, with optional
write-back to the in-process mock backlog store (PRD FR1-FR5 orchestration).

Chains Agent 1 (draft_epic) into Agent 2 (draft_features once, then
draft_stories once per feature) into a single nested result. If
write_back is True, writes the tree to app.api.store in-process (no
network hop - see app/api/store.py), preserving generated ids and
parent-child links. A standalone FastAPI wrapper around the same store
(app.api.main) is still available for manual/Swagger testing, but does
not need to be running for write-back to work.

Run standalone against a hardcoded test initiative, with write-back:
    python -m app.agent.pipeline
"""

from __future__ import annotations

import json

from app.agent.epic import EXAMPLE_INITIATIVE, draft_epic
from app.agent.features import draft_features
from app.agent.stories import draft_stories
from app.api import store


class WriteBackError(Exception):
    """Raised when writing the tree to the mock backlog store fails."""


def run_pipeline(initiative_text: str, write_back: bool = False) -> dict:
    """Run Initiative -> EPIC -> Features -> Stories end to end.

    Returns {"epic": {...}, "features": [{...feature, "stories": [...]}]}.

    If write_back is True, also writes the epic, then each feature, then
    each story to the in-process mock backlog store, and the returned
    epic/feature/story dicts carry the store-assigned "id" (and
    parent-id) fields instead of the raw drafted ones.
    """
    epic = draft_epic(initiative_text)
    features = draft_features(epic)

    features_with_stories = []
    for feature in features:
        stories = draft_stories(feature)
        features_with_stories.append({**feature, "stories": stories})

    result = {"epic": epic, "features": features_with_stories}

    if write_back:
        try:
            created_epic = store.create_epic(epic)
            epic_id = created_epic["id"]
            result["epic"] = created_epic

            written_features = []
            for feature in features_with_stories:
                feature_payload = {k: v for k, v in feature.items() if k != "stories"}
                created_feature = store.create_feature(epic_id, feature_payload)
                feature_id = created_feature["id"]

                written_stories = [
                    store.create_story(feature_id, story)
                    for story in feature["stories"]
                ]

                written_features.append({**created_feature, "stories": written_stories})

            result["features"] = written_features
        except LookupError as e:
            raise WriteBackError(f"Write-back to the mock backlog store failed: {e}") from e

    return result


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    result = run_pipeline(EXAMPLE_INITIATIVE, write_back=True)
    print(json.dumps(result, indent=2))

    epic_id = result["epic"]["id"]
    print(f"\nWritten to the in-process mock backlog store (epic id: {epic_id}).")
