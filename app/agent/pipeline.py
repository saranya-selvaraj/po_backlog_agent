"""Full pipeline: Initiative -> EPIC -> Features -> Stories, with optional
write-back to the mock backlog API (PRD FR1-FR5 orchestration).

Chains Agent 1 (draft_epic) into Agent 2 (draft_features once, then
draft_stories once per feature) into a single nested result. If
write_back is True, POSTs the tree to the Stage 1 mock API
(app.api.main, expected running at localhost:8000), preserving the
server-assigned IDs and parent-child links.

Run standalone against a hardcoded test initiative, with write-back:
    python -m app.agent.pipeline
"""

from __future__ import annotations

import json

import requests

from app.agent.epic import EXAMPLE_INITIATIVE, draft_epic
from app.agent.features import draft_features
from app.agent.stories import draft_stories

BACKLOG_API_BASE_URL = "http://localhost:8000"


class WriteBackError(Exception):
    """Raised when writing the tree to the mock backlog API fails."""


def _post(path: str, payload: dict) -> dict:
    url = f"{BACKLOG_API_BASE_URL}{path}"
    try:
        response = requests.post(url, json=payload, timeout=10)
    except requests.RequestException as e:
        raise WriteBackError(
            f"Could not reach the mock backlog API at {url}. Is it running? "
            f"(`uvicorn app.api.main:app --reload`) {e}"
        ) from e

    if not response.ok:
        raise WriteBackError(f"POST {url} failed ({response.status_code}): {response.text}")

    return response.json()


def run_pipeline(initiative_text: str, write_back: bool = False) -> dict:
    """Run Initiative -> EPIC -> Features -> Stories end to end.

    Returns {"epic": {...}, "features": [{...feature, "stories": [...]}]}.

    If write_back is True, also POSTs the epic, then each feature, then
    each story to the mock backlog API (Stage 1) in that order, and the
    returned epic/feature/story dicts carry the server-assigned "id"
    (and parent-id) fields instead of the raw drafted ones.
    """
    epic = draft_epic(initiative_text)
    features = draft_features(epic)

    features_with_stories = []
    for feature in features:
        stories = draft_stories(feature)
        features_with_stories.append({**feature, "stories": stories})

    result = {"epic": epic, "features": features_with_stories}

    if write_back:
        created_epic = _post("/epics", epic)
        epic_id = created_epic["id"]
        result["epic"] = created_epic

        written_features = []
        for feature in features_with_stories:
            feature_payload = {k: v for k, v in feature.items() if k != "stories"}
            created_feature = _post(f"/epics/{epic_id}/features", feature_payload)
            feature_id = created_feature["id"]

            written_stories = [
                _post(f"/features/{feature_id}/stories", story)
                for story in feature["stories"]
            ]

            written_features.append({**created_feature, "stories": written_stories})

        result["features"] = written_features

    return result


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    result = run_pipeline(EXAMPLE_INITIATIVE, write_back=True)
    print(json.dumps(result, indent=2))

    epic_id = result["epic"]["id"]
    print(f"\nWritten to mock backlog API. Verify with:")
    print(f"  GET {BACKLOG_API_BASE_URL}/epics/{epic_id}")
