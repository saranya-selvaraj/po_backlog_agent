"""Raw initiative text for the offline eval's sample EPICs.

Two are reused from app.agent.epic (the app's existing happy-path demo
inputs). The other three are new: one written to exercise the existing
premium-subscription knowledge-base content, and two pulled from real
initiative/incident documents supplied for this eval (Claims Agent,
Incident-driven hardening), lightly trimmed for length.
"""

from __future__ import annotations

# Grounded in business_case_example.md ("Business Case 2: Seamless Premium
# Subscription & Payment Experience"), design_doc_example.md ("2. Automated
# In-App Payment Reconciliation"), and process_policy_example.md sections
# 5-7 (Gateway Token Verification, Billing Security, Exception Isolation).
PREMIUM_SUBSCRIPTION_INITIATIVE = """
Priya (Growth PM): Our free-to-paid conversion is stuck again this quarter.
Support keeps hearing the same thing - people start the upgrade flow, hit
the payment step, and just bounce. We lose a chunk of them right at
checkout on both Stripe and Apple In-App Purchase.

Dev Lead: Part of it is we don't provision anything until the ledger
posting finishes, so there's a visible lag between "payment succeeded" and
"premium features actually unlocked" - users think it failed and back out
or retry, sometimes double-charging themselves.

Priya (Growth PM): Right, so the ask is: make the upgrade feel instant.
The moment the payment gateway confirms the transaction, flip the account
to premium and unlock the deep nutrition tracking and additive database
features immediately - don't make them wait on our backend reconciliation
job. We still need the accounting side done properly in the background,
just not blocking the user.

Dev Lead: We can do that, but we're not skipping verification - any
confirmation token we get back from Stripe or Apple still has to be
checked server-side before we flip anyone to premium, we're just doing it
async instead of making the user sit through it. And if a token comes back
with a currency mismatch or a bad signature, that has to be caught and
routed to review, not silently approved.

Priya (Growth PM): Sure, that's a backend safety net, not something the
user needs to see. Just get the "you're premium now" moment to feel
instant. This is scoped to the upgrade/checkout flow only - we are not
touching pricing, plan tiers, or the refund process in this initiative.
""".strip()

# Trimmed from the supplied "EXECUTIVE INITIATIVE BRIEF" (Project FastTrack).
# Grounded in claims_agent_workflow.md and claims_agent_system_architecture.md.
CLAIMS_INGESTION_INITIATIVE = """
INITIATIVE NAME: Project FastTrack: Automated Claims Ingestion Framework
SPONSOR: VP of Claims Operations & Chief Technology Officer

1. EXECUTIVE SUMMARY
Our current claims processing architecture is facing an unsustainable
operational bottleneck. As customer acquisition has scaled by 40% over the
past two quarters, our manual ingestion infrastructure has failed to keep
pace. This initiative proposes the immediate funding and development of an
Automated Claims Ingestion Framework to transition our operations from
legacy data entry to intelligent, zero-touch automation.

2. PROBLEM STATEMENT & OPERATIONAL OVERHEAD
The core vulnerability lies in our reliance on manual triage. Currently,
incoming claims from web portals, mobile apps, and third-party brokers are
routed into a shared queue where adjusters must manually open, read,
classify, and transcribe data into our core system. This archaic workflow
has resulted in three critical failure points: over 65% of senior claims
adjusters' daily hours are consumed by repetitive data entry rather than
high-value fraud detection, with a 22% turnover rate within the triage
team; the average Time-to-Ingest (TTI) has escalated to a 14-day manual
processing delay, driving net promoter scores down by 18 points; and the
department has relied on offshore vendor bursting, costing an additional
$45,000 per month in variable overhead.

3. STRATEGIC OBJECTIVES & CAPABILITIES
The automated framework must deliver: Intelligent Document Processing
(IDP) - AI-driven OCR to extract structured data from unstructured formats
(PDFs, handwritten receipts, smartphone images) with a 95% confidence
threshold; a Real-Time Validation API to instantly validate policy numbers
and active coverage statuses against the core ledger upon receipt; and an
Automated Triage Engine that routes high-confidence claims straight to
automated approval rails, skipping human intervention entirely for claims
under $1,500.

4. SUCCESS CRITERIA
Success will be measured by reducing the 14-day processing window down to
less than 10 minutes for standard claims, completely eliminating the
$45,000 monthly vendor bursting overhead, and reallocating 50 FTEs back to
core adjudication tasks.
""".strip()

# Trimmed from the supplied incident ticket/call-transcript log (INC-884920-NXG).
# Grounded in incident_details.md and incident_proposed_solution.md.
DOCUMENT_RETRIEVAL_INCIDENT_INITIATIVE = """
INCIDENT TICKETING & TRANSCRIPT LOG
TICKET ID: INC-884920-NXG
SEVERITY: P1 - CRITICAL
SYSTEM: NextGen Document Retrieval Service
AFFECTED CHANNELS: Customer Web Portal, Mobile App v4.2

[INCIDENT LOGGING NOTES - SYSTEM ENGINEER]
Alert triggered at 08:14 AM EST. Spiking 500 Internal Server Error codes
observed on the /documents/fetch endpoint. Legacy database queries are
timing out following the weekend cloud migration to AWS cluster-east. API
breakout identified: the microservice architecture is failing to handle
token exchange with the migrated identity provider under peak load,
completely blocking document retrieval. Live customer escalation initiated
via support desk.

[UNEDITED CALL TRANSCRIPT - CALL ID: TR-9931]
AGENT: Thank you for calling customer support. My name is Mark. How can I
help you today?
CUSTOMER: Yeah, hi Mark, I am in a complete nightmare scenario right now. I
am literally standing at a car dealership trying to finalize a lease, and
your app is completely dead.
AGENT: I am very sorry to hear that. Can you tell me exactly what error
you are seeing on the screen?
CUSTOMER: It just says "Error 500: Internal Server Error" every single
time I try to open my insurance binder. I tried logging into the website
on my phone's browser too, and the exact same thing happens. It just spins
and crashes.
AGENT: I understand your frustration. Let me look up your account details.
Can I have your policy number?
CUSTOMER: It's policy NX-99201-B. Look, you guys need to fix this right
now. The dealer is about to give this car to someone else because I can't
prove my active coverage. I've been trying for forty-five minutes.
AGENT: Thank you. I see the account here. I am attempting to manually pull
the document from my side... Wait, my terminal is also freezing up when
trying to fetch your file. It looks like our entire document retrieval
backend is unresponsive.
CUSTOMER: This is unbelievable! You migrated to this "NextGen" system last
month and it's been nothing but trouble. I am literally blocked at the
dealership counter. Can you just email me the PDF manually?
AGENT: I am unfortunately unable to generate the document link right now
because the API is completely down. I am escalating this call directly to
our engineering tier-3 team as part of an active major incident.
CUSTOMER: Please hurry, this is costing me a vehicle today!
""".strip()
