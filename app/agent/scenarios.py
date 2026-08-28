"""Demo scenarios for the Streamlit UI.

Each entry is a one-click example: the UI drops `input` into the initiative
box and runs the pipeline, so a reviewer can see both the happy path and
the guardrail behaviour from handling_negative_cases_scenarios.txt without
typing anything.
"""

from __future__ import annotations

from app.agent.epic import EXAMPLE_INITIATIVE, EXAMPLE_INITIATIVE_SCORE_EXPLAINER

# --- Negative-scenario inputs -------------------------------------------------

_EMPTY_INPUT = "   \n   "

_GIBBERISH_INPUT = "asdfghjk asdfghjk %%%%% ;;;;; qwertyuiop %%%"

# Contains a card-number shape, an SSN shape, and an API-key shape so the
# sensitive-data guardrail fires. All values are fake / non-functional
# placeholders (deliberately not real provider key formats).
_SENSITIVE_DATA_INPUT = """From the payments sync-up: support agents need a
faster way to pull up a customer's order when they call in. Right now they
ask the customer to read out their full card number over the phone, e.g.
4532 0151 1283 0366, plus SSN 123-45-6789, and someone even pasted an
internal credential (api_key=FAKE-demo-not-a-real-key-000000) into the
shared ticket. We want agents to look up orders by the last 4 digits only,
never the full number.
""".strip()


SCENARIOS = [
    {
        "key": "happy_ultra",
        "kind": "happy",
        "label": "Happy path - ultra-processing visibility",
        "description": (
            "Well-formed meeting transcript. Runs the full pipeline and "
            "produces an EPIC -> Features -> Stories tree."
        ),
        "input": EXAMPLE_INITIATIVE,
    },
    {
        "key": "happy_score",
        "kind": "happy",
        "label": "Happy path - explain the health score",
        "description": (
            "A second valid initiative (score transparency). Also produces "
            "a full backlog tree."
        ),
        "input": EXAMPLE_INITIATIVE_SCORE_EXPLAINER,
    },
    {
        "key": "neg_empty",
        "kind": "negative",
        "label": "Negative - empty / blank input",
        "description": (
            "Scenario 1: blank or whitespace-only input is rejected before "
            "any model call."
        ),
        "input": _EMPTY_INPUT,
    },
    {
        "key": "neg_gibberish",
        "kind": "negative",
        "label": "Negative - nonsensical text",
        "description": (
            "Scenario 1: key-mash / punctuation noise (\"asdfghjk\", \"%%%\") "
            "is rejected before any model call."
        ),
        "input": _GIBBERISH_INPUT,
    },
    {
        "key": "neg_sensitive",
        "kind": "negative",
        "label": "Negative - sensitive data (card / SSN / API key)",
        "description": (
            "Scenario 2: input containing a credit-card number, SSN or API "
            "key is blocked for security compliance, with a masked alert "
            "logged server-side."
        ),
        "input": _SENSITIVE_DATA_INPUT,
    },
]
