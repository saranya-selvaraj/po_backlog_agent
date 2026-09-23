"""Hand-built ground-truth test set for the offline RAGAS eval.

Each case pairs a raw initiative (the pipeline's real input) with the set
of knowledge-base source files it should draw on, and a short reference
summary of the facts a well-grounded Feature decomposition should reflect
(used by context_precision / context_recall, which need a judge target).

Two cases reuse the app's existing food-scoring KB (ultra-processing,
premium subscription); the other two are grounded in the Claims Agent and
Incident-response docs added to app/docs/ for this eval.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agent.epic import EXAMPLE_INITIATIVE

from app.evals.sample_initiatives import (
    CLAIMS_INGESTION_INITIATIVE,
    DOCUMENT_RETRIEVAL_INCIDENT_INITIATIVE,
    PREMIUM_SUBSCRIPTION_INITIATIVE,
)


@dataclass
class EvalCase:
    name: str
    initiative_text: str
    expected_sources: frozenset[str]
    reference: str


EVAL_CASES: list[EvalCase] = [
    EvalCase(
        name="ultra_processing_visibility",
        initiative_text=EXAMPLE_INITIATIVE,
        expected_sources=frozenset(
            {"business_case_example.md", "design_doc_example.md", "process_policy_example.md"}
        ),
        reference=(
            "The platform classifies products into Low, Moderate, or High "
            "ultra-processing tiers by tokenizing ingredient text and "
            "cross-referencing it against a dictionary of industrial "
            "additives (e.g. high-fructose corn syrup, hydrolyzed proteins, "
            "cosmetic texturizers). Classification must use a documented, "
            "consistent methodology from reliable data sources, be "
            "communicated in clear non-technical language, and must not be "
            "presented as a definitive 'good or bad' judgment."
        ),
    ),
    EvalCase(
        name="premium_subscription_checkout",
        initiative_text=PREMIUM_SUBSCRIPTION_INITIATIVE,
        expected_sources=frozenset(
            {"business_case_example.md", "design_doc_example.md", "process_policy_example.md"}
        ),
        reference=(
            "Premium upgrades run through native mobile commerce gateways "
            "(Stripe, Apple, Google Play). Payment confirmation tokens must "
            "undergo immediate asynchronous server-side verification before "
            "premium access is granted, unlocking deep nutrition tracking "
            "and additive-database features. Every successful activation "
            "must post a balanced ledger record within 60 seconds, and any "
            "token with a currency mismatch or invalid signature must be "
            "locked and routed to the High-Priority Billing Recovery Queue "
            "rather than silently approved."
        ),
    ),
    EvalCase(
        name="claims_ingestion_automation",
        initiative_text=CLAIMS_INGESTION_INITIATIVE,
        expected_sources=frozenset(
            {"claims_agent_workflow.md", "claims_agent_system_architecture.md"}
        ),
        reference=(
            "Incoming claims from web, mobile, and broker channels are "
            "passed to a Risk Engine that calculates a 0-100% risk score. "
            "Claims scoring below the 40% threshold are auto-approved, set "
            "claim_status to AUTO_APPROVED, and trigger payout via the "
            "Treasury Service. Claims at or above 40% are set to "
            "PENDING_REVIEW with risk metadata attached and routed to a "
            "Claims Handler's queue for manual review. An AI orchestration "
            "agent drives this via tool calls to ExtractDocumentData (OCR) "
            "and ExecuteRiskEvaluation."
        ),
    ),
    EvalCase(
        name="document_retrieval_resilience",
        initiative_text=DOCUMENT_RETRIEVAL_INCIDENT_INITIATIVE,
        expected_sources=frozenset(
            {"incident_details.md", "incident_proposed_solution.md"}
        ),
        reference=(
            "The NextGen Document Retrieval Service outage (INC-884920-NXG) "
            "was caused by a post-migration failure to reach the relocated "
            "Identity Provider and by database timeouts against the legacy "
            "on-premise database. The long-term fix replaces the "
            "synchronous architecture with JWT caching at the gateway via "
            "Redis, a DynamoDB read-optimized metadata cache, and "
            "edge-cached document delivery via S3 and CloudFront with "
            "automatic failover, targeting sub-400ms latency and under "
            "0.01% error rate."
        ),
    ),
]
