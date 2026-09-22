# PO Backlog Agent v2: Build Guide

*Companion to `po_backlog_agent_PRD_v2.md`. Build on a new branch (e.g. `v2-agentic-langgraph`) off the existing repo.*

## How this guide works

This is a **Claude-assisted build, not an auto-build**. For every stage below:
1. Claude explains what the stage does and why, in plain terms.
2. If the stage needs a PM/PO decision (a system prompt, a guardrail rule, a threshold, an eval rubric — anything that's a judgment call rather than pure implementation), Claude stops and asks for it explicitly, rather than inventing one.
3. Claude takes your answer, improvises the implementation around it, and gives you the code/commands for **that stage only**.
4. **You** run the commands and review the code — Claude does not execute the build across stages unattended.
5. You confirm the stage works before moving to the next one — no big-bang integration, same philosophy as v1.

Stages are ordered to match the graph in PRD §6, so you can build and test each node before wiring the next one on.

---

## Stage 0 — Repo, Branch, Environment

**What:** Set up the new branch and a clean environment for the new dependencies.

**No PM decision needed here** — pure setup.

**Steps:**
1. `git checkout -b v2-agentic-langgraph`
2. New dependencies on top of v1's: `langgraph`, `langsmith`, `ragas`, `supabase` (Python client), `python-dotenv` if not already present.
3. New `.env` entries (gitignored): `LANGSMITH_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` (leave Supabase ones blank until Stage 8 — local dev can run on SQLite first, per PRD §7's hosting note).
4. Confirm v1's existing pieces still run on the new branch (Groq call, Chroma retrieval, FastAPI mock API) before adding anything new.

---

## Stage 1 — Node 0: Input Safety Gate

**What:** The deterministic pre-check every raw initiative passes through before any LLM sees it — PII/financial/injection screening plus the blank/gibberish/oversized checks from PRD §10.

**PM decision needed before Claude writes this:**
- Exact PII categories to redact vs. reject outright (PRD lists names/phone/address/email/IP/national ID as redact, financial data as hard-block — confirm this split, or adjust it).
- What counts as "input dominated by PII" for the reject threshold (e.g. >50% of the text is redacted spans?).
- Any additions to the negative-case list from your original doc's Section 4 (blank, gibberish, unsupported file, oversized) — confirm the list is complete or add cases.

→ **Claude will ask you for these before generating Node 0's code.**

**Steps once decided:**
1. Claude writes the gate as a plain Python function (regex/rule-based, not an LLM call — this stays deterministic per PRD §10).
2. You test it against a handful of inputs you write yourself (clean, PII-laden, injection attempt, blank) to confirm it behaves the way you intended.

---

## Stage 2 — Node 1: EPIC Generator

**What:** Single LLM pass, raw text → structured EPIC. No tools, no loop — the simplest node.

**PM decision needed before Claude writes this:**
- The exact system prompt (you already have a draft in `PO_Agent_Revised.docx` — confirm you want to use it as-is, or paste the version you want built against).
- Model/temperature choice for this node (a drafting task like this usually wants low temperature for consistency — confirm or override).

**Steps once decided:**
1. Claude wires the prompt into a LangGraph node that calls Groq and parses the JSON EPIC shape from v1's FR1.
2. You run it against 2–3 sample initiatives and check the EPIC output against your own judgment of "good."

---

## Stage 3 — Node 2: Agentic RAG Decomposer

**What:** The centerpiece — LLM forms its own retrieval query, judges sufficiency, retries up to 2x, then generates Features/Stories, then a deterministic validator checks the output. Full mechanics in PRD §8.

**PM decisions needed before Claude writes this (several — this is the most decision-heavy stage):**
- Feature and Story system prompts — again, you have drafts in your doc; confirm or provide final versions.
- The exact wording of the "judge sufficiency" instruction — how strict should the model be about calling retrieved chunks "good enough"? Too lenient defeats the point of the loop; too strict burns retries needlessly.
- The quality-validator checklist and its pass/fail rule (PRD §8 step 7 lists shippable value, no technical prescriptions, INVEST fields, ≥2 AC per story, non-trivial "so that" — confirm this list and decide: hard block on failure, or flag-and-let-human-decide as currently scoped?).

→ **Claude will ask for each of these in turn before building the corresponding piece — this stage will likely take a few back-and-forth rounds with you, by design.**

**Steps once decided:**
1. Claude builds `retrieve_context()` as a bound tool and wires the retrieval loop with the 2-retry cap.
2. Claude builds the Feature/Story generation step using your prompts.
3. Claude builds the validator as a separate deterministic function (not another LLM call, unless you'd rather it be an LLM-graded check — your call).
4. You test with an EPIC you expect to need 1 retrieval and one you expect to need 2, and confirm `retrieval_attempts` reflects reality.

---

## Stage 4 — SQL Lifecycle Table

**What:** The table from PRD §7, running locally on SQLite for now (Supabase comes in Stage 8).

**No major PM decision needed** — schema and status values are already settled in the PRD; flag here only if you want to rename/add fields.

**Steps:**
1. Claude gives you the table-creation script and a small data-access module (insert/update functions each node calls).
2. You wire Nodes 0–2 to write to it at each transition and confirm rows appear/update as expected by querying the table directly.

---

## Stage 5 — Node 3: Human Review Interrupt

**What:** LangGraph `interrupt()` pauses the graph; Streamlit shows the Feature/Story tree (plus any validator flags from Stage 3) for editing; approve writes edits back to the table before resuming, reject cancels.

**PM decision needed before Claude writes this:**
- What exactly should be editable in the UI (full free-text edit of each Feature/Story, or structured field-by-field edit)?
- How validator-flagged items should be shown to you (inline warning badges? a separate "needs attention" list?).

**Steps once decided:**
1. Claude builds the Streamlit review screen and the resume-graph logic.
2. You do a manual end-to-end test: submit → review → edit something → approve, and confirm the SQL table shows your edited text, not the original.

---

## Stage 6 — Node 4: Publish, Retry, Time-Pass Simulator, and API Access Control

**What:** Publish to mock JIRA (succeeds by default, forced-failure flag available per PRD §9), 3-retry cap, escalate-to-user on continued failure, simulated clock for the retry schedule — plus a service-account API key gating the publish endpoints (PRD §9's access-control addition).

**No major PM decision needed** — mechanics are fully specified in PRD §9; flag here only if you want the retry count or simulated-hour increments changed.

**Steps:**
1. Claude adds the forced-failure flag to the mock API and the retry/escalate logic to the graph.
2. Claude adds the API key check (FastAPI `APIKeyHeader` dependency) to the POST endpoints only, validated against an env var, and wires the `create_backlog_item()` tool to send it as a header on every call.
3. Claude builds the "Simulate time passing" control and wires it to advance `next_retry_at` and re-trigger publish attempts.
4. You test both paths: a clean run (straight to Published) and a forced-failure run (watch it go through 3 retries, hit "awaiting user," then simulate time forward to resolution) — confirming the table updates live as we discussed. Also confirm a request *without* the API key gets rejected, so the access control is actually doing something.

---

## Stage 7 — Offline Evals

**What:** RAGAS scoring + the deterministic guardrail/negative-case test suite from PRD §11.

**PM decision needed before Claude writes this:**
- RAGAS pass threshold — what faithfulness/relevancy score counts as "acceptable" for your corpus size (this is genuinely a judgment call; Claude can suggest a reasonable starting number, but it's yours to set).
- Confirm the full negative-case test list from Stage 1 is what gets encoded as the guardrail test suite (should already match).

**Steps once decided:**
1. Claude writes the RAGAS eval script against your 3-doc corpus and a small hand-built EPIC test set.
2. Claude writes the guardrail test suite (pytest-style, deterministic pass/fail).
3. You run both, review the actual scores/results, and adjust the threshold if the number surprises you.

---

## Stage 8 — Online Evals + Deployment (Supabase + Render)

**What:** Swap SQLite for Supabase Postgres, add the LangSmith tracing hooks, wire the approve/reject logging from PRD §11's online-eval section, then deploy per PRD §14.

**PM decision needed before Claude writes this:**
- Free Render tier (accept occasional cold starts) vs. $7 Starter (always-on) — your call from PRD §14.
- Any specific fields you want visible on the public demo vs. hidden (e.g., do you want the raw LangSmith trace link exposed publicly, or kept private to you?).

**Steps once decided:**
1. Claude gives you the Supabase project setup steps (you create the project and paste the URL/key — Claude doesn't have access to create it for you).
2. Claude migrates the data-access module from Stage 4 to point at Supabase instead of SQLite.
3. Claude adds LangSmith tracing calls and the approve/reject logging.
4. Claude gives you the `render.yaml` / deploy steps and the GitHub Actions keep-alive workflow file.
5. You do the actual Render/Supabase account creation and deploy click-through yourself (these are account-level actions Claude shouldn't do on your behalf) — Claude walks you through each screen.
6. You confirm the public link works, survives an idle gap, and the table updates are visible.

---

## What's deliberately NOT a separate stage

Node 4's optional failure-type reasoning and any multi-user/auth work stay out per PRD §4 — no stage for them here. If you want either later, it's a new stage appended to this guide, not a retrofit into an existing one.
