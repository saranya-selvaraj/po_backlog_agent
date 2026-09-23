# Technical Design Document: Automated Claims Ingestion System

System architecture: event-driven microservices & AI cognitive agent.

## 1. User Interface (UI) Representation

The Frontend application (Web/Mobile) provides discrete views based on user persona:

Customer Portal: a minimalistic, wizard-driven form allowing document uploads (drag-and-drop). It features a real-time tracking component that updates dynamically via WebSockets from 'Submitted' to 'Processing' and, if eligible, to 'Approved & Paid' within seconds.

Internal Claims Handler Dashboard: a high-density data grid prioritizing escalated claims (Risk Score >= 40%). It explicitly displays the calculated risk percentage, highlighted fraud flags (e.g., mismatched dates), a side-by-side view of the uploaded documents, and action buttons to override, approve, or reject.

## 2. Backend Component Calls & Integrations

The system relies on an API Gateway routing requests to specialized microservices:

Ingestion API: receives the initial multi-part form data from the UI. It securely stores raw binary files (images/PDFs) into an S3 Object Store and publishes a 'ClaimSubmitted' event to a Kafka Message Broker.

Core Ledger Service: validates that the associated policy number exists, is active, and covers the specific incident type prior to processing.

## 3. AI Cognitive Agent & Tool Calling Mechanism

An Orchestration Agent manages the core intelligence loop using tool-calling paradigms:

Event Listener: the Agent consumes the 'ClaimSubmitted' event from the Kafka queue.

Intent Parsing & Tool Execution: the Agent analyzes the payload and programmatically calls specialized internal APIs acting as its tools: Call Tool 'ExtractDocumentData' invokes an AI-OCR service to parse unstructured receipt text into structured JSON fields; Call Tool 'ExecuteRiskEvaluation' passes the structured data and policy history into the Risk Engine, which evaluates rules and outputs the specific risk percentage.

## 4. Routing Logic & Database (DB) Transactions

The Agent acts as the final traffic controller based on the tool responses, executing conditional database logic:

If Risk Score < 40%: the Agent issues a write command to the relational Core DB (PostgreSQL) via a transactional query updating `claim_status` to 'AUTO_APPROVED'. It executes an API call to the Treasury Service to initialize the payout sequence, and posts a notification payload to the Communication Microservice.

If Risk Score >= 40%: the Agent writes to the Core DB setting `claim_status` to 'PENDING_REVIEW', and populates a separate `risk_metadata` table containing the breakdown of the score flags. It pushes a message to the internal Queue Service, appending the claim ID to the active workspace of the assigned manual claims handler group, prompting a UI refresh on the dashboard.
