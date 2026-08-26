# PO Backlog Agent — Technical Product Decisions

## Why RAG, here specifically?
Turning an initiative into Features needs real context: actual company documents, discussions, and policies, not general internet knowledge. RAG keeps the agent grounded in verified, organization-specific sources. That cuts down on hallucination and means every Feature can be traced back to a real document.

## Why a mock API instead of real JIRA?
A real JIRA integration would add cost and complexity that isn't needed just to prove the concept. The mock API mirrors what a real integration would look like: same endpoints, same nested structure. So it's contract-first. Swapping in real JIRA later is a config and auth change, not a rewrite of the agent logic.

## Why local embeddings/Chroma instead of a hosted vector DB?
This is a small POC with a limited, plain-text knowledge base. No PDFs, no OCR, nothing that needs heavy cleanup. Chroma (which is itself a vector database, just a local, embedded one rather than a hosted service) is enough to chunk, embed, and retrieve accurately at this scale. It also avoids adding another external service with its own quota to manage, which is the same thinking behind moving off Gemini, explained below.

## Why Groq instead of the original Gemini plan?
Groq was chosen for fast inference, which matters for a responsive demo, a free tier generous enough to support iterative development, and OpenAI-compatible tool calling, which the agent's function calls depend on. It also sidestepped the quota fragility already run into with Google AI Studio on other projects. That reinforced a broader principle for this project: don't build the core reasoning step on a single fragile external quota.

## What would I change to make this production-ready?
Same baseline architecture, with these additions:

- **Input guardrails:** a clean-up layer to strip malicious content, PII, and prompt injections before user input reaches the agents.
- **RAG at scale:** a stronger embedding model as the knowledge base grows, a reranker, and an LLM-as-judge check on retrieval quality. Move from Chroma to a managed, hosted vector DB such as Pinecone, Weaviate, or pgvector.
- **Evaluation:** a ground-truth dataset per agent, with both offline and online evals, revised over time using real production queries and responses.
- **Output verification:** human and LLM-as-judge review of outputs, with the same clean-up layer applied before anything reaches the user.
- **Human approval gates:** any write-back action, like creating a real backlog item, requires explicit human approval before it executes, not just a review afterward. Same principle as keeping sign-off human in this project's scope.
- **Auth:** a real JIRA/Confluence integration would need OAuth or API-token auth, scoped per-user permissions, and proper secrets management, not a `.env` file.
- **Cost/latency monitoring:** track token spend and p95 latency per agent call, with alerting thresholds. Consider routing simpler steps to a cheaper, faster model and saving the strongest model for steps that genuinely need deep reasoning.
