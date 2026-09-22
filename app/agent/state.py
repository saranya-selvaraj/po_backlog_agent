"""Shared LangGraph state for the v2 backlog agent (PRD §6).

Plain, JSON-serialisable values only, so the state can later be persisted
(Node 3 interrupt / SQL lifecycle table) without conversion.
"""

from __future__ import annotations

from typing import TypedDict


class GraphState(TypedDict, total=False):
    raw_text: str  # input: the raw initiative text
    filename: str | None  # input: optional source filename (file-type check)
    gate: dict  # Node 0: GateResult as a dict (passed, reason, message, flags, redactions, ...)
    clean_text: str  # Node 0 output: sanitized text; the only text any LLM node may see
    epic: dict  # Node 1 output: title, problem_statement, business_value, in_scope, out_of_scope
    features: list[dict]  # Node 2 output: Features, each with "stories" and "validation_flags"
    retrieval_attempts: int  # Node 2: Feature-level retrieval loop attempt count (1-3), for the SQL table
    node2_trace: dict  # Node 2: full retrieval trace (feature + per-feature story loops)
    error: dict | None  # {"stage", "code", "message"} - set when a node stops the run
