"""Runs a single eval case end-to-end and prints its result as one JSON
line to stdout. Invoked as a subprocess (see offline_eval.py) so a stalled
judge call can be killed at the OS level (subprocess.run(timeout=...)),
rather than relying on asyncio cancellation - which does not reliably
interrupt a pending I/O read on Windows' default ProactorEventLoop, so an
in-process asyncio.wait_for() guard was observed not to fire even minutes
past its deadline.

Not meant to be run directly by a person; see offline_eval.py for the
real entry point and thresholds.
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.evals.ragas_setup import build_ragas_metrics

from app.agent.epic import draft_epic
from app.agent.features import RETRIEVAL_K, _build_query, draft_features
from app.rag.retrieve import _get_collection, _get_model, retrieve
from app.evals.dataset import EVAL_CASES

RECALL_K = 10
PRECISION_K = 5


def _raw_retrieve(query: str, k: int) -> list[tuple[str, str, float]]:
    model = _get_model()
    collection = _get_collection()
    query_embedding = model.encode([query]).tolist()
    results = collection.query(query_embeddings=query_embedding, n_results=k)

    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    return [
        (doc, meta["source"], round(1 - dist, 4))
        for doc, meta, dist in zip(documents, metadatas, distances)
    ]


def _format_feature(feature: dict) -> str:
    parts = [f"{feature['title']}: {feature['description']}"]
    if feature.get("tech_notes"):
        parts.append(f"(Tech notes: {feature['tech_notes']})")
    return " ".join(parts)


async def _run(case_name: str) -> dict:
    case = next(c for c in EVAL_CASES if c.name == case_name)
    faithfulness, answer_relevancy, context_precision, context_recall = build_ragas_metrics()

    out: dict = {"case": case.name}

    epic = draft_epic(case.initiative_text)
    query = _build_query(epic)

    production_chunks = retrieve(query, k=RETRIEVAL_K)
    out["production_sources"] = [c.source for c in production_chunks]

    features = draft_features(epic)
    response_text = " ".join(_format_feature(f) for f in features)

    wide = _raw_retrieve(query, k=RECALL_K)
    out["wide_sources"] = [source for _, source, _ in wide]
    precision_texts = [text for text, _, _ in wide[:PRECISION_K]]
    recall_texts = [text for text, _, _ in wide]

    if not production_chunks:
        out["error"] = "No production (k=3) context retrieved - cannot score faithfulness."
        return out

    f_score = await faithfulness.ascore(
        user_input=query, response=response_text,
        retrieved_contexts=[c.text for c in production_chunks],
    )
    out["faithfulness"] = f_score.value

    ar_score = await answer_relevancy.ascore(user_input=query, response=response_text)
    out["answer_relevancy"] = ar_score.value

    cp_score = await context_precision.ascore(
        user_input=query, reference=case.reference, retrieved_contexts=precision_texts
    )
    out["context_precision"] = cp_score.value

    cr_score = await context_recall.ascore(
        user_input=query, retrieved_contexts=recall_texts, reference=case.reference
    )
    out["context_recall"] = cr_score.value

    return out


def main() -> int:
    case_name = sys.argv[1]
    try:
        result = asyncio.run(_run(case_name))
    except Exception as e:
        result = {"case": case_name, "error": f"{type(e).__name__}: {e}"}

    print("RESULT_JSON:" + json.dumps(result))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
