"""RAGAS judge wiring: the Groq LLM as judge, local sentence-transformers
as the embedding model (matching app.rag.retrieve's own embedding model,
so answer_relevancy's similarity check runs in the same embedding space
the app's retrieval already uses - zero-cost, no extra API key needed).

Also works around a real packaging bug in ragas==0.4.3: ragas/llms/base.py
unconditionally imports ChatVertexAI/VertexAI from langchain_community,
but current langchain-community (post its 0.4.x integration sunset) no
longer bundles that module, so `import ragas` fails outright. This app
never uses the VertexAI provider, so the two symbols are stubbed out
before ragas is imported anywhere. Must be called before any `ragas.*`
import - hence its own module, imported first in every eval entry point.
"""

from __future__ import annotations

import os
import sys
import types


def _patch_ragas_vertexai_import() -> None:
    if "langchain_community.chat_models.vertexai" in sys.modules:
        return  # already patched

    vertexai_chat_mod = types.ModuleType("langchain_community.chat_models.vertexai")
    vertexai_chat_mod.ChatVertexAI = object
    sys.modules["langchain_community.chat_models.vertexai"] = vertexai_chat_mod

    import langchain_community.llms as _llms_mod

    if not hasattr(_llms_mod, "VertexAI"):
        _llms_mod.VertexAI = object


_patch_ragas_vertexai_import()

from dotenv import load_dotenv  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402
from ragas.embeddings import HuggingFaceEmbeddings  # noqa: E402
from ragas.llms import llm_factory  # noqa: E402
from ragas.metrics.collections import (  # noqa: E402
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
    Faithfulness,
)

from app.llm.client import GROQ_BASE_URL, GROQ_MODEL  # noqa: E402
from app.rag.ingest import EMBEDDING_MODEL_NAME  # noqa: E402

load_dotenv()


def build_ragas_metrics():
    """Return (faithfulness, answer_relevancy, context_precision, context_recall),
    all wired to the Groq LLM (async client - .ascore() requires it) and to
    the app's own local embedding model.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set. Add it to a .env file at the project root.")

    # context_precision/context_recall each issue several sequential judge
    # calls (one per retrieved chunk). Without an explicit timeout, a single
    # stalled Groq response can block far longer than the SDK's own generous
    # default - observed as a multi-minute hang on one case even with an
    # outer asyncio.wait_for() in the eval script, since a stuck HTTP read
    # doesn't reliably respond to asyncio-level cancellation through every
    # layer (httpx/instructor/tenacity). A hard per-request timeout at the
    # client itself is a firmer bound than relying on cooperative cancellation.
    #
    # openai/gpt-oss-20b also carries its own tight TOKENS-PER-MINUTE limit
    # (8000 TPM, separate from the daily cap on the 120b model) - a case's
    # handful of calls can burn most of that budget, and Groq's 429 response
    # names a wait ("Please try again in Xs") typically well under 10s. The
    # openai SDK's built-in retry-with-backoff (max_retries) respects that
    # signal, so raising it from the default lets a 429 self-heal within a
    # case instead of failing it outright; offline_eval.py also paces launches
    # between cases so usage has time to fall back under budget.
    async_client = AsyncOpenAI(api_key=api_key, base_url=GROQ_BASE_URL, timeout=30.0, max_retries=5)
    # ragas' InstructorLLM defaults to max_tokens=1024, which is enough for a
    # normal chat model but not for openai/gpt-oss-120b: it's a reasoning
    # model that spends completion tokens on internal chain-of-thought before
    # emitting the final JSON, so 1024 was getting exhausted before the judge
    # could produce valid structured output (json_validate_failed / "max
    # completion tokens reached"). Bumped well above what the judge prompts
    # (statement lists, NLI verdicts) actually need once reasoning is included.
    #
    # reasoning_effort="low" (a Groq/gpt-oss-specific param) caps how much
    # chain-of-thought the model spends per call. These judge prompts are
    # simple classification/extraction tasks (list statements, verdict
    # true/false), not tasks that benefit from deep reasoning, and without
    # this the model's default ("medium") effort made individual judge calls
    # slow enough that a 4-case eval could stall for many minutes.
    ragas_llm = llm_factory(
        GROQ_MODEL, provider="openai", client=async_client,
        max_tokens=8192, reasoning_effort="low",
    )
    ragas_embeddings = HuggingFaceEmbeddings(model=EMBEDDING_MODEL_NAME, use_api=False)

    faithfulness = Faithfulness(llm=ragas_llm)
    answer_relevancy = AnswerRelevancy(llm=ragas_llm, embeddings=ragas_embeddings)
    context_precision = ContextPrecision(llm=ragas_llm)
    context_recall = ContextRecall(llm=ragas_llm)

    return faithfulness, answer_relevancy, context_precision, context_recall
