"""Offline RAGAS eval for v1's fixed, one-shot RAG pipeline (EPIC -> RAG
retrieval -> Features). Not agentic - this scores the pipeline as it
actually runs today (app.agent.features.draft_features, k=3 retrieval),
so a regression in prompt, retrieval, or corpus content shows up as a
score drop here before it reaches a user.

Two retrieval widths are checked per case, deliberately different from
the k=3 the app uses in production:
  - RECALL_K=10:    a wide net - "does the corpus have this at all",
                     independent of the app's fixed relevance cutoff.
  - PRECISION_K=5:  the top slice of that same ranked list - "how clean
                     is what would realistically surface".
Faithfulness and answer_relevancy are scored against the real production
k=3 context and the real generated Features text, since those are the
only two steps that actually feed the LLM in this app.

Thresholds (see PR discussion for reasoning):
  faithfulness      >= 0.70   (production k=3 context)
  answer_relevancy  >= 0.70   (production k=3 context)
  context_recall    >= 0.70   (wide net, k=10)
  context_precision >= 0.80   (narrow cut, k=5)

Each case runs in its own subprocess with a hard wall-clock timeout
(CASE_TIMEOUT_SECONDS). This is a deliberate choice, not the obvious one:
an in-process asyncio.wait_for() guard around each judge call was tried
first, but on Windows' default ProactorEventLoop, cancelling a Task stuck
on a pending socket read does not reliably interrupt it - the guard was
observed not to fire even minutes past its deadline. subprocess.run(...,
timeout=...) kills the child at the OS level regardless of what it's
blocked on, which is a real bound.

Run with:
    python -m app.evals.offline_eval
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

from app.evals.dataset import EVAL_CASES, EvalCase

RECALL_K = 10
PRECISION_K = 5

FAITHFULNESS_THRESHOLD = 0.70
ANSWER_RELEVANCY_THRESHOLD = 0.70
CONTEXT_RECALL_THRESHOLD = 0.70
CONTEXT_PRECISION_THRESHOLD = 0.80

CASE_TIMEOUT_SECONDS = 180

# openai/gpt-oss-20b (the eval's current judge model, see app/llm/client.py)
# has an 8000 tokens-per-minute limit. A case's own calls can consume most
# of that budget, so pause between cases to let usage fall back under it
# rather than starting the next case's calls straight into a 429.
INTER_CASE_PAUSE_SECONDS = 30


class CaseScores:
    def __init__(self, case: EvalCase):
        self.case = case
        self.faithfulness: float | None = None
        self.answer_relevancy: float | None = None
        self.context_precision: float | None = None
        self.context_recall: float | None = None
        self.production_sources: list[str] = []
        self.wide_sources: list[str] = []
        self.error: str | None = None

    def passed(self) -> bool:
        if self.error is not None:
            return False
        return (
            self.faithfulness is not None and self.faithfulness >= FAITHFULNESS_THRESHOLD
            and self.answer_relevancy is not None and self.answer_relevancy >= ANSWER_RELEVANCY_THRESHOLD
            and self.context_precision is not None and self.context_precision >= CONTEXT_PRECISION_THRESHOLD
            and self.context_recall is not None and self.context_recall >= CONTEXT_RECALL_THRESHOLD
        )


def score_case(case: EvalCase) -> CaseScores:
    result = CaseScores(case)

    try:
        proc = subprocess.run(
            [sys.executable, "-u", "-m", "app.evals._run_one_case", case.name],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=CASE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        result.error = f"Timed out after {CASE_TIMEOUT_SECONDS}s (subprocess killed)"
        return result

    result_line = next(
        (line for line in proc.stdout.splitlines() if line.startswith("RESULT_JSON:")), None
    )
    if result_line is None:
        result.error = f"No result from subprocess (exit {proc.returncode}). stderr: {proc.stderr[-1000:]}"
        return result

    data = json.loads(result_line[len("RESULT_JSON:"):])

    if "error" in data:
        result.error = data["error"]
        return result

    result.production_sources = data["production_sources"]
    result.wide_sources = data["wide_sources"]
    result.faithfulness = data["faithfulness"]
    result.answer_relevancy = data["answer_relevancy"]
    result.context_precision = data["context_precision"]
    result.context_recall = data["context_recall"]
    return result


def _fmt(value: float | None, threshold: float) -> str:
    if value is None:
        return "  n/a "
    mark = "OK" if value >= threshold else "!!"
    return f"{value:.3f} {mark}"


def main() -> int:
    print("=== Offline RAGAS eval: EPIC -> RAG retrieval -> Features ===")
    print(f"Thresholds: faithfulness>={FAITHFULNESS_THRESHOLD}, answer_relevancy>={ANSWER_RELEVANCY_THRESHOLD}, "
          f"context_precision@{PRECISION_K}>={CONTEXT_PRECISION_THRESHOLD}, context_recall@{RECALL_K}>={CONTEXT_RECALL_THRESHOLD}\n")

    all_results: list[CaseScores] = []
    for i, case in enumerate(EVAL_CASES):
        if i > 0:
            time.sleep(INTER_CASE_PAUSE_SECONDS)
        print(f"--- {case.name} ---", flush=True)
        r = score_case(case)
        all_results.append(r)

        if r.error:
            print(f"  ERROR: {r.error}\n", flush=True)
            continue

        print(f"  Retrieved sources (k=3, production):  {r.production_sources}")
        print(f"  Retrieved sources (k={RECALL_K}, wide):          {r.wide_sources}")
        print(f"  Expected sources:                      {sorted(case.expected_sources)}")
        print(f"  faithfulness           = {_fmt(r.faithfulness, FAITHFULNESS_THRESHOLD)}")
        print(f"  answer_relevancy       = {_fmt(r.answer_relevancy, ANSWER_RELEVANCY_THRESHOLD)}")
        print(f"  context_precision@{PRECISION_K}    = {_fmt(r.context_precision, CONTEXT_PRECISION_THRESHOLD)}")
        print(f"  context_recall@{RECALL_K}       = {_fmt(r.context_recall, CONTEXT_RECALL_THRESHOLD)}")
        print("  PASS" if r.passed() else "  FAIL", flush=True)
        print()

    print("=== Summary ===")
    passed = sum(r.passed() for r in all_results)
    total = len(all_results)
    for r in all_results:
        status = "PASS" if r.passed() else "FAIL"
        print(f"  [{status}] {r.case.name}")
    print(f"\n{passed}/{total} cases passed all four metric thresholds.")

    return 0 if passed == total else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
