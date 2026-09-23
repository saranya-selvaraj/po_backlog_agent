"""Online-eval logging: every real generation the Streamlit UI shows a user
gets one row here (input, output, timestamp), and a 1-5 star rating is
added to that row once the user gives one.

Backed by Supabase Postgres (migrated from local SQLite in Stage C, once
the app needed to run somewhere with no durable local disk, e.g. Cloud
Run). Table `runs` (id, timestamp, initiative_text, generated_output
jsonb, rating) - create it once via the SQL in this project's deployment
notes before first use.

Run `python -m app.evals.query_online_log` to see what's been logged.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

TABLE_NAME = "runs"

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL / SUPABASE_KEY not set. Add them to a .env file at the project root."
            )
        _client = create_client(url, key)
    return _client


def log_run(initiative_text: str, result: dict) -> int:
    """Insert a new row for a completed generation (epic + features tree).

    Returns the new row's id, so the caller can later attach a rating to
    it via update_rating().
    """
    client = _get_client()
    response = (
        client.table(TABLE_NAME)
        .insert({"initiative_text": initiative_text, "generated_output": result})
        .execute()
    )
    return response.data[0]["id"]


def update_rating(run_id: int, rating: int) -> None:
    """Attach a 1-5 star rating to a previously logged run."""
    if not 1 <= rating <= 5:
        raise ValueError(f"rating must be 1-5, got {rating}")

    client = _get_client()
    client.table(TABLE_NAME).update({"rating": rating}).eq("id", run_id).execute()
