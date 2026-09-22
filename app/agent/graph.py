"""LangGraph wiring for the v2 backlog agent (PRD §6).

Currently:
  START -> Node 0 (safety gate) -[pass]-> Node 1 (EPIC generator) -[ok]-> Node 2 (decomposer) -> END
                                -[reject]-> END (error in state)         -[bad model reply]-> END

Run standalone to try it by hand:
    python -m app.agent.graph --demo
    python -m app.agent.graph "some initiative text"
    python -m app.agent.graph --file path/to/text.txt
"""

from __future__ import annotations

from dataclasses import asdict

from langgraph.graph import END, START, StateGraph

from app.agent.epic_node import epic_generator_node
from app.agent.node2 import decomposer_node
from app.agent.safety_gate import run_safety_gate
from app.agent.state import GraphState


def safety_gate_node(state: GraphState) -> dict:
    """Node 0 wrapper: deterministic gate; on pass, publishes the sanitized text."""
    result = run_safety_gate(state["raw_text"], filename=state.get("filename"))
    update: dict = {"gate": asdict(result)}
    if result.passed:
        update["clean_text"] = result.text
    else:
        update["error"] = {"stage": "safety_gate", "code": result.reason, "message": result.message}
    return update


def route_after_gate(state: GraphState) -> str:
    return "epic_generator" if state["gate"]["passed"] else END


def route_after_epic(state: GraphState) -> str:
    return END if state.get("error") else "decomposer"


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("safety_gate", safety_gate_node)
    graph.add_node("epic_generator", epic_generator_node)
    graph.add_node("decomposer", decomposer_node)
    graph.add_edge(START, "safety_gate")
    graph.add_conditional_edges("safety_gate", route_after_gate, {"epic_generator": "epic_generator", END: END})
    graph.add_conditional_edges("epic_generator", route_after_epic, {"decomposer": "decomposer", END: END})
    graph.add_edge("decomposer", END)
    return graph.compile()


# ---------------------------------------------------------------------------
# Manual testing
# ---------------------------------------------------------------------------
SAMPLE_INITIATIVES = {
    "1. Meeting notes (open question + explicit exclusions)": (
        "Notes from Tuesday's growth sync: our onboarding drop-off is worst on step 3, where new users are "
        "asked to link a grocery loyalty card before they see any value. About 4 in 10 people quit there "
        "according to the funnel dashboard. Proposal: let people skip the loyalty card step and land straight "
        "on the scanner, then prompt them to link a card later, after their third successful scan. We agreed "
        "this is for the mobile app only for now; web onboarding stays as it is. We are not redesigning the "
        "whole onboarding flow and not changing which loyalty programs we support. Still open: whether the "
        "later prompt should be a banner or a modal - design will decide."
    ),
    "2. JIRA-style ticket": (
        "JIRA-2231: Weekly savings digest email. Customers who scan at least 5 products a week should get a "
        "Sunday email summarising how much they could have saved by choosing lower-priced alternatives we "
        "already surface in-app. Marketing wants it live before the January campaign because email is "
        "currently our lowest-cost re-engagement channel. Digest content is limited to price-comparison data "
        "we already have; no personalised nutrition advice and no new data sources. Users must be able to "
        "unsubscribe from the digest without affecting transactional emails. Out of scope: SMS or push "
        "versions of the digest, and any change to how alternatives are ranked."
    ),
    "3. Support ticket with PII (Node 0 redacts, Node 1 sees placeholders)": (
        "Customer name: Dana Whitfield\n"
        "Contact: dana.whitfield@example.com, +44 7700 900123\n\n"
        "Dana keeps writing in because the app shows a product as 'unsafe for nut allergies' but doesn't say "
        "which ingredient triggered the warning, so she can't tell whether it is a real risk or a false alarm. "
        "Three other tickets this month say the same. Ask: whenever an allergy warning is shown, list the "
        "specific ingredient(s) that caused it, on the product page and in the scan result. Only for the "
        "allergens users already selected in their profile. Not asking for new allergen categories or for "
        "changes to how ingredient data is sourced."
    ),
}


def _print_run(label: str, final_state: dict) -> None:
    import json

    print(f"\n=== {label} ===")
    gate = final_state.get("gate", {})
    if gate.get("flags"):
        print(f"gate flags: {gate['flags']}  redactions: {gate.get('redactions')}")
        print(f"text sent to LLM: {final_state.get('clean_text', '')[:220]!r}")
    if final_state.get("error"):
        err = final_state["error"]
        print(f"STOPPED at {err['stage']} ({err['code']}): {err['message']}")
        return

    print(json.dumps(final_state["epic"], indent=2, ensure_ascii=False))
    print(f"\nretrieval_attempts (Feature-level loop) = {final_state.get('retrieval_attempts')}")
    for feature in final_state.get("features", []):
        stories = feature.get("stories", [])
        print(f"\n--- Feature: {feature['title']} ---")
        if feature.get("validation_flags"):
            print(f"  [FEATURE FLAGS] {feature['validation_flags']}")
        print(json.dumps({k: v for k, v in feature.items() if k not in ("stories", "validation_flags")}, indent=2))
        for story in stories:
            print(f"  * {story['story']}")
            if story.get("validation_flags"):
                print(f"    [STORY FLAGS] {story['validation_flags']}")
            for ac in story["acceptance_criteria"]:
                print(f"      - {ac}")


if __name__ == "__main__":
    import argparse
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Run Node 0 -> Node 1 -> Node 2 by hand.")
    parser.add_argument("text", nargs="?", help="raw initiative text")
    parser.add_argument("--file", help="read the initiative from this UTF-8 file")
    parser.add_argument("--demo", action="store_true", help="run the built-in sample initiatives")
    args = parser.parse_args()

    app = build_graph()
    if args.demo or (args.text is None and args.file is None):
        for label, sample in SAMPLE_INITIATIVES.items():
            _print_run(label, app.invoke({"raw_text": sample}))
    else:
        raw = open(args.file, encoding="utf-8").read() if args.file else args.text
        _print_run("input", app.invoke({"raw_text": raw}))
