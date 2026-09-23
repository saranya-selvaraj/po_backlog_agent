# PO Backlog Agent

A small multi-agent system that turns a raw, unstructured initiative into a structured backlog — EPIC → Features → Stories with Acceptance Criteria — demonstrating a full **Retrieve → Reason → Decide → Act** agentic workflow: RAG over a local knowledge base, tool/function calling, and a two-agent handoff.

## What it does

1. **Agent 1 (Synthesizer)** takes raw initiative text (e.g. messy meeting notes) and drafts a structured EPIC (title, problem statement, business value, in/out of scope).
2. **Agent 2 (Decomposer)** retrieves relevant context from a local knowledge base via RAG, then decomposes the EPIC into 2–5 Features, and each Feature into 2–4 user Stories with Given/When/Then Acceptance Criteria.
3. The resulting EPIC → Feature → Story tree can optionally be written to a mock backlog API (standing in for a real system like JIRA).
4. A Streamlit UI ties the flow together end to end.

## Architecture

```
INPUT LAYER
  Raw Initiative Text (pasted into UI)        Knowledge Base (3 seed docs:
        |                                      business case, design doc, policy doc)
        v                                              |
PROCESSING LAYER                                        | (embedded locally via
  AGENT 1 — Synthesizer                                 |  sentence-transformers,
  Initiative -> structured EPIC                         |  stored in local Chroma)
  (pure generation, no tools)                            |
        |                                                |
        v  (handoff)                                     |
  EPIC object -----------------------------------> AGENT 2 — Decomposer
                                                    EPIC -> Features -> Stories + AC
                                                    Tools it can call:
                                                      - retrieve_context()   <-- RAG query
                                                      - create_backlog_item()
        |                                                |
        v                                                v
OUTPUT LAYER
  Streamlit UI                                   Mock Backlog API (FastAPI)
  EPIC + retrieved context                       /epics /features /stories
  + Features + Stories                                   |
                                                           v
                                                  In-memory / JSON store
```

Local, zero-cost components throughout: embeddings and vector search run entirely on-machine (no external quota to manage); the only network call is to the Groq LLM API.

## What's automated vs. kept human

This project deliberately automates only the two steps of a real backlog-creation workflow that are well-suited to LLM reasoning. Everything else stays human by design:

| Step | Automated here? |
|---|---|
| Gather input from meetings, tickets, business cases | **No — human-only.** Requires live conversation and judgment. |
| Synthesize input into a structured EPIC | **Yes — Agent 1.** |
| Research internal docs for context | **Yes — Agent 2, via RAG.** |
| Explore the product, meet SMEs/architects | **No — human-only.** Requires hands-on exploration and relationships. |
| Refine EPIC into Features with tech input | **Assisted — Agent 2 drafts, a human validates.** |
| HLD/LLD, test plan authorship | **No — out of scope.** Owned by Tech Lead/QA, not this agent. |
| Sign-off / approval | **No — human-only, by design.** Governance should never be agent-automated. |
| Break Features into Stories + Acceptance Criteria | **Yes — Agent 2.** |

## Negative-scenario handling (guardrails)

Agent 1 is guarded against two bad-input cases before any model call is spent
(`check_input_guardrails` in `app/agent/epic.py`, also described in that
agent's system prompt as a second line of defence):

| Scenario | What happens |
|---|---|
| **Invalid / empty input** — blank, whitespace, or gibberish like `asdfghjk` / `%%%` | Submission is halted, the UI shows an amber warning, no backend processing runs. |
| **Sensitive data** — text matching a credit-card, SSN/national-ID, or API-key/token shape | Epic conversion is paused, the UI shows a red security notice, and a **masked** alert is logged server-side (the matched value is never logged). |

The Streamlit UI has a **"Try a scenario"** panel with one-click buttons for
both happy-path examples and each negative case, so the behaviour is easy to
demo. Scenario definitions live in `app/agent/scenarios.py`.

## How to run it

### 1. Setup (once)
```powershell
git clone https://github.com/saranya-selvaraj/po_backlog_agent.git
cd po_backlog_agent
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a `.env` file (not committed) with your Groq key:
```
GROQ_API_KEY=your_key_here
```

### 2. Build the knowledge base index (once, or after editing docs in app/docs/)
```powershell
python app/rag/ingest.py
```

### 3. Run the UI
```powershell
streamlit run app/ui/streamlit_app.py
```
Paste an initiative into the text box and click Generate. The "Write result
to mock backlog store" checkbox writes in-process (see app/api/store.py) -
no separate server needed.

### Optional: offline RAGAS eval (app/evals/offline_eval.py)
Not installed by `requirements.txt` and not needed to run the app - only
for scoring the RAG pipeline against the hand-built test set. `ragas`
needs an `openai` version that conflicts with the app's pinned one, so
install in this exact order (a single combined `pip install` of both
files will fail to resolve):
```powershell
pip install -r requirements.txt
pip install ragas==0.4.3 langchain-openai==1.6.3
pip install --no-deps openai==3.3.1
```
Then run with `python -m app.evals.offline_eval`.

### Optional: the mock backlog API as a standalone service
`app/api/main.py` is a thin FastAPI wrapper around the same in-process
store, kept for manual/Swagger-style testing. It has its own separate
in-memory state (not shared with the Streamlit app), so it's useful for
poking at the API shape directly, not for verifying a UI write-back.
```powershell
uvicorn app.api.main:app --reload
```
Swagger UI: http://localhost:8000/docs

### Running individual pieces directly (for testing/debugging)
Any module that imports across `app/` subfolders must be run with `-m` from the project root, e.g.:
```powershell
python -m app.llm.client
python -m app.agent.epic
python -m app.agent.features
python -m app.agent.stories
python -m app.agent.pipeline
```

## Tech stack

| Component | Choice |
|---|---|
| LLM | Groq API (llama-3.3-70b-versatile) |
| Embeddings | Local sentence-transformers (all-MiniLM-L6-v2) |
| Vector store | Chroma (local, file-backed) |
| Mock backlog API | FastAPI |
| UI | Streamlit |

Full requirements and design rationale: see `po_backlog_agent_PRD.md`.
