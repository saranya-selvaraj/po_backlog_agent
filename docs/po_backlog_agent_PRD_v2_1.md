# PO Backlog Agent v2: Product Requirements Document (POC)

*Handover doc for AI coding assistance (Claude Code). Defines WHAT to build and WHY. Supersedes `po_backlog_agent_PRD.md` v1. Tech stack for the new components (orchestration, tracing, eval) is agreed at the framework level below; specific library/tier choices are finalized in a companion build guide.*

---

## 1. Problem Statement

v1 built a working pipeline (Initiative → EPIC → RAG → Features/Stories → optional write-back) but it was a **scripted sequence of LLM calls**, not an agent: every step ran in a fixed order regardless of what the model produced, and nothing was ever decided at runtime. v2 keeps everything that made v1 reliable (structured output, RAG grounding, a mock backlog API) and adds the three things that were actually missing: a **stateful graph with a real human-in-the-loop pause**, **deterministic guardrails** around every risky action, and **one genuine agentic decision point** where the model — not the orchestration code — decides whether it has done enough work before moving on.

## 2. Goal

Build a small LangGraph-orchestrated system that demonstrates a full **Retrieve → Reason → Decide → Act** workflow, where "Decide" is a real branch taken by either a human or the model, not just a label on a fixed pipeline:

1. Raw initiative text is safety-checked, then converted to a structured EPIC (no HITL — low risk, easily reviewed downstream).
2. The EPIC is decomposed into Features and Stories, grounded in a knowledge base the agent searches **agentically** — it forms its own query, judges whether what it retrieved is good enough, and re-queries if not.
3. The full Feature/Story tree is paused for **human review** — editable, then approved or rejected.
4. On approval, the tree is published to a mock JIRA API with a **deterministic retry-and-escalate** state machine on failure.
5. Every transition is persisted to a SQL table, so the full lifecycle of an initiative is visible and auditable at all times.
6. The system is evaluated both offline (before every change) and online (from real usage/approval data).

## 3. Users

Solo builder/owner. Personal productivity tool + a reference architecture for a real company's JIRA/Confluence stack once real system access exists. Built deliberately to be interview-legible: every node should be explainable as "this is deterministic because X" or "this is agentic because Y."

## 4. Scope

### In scope
- Input safety gate (PII / financial data / prompt-injection screening) before any LLM sees raw text
- Node 1: EPIC generation (deterministic, single pass)
- Node 2: agentic RAG-grounded Feature/Story decomposition, with a self-directed retrieval loop (LLM decides query + whether to retry, capped at 2 retries)
- Lightweight quality validator pass on Features/Stories (checks the guardrail checklist from the system prompts — not just prompted, actually checked)
- Node 3: human review interrupt — edit, approve, or reject
- Node 4: publish to mock JIRA with retry/escalate state machine, **simulated time** for the retry schedule (see §9)
- SQL table tracking full initiative lifecycle, including retry sub-states
- Offline evals (RAGAS-based + deterministic guardrail tests) and a basic online eval loop (approve/reject as ground-truth feedback)
- Minimal Streamlit UI: submit initiative, watch status live, review/edit/approve, trigger the time-pass simulator, see the SQL table update in real time

### Explicitly out of scope
- Real JIRA/Confluence/AHA integration
- Real wall-clock scheduling (a live cron running for hours/days) — simulated instead, see §9
- Authentication/login — public demo, no user accounts (see §14)
- Multi-user support (single shared initiative table, not per-user)
- Version tracking/diffing after publish
- Automating live meetings, SME conversations, HLD/LLD authorship (stays human-only by design)
- Node 4 failure-*type* reasoning (retryable vs. non-retryable error classification) — deferred; v2 uses a fixed retry-then-escalate counter instead

## 5. Concept Note: What "Agentic" Means Here

This project deliberately mixes two things on purpose, and the PRD calls out which is which at every step, because conflating them is the mistake v1 made:

- **Deterministic guardrail / state machine** — code decides, always the same way given the same input (input safety gate, approval-gate check, retry counter, status transitions). Preferred wherever a wrong decision would be unacceptable or ambiguity serves no purpose.
- **Agentic decision** — the LLM decides, and the decision can genuinely vary at runtime (Node 2's retrieval loop). Used only where judgment adds real value and a wrong decision is cheap to recover from (worst case: one extra retrieval call).

Only Node 2 is agentic in this sense. Everything else is a well-designed deterministic pipeline with an LLM doing generation work inside it — and that's fine; most of a good agent system should be deterministic. The point is knowing which is which, not maximizing how much is "agentic."

## 6. Graph Design (LangGraph)

```
[raw initiative text]
        │
        ▼
 ┌─────────────────┐
 │ Node 0: Input     │  deterministic — PII/financial/injection screen,
 │ Safety Gate       │  blank/gibberish check (Section 3/4 rules)
 └─────────────────┘
        │ pass
        ▼
 ┌─────────────────┐
 │ Node 1: Epic      │  deterministic — single LLM pass, no tools
 │ Generator         │
 └─────────────────┘
        │
        ▼
 ┌─────────────────┐
 │ Node 2: Agentic   │  AGENTIC — LLM forms query, calls retrieve_context()
 │ RAG Decomposer    │  tool, judges sufficiency, re-queries up to 2x,
 │                   │  then generates Features → Stories, then a
 │                   │  deterministic quality-validator pass runs on output
 └─────────────────┘
        │
        ▼
 ┌─────────────────┐
 │ Node 3: Human     │  interrupt — pause, persist state, wait
 │ Review            │  (edits written back to SQL before continuing)
 └─────────────────┘
        │
   ┌────┴────┐
   │ Approve  │ Reject
   ▼          ▼
 ┌────────┐ ┌──────────────┐
 │ Node 4:│ │ Cancel:       │  status → 'Cancelled by User', end
 │ Publish│ │ deterministic │
 └────────┘ └──────────────┘
   │
   ├─ success → status 'Epic Published', JIRA ID stored, end
   └─ failure → retry (max 3, deterministic counter)
                  │
                  └─ still failing → notify human, status
                     'Failed – Awaiting User', offer retry-later
                     (Node 4b: simulated retry-schedule loop, §9)
```

## 7. SQL Lifecycle Table

One row per initiative; status is the single source of truth the UI reads from, and every node writes to it on every transition — this is what makes the whole run auditable and lets the UI show live state changes (including during the time-pass simulation).

**Hosting note (see §14):** locally this can be SQLite; once deployed, it lives in Supabase Postgres instead, because Render's free tier wipes the local filesystem on every idle spin-down — a hosted DB is the only way the table survives between visits.

```sql
CREATE TABLE initiative (
    initiative_id       TEXT PRIMARY KEY,      -- generated on submit
    initiative_summary  TEXT NOT NULL,          -- raw input (post-safety-gate)
    status               TEXT NOT NULL,          -- see status values below
    epic_title           TEXT,
    epic_description     TEXT,
    epic_jira_id          TEXT,                   -- mock JIRA ID, set on publish success
    retrieval_attempts    INTEGER DEFAULT 0,      -- Node 2 agentic loop count (0-2)
    publish_attempts      INTEGER DEFAULT 0,      -- Node 4 retry count (0-3)
    last_error            TEXT,                   -- last publish failure message, if any
    next_retry_at         TIMESTAMP,              -- simulated clock, Node 4b only
    created_at            TIMESTAMP DEFAULT now(),
    updated_at            TIMESTAMP DEFAULT now()
);
```

**Status values (state machine):**
`Open` → `Epic Drafted` → `Pending Review` → *(human decides)* → `Published` **or** `Cancelled by User` **or** `Failed – Retrying` → `Failed – Awaiting User` → (`Published` on later success, or stays `Failed – Awaiting User` indefinitely if user keeps declining retry)

## 8. Node 2 Detail — the Agentic Retrieval Loop

This is the node worth building carefully since it's the one genuinely agentic piece.

**Flow inside Node 2:**
1. LLM receives the EPIC (plain text — title, problem statement, scope). No embeddings anywhere near the LLM.
2. LLM writes its own plain-text search query and calls the tool `retrieve_context(query: str)`.
3. Tool (plain code): embeds the query, runs similarity search against Chroma, returns top-k chunks + source doc names as plain text. The LLM never sees a vector.
4. LLM reads the chunks and judges: are they clearly relevant to and sufficient for grounding this EPIC?
   - If yes → proceed to Feature/Story generation using these chunks.
   - If no → write a refined query, call the tool again. **Hard cap: 2 retries** (deterministic backstop — same pattern as Node 4's retry cap, so a confused model can't loop indefinitely).
5. If still unsatisfied after 2 retries, proceed anyway but explicitly note "no strongly relevant context found" in the Feature output (per v1 FR2's original acceptance criterion) rather than fabricating grounding.
6. Features/Stories generated per the existing system prompts (unchanged from your doc).
7. **Deterministic validator pass** runs against the Feature/Story guardrail checklist from your system prompts (shippable value, no technical prescriptions, INVEST fields present, ≥2 Given/When/Then AC per story, "so that" clause non-trivial). Failing items are flagged inline for the human reviewer at Node 3 rather than silently blocked — keeps the human in control of the final call.

`retrieval_attempts` is written to the SQL table after each loop iteration, so you can literally watch in the table whether the agent needed 1 or 2 or 3 tries on a given run — useful both as a demo moment and as an eval signal (see §11).

## 9. Node 4 Detail — Publish, Retry, and the Time-Pass Simulator

Your original design (retry every 2 hours until 5pm, then re-ask the human daily until resolved) is the right *target* architecture, but running it live would need a persistent scheduler (cron/Celery) waking a paused graph across real hours/days — too much infrastructure for a POC demo.

**What v2 actually builds:** the exact same state machine and status transitions, but time is **simulated**, not real:

- By default, the mock JIRA API returns success — most runs go straight to `Published` with a mock JIRA ID on the first attempt, no retry logic involved.
- The mock API also accepts a **forced-failure flag** (e.g. a UI toggle or request param) so the failure/retry/escalate path can be demonstrated on request, without success being the exception. When triggered: publish attempt fails → `publish_attempts += 1`, status → `Failed – Retrying`.
- Up to 3 automatic retries happen immediately (no real delay) against the mock API.
- Still failing after 3 → status → `Failed – Awaiting User`, human is shown "Failed to publish — JIRA appears to be down. Retry later?"
- UI has a **"Simulate time passing" control** — each click advances a simulated clock (e.g., by a simulated 2 hours) and, if the user said yes to retrying, triggers another publish attempt at that simulated time; if past simulated 5pm, prompts "retry tomorrow?" instead.
- Every simulated tick writes `next_retry_at`, `publish_attempts`, and `status` to the SQL table and the UI re-reads and displays the table live, so the status change is visibly watchable — the whole point of building it this way rather than skipping straight to "eventually published."
- If the user declines retry at any point, status stays `Failed – Awaiting User` — no further action, matches your original "leave as-is" behavior.

This keeps the demo fast (seconds, not hours) while proving the actual retry/escalate/re-ask logic works, which is what matters for the architecture story.

## 10. Guardrails

**Pre-execution (Node 0, before any LLM call sees the text) — deterministic, from your Section 3:**
- PII (names, phone, address, email, IP, national ID) → auto-redact with placeholders; if input is dominated by PII, reject entirely and ask for generalized input.
- Financial data (PANs, CVVs, IBANs, API keys/passwords) → hard block, purge from memory, security warning to user. Never passed to the LLM, not even redacted.
- Prompt injection → sanitize/strip system-level commands, or reject if it fails an injection check.
- Blank/whitespace, gibberish/low-entropy, unsupported file type, oversized input → each handled per your Section 4 table (this becomes your negative-case eval set — see §11).

**Node 3 approval gate — deterministic, code-level, not LLM judgment:**
- Publish tool call is blocked unless `status == 'approved'` in the current graph state. The LLM is never asked "should I publish?" — the check is a plain conditional in code, matching the hard-guardrail principle from the OpenClaw reference doc.

**Node 2 quality guardrails — checked, not just prompted (§8, step 7).**

## 11. Evals

**Offline (run before every prompt/graph change, against a fixed test set):**
- *RAGAS* — faithfulness and answer relevancy of Features/Stories against retrieved chunks, using your 3 seed knowledge-base docs as the corpus.
- *Guardrail correctness (deterministic pass/fail, not scored)* — every row in your Section 4 negative-case table becomes a test case: blank input → rejected; PII input → redacted; injection attempt → sanitized/rejected; oversized input → chunked. Expect 100% pass, always — any failure is a regression, not a "score."
- *Approval-gate bypass test* — assert the publish tool call is refused with `status != 'approved'` for every possible input. Also expect 100% pass, always.
- *Retrieval-loop behavior* — a small hand-built set of EPICs where you know which should need 1 retry vs 2, to sanity-check Node 2's self-assessment isn't looping needlessly or stopping too early.

**Online (from real usage, once you're actually using it):**
- Every Node 3 approve/reject/edit is free ground-truth signal — log it and periodically re-score: what fraction of Features/Stories get approved unedited vs. heavily edited vs. rejected? A rising edit-rate over time is your earliest real signal of prompt or retrieval drift.
- `retrieval_attempts` and `publish_attempts` distributions over time, pulled straight from the SQL table — no extra instrumentation needed.

## 12. Non-Functional Requirements

- Builds and runs locally first (Python 3.11+); deployed as a public portfolio link once stable (see §15).
- No secrets committed to git.
- Each node independently testable — no big-bang integration (unchanged from v1's philosophy).
- Total external cost: $0–$7/month (free-tier by default; optional $7/month Render Starter tier if always-on matters more than a cold-start delay — decided in the build guide).

## 13. Success Criteria for the POC Demo

Given a pasted initiative in the UI, the demo should visibly show, in order:
1. Input safety gate passing (or catching a deliberately bad input, on request)
2. EPIC drafted
3. Node 2's retrieval loop happening live — including a case where it needs a second retrieval, visible via `retrieval_attempts` in the table
4. Human review screen — edit some text, approve
5. Publish attempt — normally succeeds first try and shows the JIRA ID; optionally, trigger a deliberate failure on demand to show the 3 auto-retries and the "awaiting user" prompt
6. Click "simulate time passing" and watch the status/table update live through to either success or end-of-day escalation
7. An offline eval run showing the guardrail tests passing and a RAGAS score for the decomposition

## 14. Deployment & Hosting

Built local-first, deployed once stable, as a public portfolio link with no login:

- **App hosting:** Render free tier (Streamlit, or FastAPI + Streamlit as two services). Spins down after 15 min idle; ~30–60s cold start on the next visit. Upgrade path: $7/month Starter tier removes this entirely, if a cold start on a portfolio link is ever a concern.
- **Database:** Supabase Postgres hosts the initiative lifecycle table from §7 — chosen over Render's own free Postgres because Render's free DB expires 30 days after creation, while Supabase's free tier only *pauses* after 7 days of inactivity and is restorable, not deleted.
- **No auth:** the app is public — anyone with the link can submit an initiative and see the flow. This was a deliberate scope cut (see §4) rather than an oversight; it keeps the deploy simple and matches "portfolio demo," not "product with users."
- **Keep-alive job:** a scheduled GitHub Actions workflow (free on public repos) pings the Render URL and issues a lightweight Supabase query every ~10–14 minutes, so neither service goes idle long enough to spin down or pause — this is what makes "someone clicks the portfolio link at 2am and it just works" actually true. Unofficial workaround (not a guaranteed platform feature), acceptable for this use case.

## 15. What This Project Demonstrates

- A real distinction between deterministic guardrails and genuine agentic decision-making, applied consistently rather than labeled loosely
- Stateful multi-node orchestration with a true human-in-the-loop pause/resume (LangGraph interrupt)
- Self-directed tool use with a bounded retry loop (Node 2)
- A layered guardrail system: input safety, approval gating, and output quality validation, each enforced the appropriate way for its risk level
- A fully auditable lifecycle via a backing SQL state machine, with a simulated-time mechanism to demo long-running retry logic without long-running infrastructure
- Both offline (regression-style) and online (usage-driven) evaluation, tied directly to logged agent behavior rather than bolted on afterward
