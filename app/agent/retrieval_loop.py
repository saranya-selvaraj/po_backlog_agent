"""Node 2, part 1 - the agentic retrieval loop (PRD §8 steps 1-5).

The LLM reads an EPIC (or a Feature) as plain text, writes its own search
query, and calls the bound tool `retrieve_context(query)`. The tool is plain
code: it embeds the query, searches Chroma and returns chunks as text - the
LLM never sees a vector and never chooses filters. After each result the LLM
judges sufficiency (wording confirmed by the PM) and either refines its query
or stops with a JSON verdict.

The retry cap is a code-level backstop the LLM cannot override:
  1. the tool executor refuses any search beyond MAX_SEARCHES,
  2. once the cap is hit the API call is made with tool_choice="none",
  3. the loop itself runs a bounded number of turns.

`attempts` counts retrieve_context calls that actually executed:
1 = first query sufficed, 3 = both retries used.

Run standalone to watch the loop on two sample EPICs:
    python -m app.agent.retrieval_loop
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import openai

from app.llm.client import chat_with_tools
from app.rag.ingest import GRANULAR_DOC_TYPES, HIGH_LEVEL_DOC_TYPES
from app.rag.retrieve import RetrievedChunk, retrieve

MAX_RETRIES = 2  # hard cap from PRD §8
MAX_SEARCHES = 1 + MAX_RETRIES
RETRIEVAL_K = 3  # chunks returned per search
MAX_CONTEXT_CHUNKS = 6  # chunks handed to generation after de-duplication
LOOP_TEMPERATURE = 0.3
NO_CONTEXT_MESSAGE = "No strongly relevant context found in the knowledge base."

PHASE_FEATURE = "feature"
PHASE_STORY = "story"

# --- PM-confirmed wording (Stage 3, points 2 and follow-ups) ------------------
SUFFICIENCY_INSTRUCTION = """After each retrieve_context result, judge whether the chunks are sufficient to ground this {subject}.

The chunks are SUFFICIENT if they are clearly relevant to the {subject}'s problem or scope AND contain at least one concrete, usable fact (a policy, constraint, requirement, or design detail) that you would actually reflect in a {target}. They do not need to cover every in-scope item.

The chunks are NOT sufficient if they are empty, about a different topic, or only generic/tangential.

If NOT sufficient, call retrieve_context again with a refined query. Say what was missing, and change the key terms (do not just rephrase the same query). If sufficient, stop searching."""

QUERY_GUIDANCE = {
    PHASE_FEATURE: (
        "Your query must cover the high level concepts from the docs such as "
        "architecture, functional requirements, workflows, integrations."
    ),
    PHASE_STORY: (
        "Your query must cover the granular level concepts from the docs such as "
        "use cases, database models, API, rules, etc."
    ),
}
PHASE_WORDS = {
    PHASE_FEATURE: {"subject": "EPIC", "target": "Feature"},
    PHASE_STORY: {"subject": "Feature", "target": "user Story"},
}

SYSTEM_PROMPT_TEMPLATE = """You are the research step of a product-backlog agent. Your job is to find grounding context in an internal knowledge base (business cases, design docs, policy docs) for the {subject} below, so it can be decomposed into {target}s.

You have one tool: retrieve_context(query). It searches the knowledge base with a plain-text query and returns text chunks labeled with their source filename.

WRITING YOUR QUERY
Write a short, specific plain-text query built from the key terms of the {subject}. {guidance}

JUDGING WHAT COMES BACK
{sufficiency}

LIMITS
Always call retrieve_context first. You may search at most {max_searches} times in total (one initial search plus {max_retries} retries); the system enforces this and will remove the search tool once the limit is reached. When you are done searching, call submit_verdict with your final judgement. Set sufficient=true only if the chunks you have seen meet the standard above."""

RETRIEVE_TOOL = {
    "type": "function",
    "function": {
        "name": "retrieve_context",
        "description": (
            "Search the internal knowledge base with a plain-text query. Returns the most "
            "relevant text chunks, each labeled with its source document filename."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Plain-text search query."}},
            "required": ["query"],
        },
    },
}
VERDICT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_verdict",
        "description": "Report your final judgement on whether the retrieved chunks are sufficient. Ends the search.",
        "parameters": {
            "type": "object",
            "properties": {
                "sufficient": {"type": "boolean", "description": "True only if the chunks meet the sufficiency standard."},
                "reason": {"type": "string", "description": "One sentence explaining the judgement."},
            },
            "required": ["sufficient", "reason"],
        },
    },
}
FORCE_RETRIEVE = {"type": "function", "function": {"name": "retrieve_context"}}
FORCE_VERDICT = {"type": "function", "function": {"name": "submit_verdict"}}


def build_system_prompt(phase: str) -> str:
    words = PHASE_WORDS[phase]
    return SYSTEM_PROMPT_TEMPLATE.format(
        **words,
        guidance=QUERY_GUIDANCE[phase],
        sufficiency=SUFFICIENCY_INSTRUCTION.format(**words),
        max_searches=MAX_SEARCHES,
        max_retries=MAX_RETRIES,
    )


# ---------------------------------------------------------------------------
# Plain-text views of the EPIC / Feature (no embeddings, no JSON blobs)
# ---------------------------------------------------------------------------
def epic_to_text(epic: dict) -> str:
    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {i}" for i in items) or "- (none)"

    return (
        f"EPIC TITLE: {epic['title']}\n"
        f"PROBLEM STATEMENT: {epic['problem_statement']}\n"
        f"BUSINESS VALUE: {epic['business_value']}\n"
        f"IN SCOPE:\n{bullets(epic['in_scope'])}\n"
        f"OUT OF SCOPE:\n{bullets(epic['out_of_scope'])}"
    )


def feature_to_text(feature: dict, epic: dict) -> str:
    reqs = "\n".join(f"- {r}" for r in feature.get("high_level_requirements", [])) or "- (none)"
    return (
        f"FEATURE: {feature['title']}\n"
        f"VALUE STATEMENT: {feature.get('value_statement', '')}\n"
        f"HIGH-LEVEL REQUIREMENTS:\n{reqs}\n"
        f"PARENT EPIC: {epic['title']} - {epic['problem_statement']}"
    )


# ---------------------------------------------------------------------------
# The tool (plain code)
# ---------------------------------------------------------------------------
def _phase_filter(phase: str) -> dict:
    """Soft, code-applied metadata filter: Feature search skips granular doc
    types, Story search skips high-level ones. Untagged ('general') and other
    doc types are never excluded."""
    excluded = GRANULAR_DOC_TYPES if phase == PHASE_FEATURE else HIGH_LEVEL_DOC_TYPES
    return {"doc_type": {"$nin": list(excluded)}}


def retrieve_context(query: str, phase: str, boost_text: str) -> tuple[list[RetrievedChunk], bool]:
    """The bound tool body. Returns (chunks, widened). If the phase filter leaves
    nothing, the search is repeated over all doc types (widened=True) so the loop
    never dead-ends on a tagging quirk."""
    chunks = retrieve(query, k=RETRIEVAL_K, where=_phase_filter(phase), boost_text=boost_text)
    if chunks:
        return chunks, False
    return retrieve(query, k=RETRIEVAL_K, boost_text=boost_text), True


def format_tool_result(query: str, chunks: list[RetrievedChunk], widened: bool, attempt: int) -> str:
    left = MAX_SEARCHES - attempt
    header = f'Search {attempt} of {MAX_SEARCHES} for query: "{query}". Searches remaining: {left}.'
    if widened:
        header += " (No chunks matched the preferred document types, so all document types were searched.)"
    if not chunks:
        return f"{header}\nNo chunks met the relevance threshold for this query."
    body = "\n\n".join(
        f"[{i}] Source: {c.source} | type: {c.doc_type} | relevance: {c.score:.2f}\n{c.text}"
        for i, c in enumerate(chunks, 1)
    )
    return f"{header}\n\n{body}"


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------
@dataclass
class RetrievalResult:
    attempts: int  # retrieve_context calls that actually executed (1-3)
    sufficient: bool
    reason: str
    capped: bool  # True if the hard cap was reached (LLM was not allowed to search again)
    chunks: list[RetrievedChunk] = field(default_factory=list)  # context for generation ([] if insufficient)
    searches: list[dict] = field(default_factory=list)  # per-attempt trace

    @property
    def context_text(self) -> str:
        if not self.chunks:
            return NO_CONTEXT_MESSAGE
        return "\n\n".join(f"[Source: {c.source}]\n{c.text}" for c in self.chunks)

    @property
    def sources(self) -> list[str]:
        return sorted({c.source for c in self.chunks})

    def trace(self) -> dict:
        """JSON-serialisable summary for graph state (chunk text is left out)."""
        return {
            "attempts": self.attempts,
            "sufficient": self.sufficient,
            "reason": self.reason,
            "capped": self.capped,
            "searches": self.searches,
            "context_sources": self.sources,
        }


def _parse_verdict(text: str) -> tuple[bool | None, str]:
    cleaned = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict) and isinstance(data.get("sufficient"), bool):
            return data["sufficient"], str(data.get("reason", "")).strip()
    except json.JSONDecodeError:
        pass
    match = re.search(r'"sufficient"\s*:\s*(true|false)', cleaned, re.I)
    if match:
        return match.group(1).lower() == "true", ""
    return None, ""


def _verdict_from_call(call: dict) -> tuple[bool | None, str]:
    try:
        args = json.loads(call["function"]["arguments"] or "{}")
    except json.JSONDecodeError:
        return None, ""
    sufficient = args.get("sufficient")
    return (sufficient if isinstance(sufficient, bool) else None), str(args.get("reason", "")).strip()


def _query_from_call(call: dict) -> str | None:
    try:
        query = json.loads(call["function"]["arguments"] or "{}").get("query")
    except (json.JSONDecodeError, AttributeError):
        return None
    return query.strip() if isinstance(query, str) and query.strip() else None


def run_retrieval_loop(phase: str, subject_text: str, boost_text: str) -> RetrievalResult:
    """Run the agentic loop for `phase` (PHASE_FEATURE / PHASE_STORY).

    subject_text: plain-text EPIC or Feature shown to the LLM.
    boost_text: text whose words are matched against doc topics for ranking.
    """
    messages: list[dict] = [
        {"role": "system", "content": build_system_prompt(phase)},
        {"role": "user", "content": subject_text},
    ]
    attempts = 0
    searches: list[dict] = []
    pool: dict[tuple[str, int], RetrievedChunk] = {}
    last_search_had_chunks = False
    verdict: bool | None = None
    reason = ""

    for _ in range(MAX_SEARCHES + 3):  # backstop 3: bounded turns, a confused model cannot loop
        # Backstop 2: nudge behavior via tool_choice, but keep both tools declared on every
        # call - some Groq-hosted models will still emit an *undeclared* tool name despite a
        # forced tool_choice, which the API then hard-rejects with a 400. Declaring both and
        # forcing which one to use avoids that, and the executor below (backstop 1) is what
        # actually refuses a retrieve_context call once the cap is reached.
        tools = [RETRIEVE_TOOL, VERDICT_TOOL]
        if attempts == 0:
            tool_choice = FORCE_RETRIEVE  # must search before judging
        elif attempts < MAX_SEARCHES:
            tool_choice = "auto"
        else:
            tool_choice = FORCE_VERDICT  # cap reached
        try:
            reply = chat_with_tools(messages, tools, tool_choice=tool_choice, temperature=LOOP_TEMPERATURE)
        except openai.BadRequestError as e:
            # Observed in practice: some Groq-hosted models occasionally emit a tool call the
            # API rejects even when declared correctly. Don't let a single malformed turn take
            # down the whole run - stop searching and fall back below.
            reason = f"Model/tool-call error, stopped searching early: {e}"
            break
        messages.append(reply)

        calls = reply.get("tool_calls") or []
        if not calls:  # answered in plain text instead of calling a tool
            verdict, reason = _parse_verdict(reply["content"])
            break

        done = False
        for i, call in enumerate(calls):
            name = call["function"]["name"]
            if name == "submit_verdict" and i == 0 and attempts > 0:
                verdict, reason = _verdict_from_call(call)
                done = verdict is not None
                content = "Verdict recorded." if done else "Refused: submit_verdict needs a boolean 'sufficient'."
            elif name == "retrieve_context" and i == 0:
                query = _query_from_call(call)
                if attempts >= MAX_SEARCHES:  # backstop 1: the executor itself refuses
                    content = "Refused: the search limit has been reached."
                elif query is None:
                    content = "Refused: retrieve_context needs a non-empty plain-text 'query' string."
                else:
                    attempts += 1
                    chunks, widened = retrieve_context(query, phase, boost_text)
                    last_search_had_chunks = bool(chunks)
                    for c in chunks:
                        key = (c.source, c.chunk_index)
                        if key not in pool or c.score > pool[key].score:
                            pool[key] = c
                    searches.append(
                        {
                            "attempt": attempts,
                            "query": query,
                            "widened_to_all_doc_types": widened,
                            "results": [
                                {"source": c.source, "chunk": c.chunk_index, "doc_type": c.doc_type,
                                 "score": c.score, "boost": round(c.boost, 2)}
                                for c in chunks
                            ],
                        }
                    )
                    content = format_tool_result(query, chunks, widened, attempts)
            else:
                content = "Refused: one tool call per turn, and only after reading search results."
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
        if done:
            break

    if verdict is None:  # no parseable verdict: fall back to what the last search returned
        verdict = last_search_had_chunks
        reason = reason or "No parseable verdict from the model; inferred from the last search result."
    if not pool:  # deterministic sanity check: nothing retrieved can never be 'sufficient'
        verdict = False
        reason = reason or "No chunks were retrieved."

    context = (
        sorted(pool.values(), key=lambda c: c.score + c.boost, reverse=True)[:MAX_CONTEXT_CHUNKS]
        if verdict
        else []
    )
    return RetrievalResult(
        attempts=attempts,
        sufficient=verdict,
        reason=reason,
        capped=attempts >= MAX_SEARCHES,
        chunks=context,
        searches=searches,
    )


# ---------------------------------------------------------------------------
# Manual testing
# ---------------------------------------------------------------------------
SAMPLE_EPICS: dict[str, dict] = {}  # filled in below


def _print_result(label: str, epic: dict, result: RetrievalResult) -> None:
    print(f"\n=== {label} ===")
    print(f"EPIC: {epic['title']}")
    for s in result.searches:
        widened = "  [widened to all doc types]" if s["widened_to_all_doc_types"] else ""
        print(f"  attempt {s['attempt']}: query = {s['query']!r}{widened}")
        if not s["results"]:
            print("      (no chunks above the relevance threshold)")
        for r in s["results"]:
            print(f"      {r['score']:.3f} (+{r['boost']:.2f})  {r['source']} [{r['doc_type']}] chunk {r['chunk']}")
    print(f"  retrieval_attempts = {result.attempts}   capped = {result.capped}")
    print(f"  verdict: sufficient={result.sufficient} - {result.reason}")
    print(f"  context handed to generation: {result.sources or NO_CONTEXT_MESSAGE}")


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    for label, sample_epic in SAMPLE_EPICS.items():
        text = epic_to_text(sample_epic)
        _print_result(label, sample_epic, run_retrieval_loop(PHASE_FEATURE, text, text))
