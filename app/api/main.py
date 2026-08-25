"""Mock Backlog API (PRD §7).

FastAPI app exposing 4 endpoints backed by in-memory Python dicts:
  POST /epics
  POST /epics/{epic_id}/features
  POST /features/{feature_id}/stories
  GET  /epics/{epic_id}

No database, no auth. Run with:
    uvicorn app.api.main:app --reload
"""

import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="PO Backlog Agent - Mock Backlog API")

# ---------------------------------------------------------------------------
# In-memory storage
# ---------------------------------------------------------------------------
# epic_id -> epic dict (with nested "features" list)
epics_db: dict[str, dict] = {}
# feature_id -> feature dict (with nested "stories" list)
features_db: dict[str, dict] = {}


def new_id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Request models (PRD §5)
# ---------------------------------------------------------------------------
class EpicCreate(BaseModel):
    title: str
    problem_statement: str
    business_value: str
    in_scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)


class FeatureCreate(BaseModel):
    title: str
    description: str
    tech_notes: str | None = None


class StoryCreate(BaseModel):
    story: str
    acceptance_criteria: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
class Story(StoryCreate):
    id: str
    feature_id: str


class Feature(FeatureCreate):
    id: str
    epic_id: str


class FeatureWithStories(Feature):
    stories: list[Story] = Field(default_factory=list)


class Epic(EpicCreate):
    id: str


class EpicWithFeatures(Epic):
    features: list[FeatureWithStories] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/epics", response_model=Epic)
def create_epic(epic: EpicCreate) -> dict:
    epic_id = new_id()
    record = {"id": epic_id, **epic.model_dump(), "features": []}
    epics_db[epic_id] = record
    return record


@app.post("/epics/{epic_id}/features", response_model=Feature)
def create_feature(epic_id: str, feature: FeatureCreate) -> dict:
    epic = epics_db.get(epic_id)
    if epic is None:
        raise HTTPException(status_code=404, detail=f"Epic '{epic_id}' not found")

    feature_id = new_id()
    record = {"id": feature_id, "epic_id": epic_id, **feature.model_dump(), "stories": []}
    features_db[feature_id] = record
    epic["features"].append(record)
    return record


@app.post("/features/{feature_id}/stories", response_model=Story)
def create_story(feature_id: str, story: StoryCreate) -> dict:
    feature = features_db.get(feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail=f"Feature '{feature_id}' not found")

    story_id = new_id()
    record = {"id": story_id, "feature_id": feature_id, **story.model_dump()}
    feature["stories"].append(record)
    return record


@app.get("/epics/{epic_id}", response_model=EpicWithFeatures)
def get_epic(epic_id: str) -> dict:
    epic = epics_db.get(epic_id)
    if epic is None:
        raise HTTPException(status_code=404, detail=f"Epic '{epic_id}' not found")
    return epic
