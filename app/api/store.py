"""In-memory mock backlog store (PRD §7).

Plain functions over two in-memory dicts - no HTTP, no auth, no real
database. Shared by app.api.main (a thin FastAPI wrapper, kept for
standalone/manual use via `uvicorn app.api.main:app`) and
app.agent.pipeline (in-process write-back), so there's exactly one
source of truth for this logic regardless of how it's called.

Data is process-local and resets on restart - unchanged from before this
module existed as a separate HTTP service, just no longer required to be
one for write-back to work.
"""

from __future__ import annotations

import uuid

# epic_id -> epic dict (with nested "features" list)
epics_db: dict[str, dict] = {}
# feature_id -> feature dict (with nested "stories" list)
features_db: dict[str, dict] = {}


def new_id() -> str:
    return uuid.uuid4().hex


def create_epic(epic: dict) -> dict:
    epic_id = new_id()
    record = {"id": epic_id, **epic, "features": []}
    epics_db[epic_id] = record
    return record


def create_feature(epic_id: str, feature: dict) -> dict:
    epic = epics_db.get(epic_id)
    if epic is None:
        raise LookupError(f"Epic '{epic_id}' not found")

    feature_id = new_id()
    record = {"id": feature_id, "epic_id": epic_id, **feature, "stories": []}
    features_db[feature_id] = record
    epic["features"].append(record)
    return record


def create_story(feature_id: str, story: dict) -> dict:
    feature = features_db.get(feature_id)
    if feature is None:
        raise LookupError(f"Feature '{feature_id}' not found")

    story_id = new_id()
    record = {"id": story_id, "feature_id": feature_id, **story}
    feature["stories"].append(record)
    return record


def get_epic(epic_id: str) -> dict:
    epic = epics_db.get(epic_id)
    if epic is None:
        raise LookupError(f"Epic '{epic_id}' not found")
    return epic
