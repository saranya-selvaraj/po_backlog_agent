"""Mock Backlog API (PRD §7).

Thin FastAPI wrapper around app.api.store's in-memory logic, kept for
manual testing via Swagger UI. The real write-back path
(app.agent.pipeline) calls app.api.store directly, in-process, so this
server does not need to be running for write-back to work - it's an
optional, standalone way to poke at the same store shape over HTTP.
Note it has its own separate in-memory state from any Streamlit process
that also imports app.api.store; the two don't share data.

Run with:
    uvicorn app.api.main:app --reload
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.api import store

app = FastAPI(title="PO Backlog Agent - Mock Backlog API")


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
    return store.create_epic(epic.model_dump())


@app.post("/epics/{epic_id}/features", response_model=Feature)
def create_feature(epic_id: str, feature: FeatureCreate) -> dict:
    try:
        return store.create_feature(epic_id, feature.model_dump())
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/features/{feature_id}/stories", response_model=Story)
def create_story(feature_id: str, story: StoryCreate) -> dict:
    try:
        return store.create_story(feature_id, story.model_dump())
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/epics/{epic_id}", response_model=EpicWithFeatures)
def get_epic(epic_id: str) -> dict:
    try:
        return store.get_epic(epic_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
