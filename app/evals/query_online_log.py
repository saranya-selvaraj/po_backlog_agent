"""Query the online-eval log (see app/evals/online_log.py), backed by
Supabase Postgres.

Run with no arguments to list the most recent runs:
    python -m app.evals.query_online_log

Pass a row id to see that run's full initiative text and generated
EPIC/Features/Stories tree:
    python -m app.evals.query_online_log 7

Pass --limit N to change how many rows the list view shows (default 20).
"""

from __future__ import annotations

import json
import sys

from app.evals.online_log import TABLE_NAME, _get_client

DEFAULT_LIMIT = 20


def _truncate(text: str, width: int) -> str:
    text = " ".join(text.split())  # collapse newlines/whitespace for a one-line table
    return text if len(text) <= width else text[: width - 1] + "…"


def list_runs(limit: int) -> None:
    client = _get_client()
    response = (
        client.table(TABLE_NAME)
        .select("id, timestamp, initiative_text, rating")
        .order("id", desc=True)
        .limit(limit)
        .execute()
    )
    rows = response.data

    if not rows:
        print("No runs logged yet - generate something in the UI first.")
        return

    print(f"{'id':>4}  {'timestamp':<26}  {'rating':<6}  initiative_text")
    print("-" * 90)
    for row in rows:
        rating = "-" if row["rating"] is None else f"{row['rating']}/5"
        print(f"{row['id']:>4}  {row['timestamp']:<26}  {rating:<6}  {_truncate(row['initiative_text'], 50)}")

    print(f"\n{len(rows)} row(s) shown (limit {limit}). "
          f"Run `python -m app.evals.query_online_log <id>` to see a full run.")


def show_run(run_id: int) -> None:
    client = _get_client()
    response = client.table(TABLE_NAME).select("*").eq("id", run_id).execute()
    rows = response.data

    if not rows:
        print(f"No run with id {run_id}.")
        return

    row = rows[0]
    rating_str = "unrated" if row["rating"] is None else f"{row['rating']}/5"
    print(f"=== Run {row['id']} ===")
    print(f"timestamp: {row['timestamp']}")
    print(f"rating:    {rating_str}")
    print(f"\n--- initiative_text ---\n{row['initiative_text']}")
    print(f"\n--- generated_output ---\n{json.dumps(row['generated_output'], indent=2)}")


def main() -> int:
    args = sys.argv[1:]

    if args and args[0].isdigit():
        show_run(int(args[0]))
        return 0

    limit = DEFAULT_LIMIT
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])

    list_runs(limit)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
