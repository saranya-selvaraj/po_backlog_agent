"""Node 2, part 3 - the deterministic quality-validator pass (PRD §8 step 7).

Runs after Feature/Story generation, not another LLM call. Checks the
guardrail checklist from docs/system_prompts.md plus two PM-added checks
(useful_documents must be real, epic_alignment must trace to scope).

PM decision (Stage 3, point 3b): FLAG ONLY. A failed check never blocks or
drops output - it is attached as a `validation_flags` entry on the Feature or
Story it applies to, and the human reviewer at Node 3 decides what to do with
it. Several checks are heuristic proxies for a judgment call code cannot make
exactly (see each check's docstring) and can produce false flags - that is
why they flag rather than block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "of", "in", "on", "for", "to", "with", "is", "are",
    "be", "this", "that", "it", "as", "by", "from", "at", "so", "so that", "i", "want", "need",
    "will", "can", "their", "they", "them", "user", "users", "customer", "customers", "feature",
    "epic", "story", "stories", "system", "app", "platform",
}

_TECH_TERMS = [
    "postgres", "postgresql", "mysql", "sqlite", "mongodb", "dynamodb", "redis", "kafka",
    "rabbitmq", "graphql", "grpc", "react", "angular", "vue", "django", "flask", "fastapi",
    "spring boot", "node.js", "nodejs", "docker", "kubernetes", "aws", "s3 bucket", "lambda",
    "microservice", "endpoint", "api call", "rest api", "sql query", "database table",
    "class ", "function ", "json schema", "cron job", "webhook handler",
]

_SO_THAT_STOCK_PHRASES = [
    "use the app", "use the system", "use the platform", "get it done", "so that i can use it",
    "achieve the goal", "so i can use the app", "improve the experience",
]


@dataclass
class ValidationFlag:
    check: str
    message: str

    def to_dict(self) -> dict:
        return {"check": self.check, "message": self.message}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z']+", text.lower()) if len(w) > 2 and w not in _STOPWORDS}


# ---------------------------------------------------------------------------
# Feature checks
# ---------------------------------------------------------------------------
def check_shippable_value(feature: dict) -> ValidationFlag | None:
    """Proxy for 'can this ship on its own': a substantive value statement plus
    at least one stated requirement. Cannot verify true deployability."""
    value = (feature.get("value_statement") or "").strip()
    reqs = feature.get("high_level_requirements") or []
    if len(value.split()) < 8 or not reqs:
        return ValidationFlag(
            "shippable_value",
            "Value statement is too short or no high-level requirements are listed; "
            "can't tell if this Feature is independently shippable.",
        )
    return None


def check_no_technical_prescriptions(feature: dict) -> ValidationFlag | None:
    """Heuristic keyword scan for implementation detail (tool/framework names,
    'endpoint', 'schema', etc). Can false-flag when the source KB docs are
    themselves technical and that detail is a real constraint, not a prescription."""
    text = " ".join(
        [feature.get("title", ""), feature.get("value_statement", "")]
        + (feature.get("high_level_requirements") or [])
    ).lower()
    hits = [t.strip() for t in _TECH_TERMS if t in text]
    if hits:
        return ValidationFlag(
            "no_technical_prescriptions",
            f"Feature text mentions implementation-level terms ({', '.join(sorted(set(hits)))}); "
            "should describe what the system does, not how it's built.",
        )
    return None


def check_useful_documents_real(feature: dict, retrieved_sources: set[str]) -> ValidationFlag | None:
    """PM-added check: every filename under useful_documents must be one the
    retrieval loop actually returned for this Feature - catches invented names."""
    claimed = feature.get("useful_documents") or []
    invented = [d for d in claimed if d not in retrieved_sources]
    if invented:
        return ValidationFlag(
            "useful_documents_real",
            f"Listed document(s) not among the retrieved sources: {', '.join(invented)}.",
        )
    return None


def check_epic_alignment_traces(feature: dict, epic: dict) -> ValidationFlag | None:
    """PM-added check: epic_alignment must share at least one significant word
    with some in_scope item - a proxy for 'traces back to an In-Scope boundary'."""
    alignment = (feature.get("epic_alignment") or "").strip()
    if not alignment:
        return ValidationFlag("epic_alignment_traces_to_scope", "epic_alignment is empty.")
    alignment_words = _words(alignment)
    scope_words: set[str] = set()
    for item in epic.get("in_scope") or []:
        scope_words |= _words(item)
    if not (alignment_words & scope_words):
        return ValidationFlag(
            "epic_alignment_traces_to_scope",
            "epic_alignment doesn't share any keywords with the Epic's In-Scope items.",
        )
    return None


def validate_feature(feature: dict, epic: dict, retrieved_sources: set[str]) -> list[dict]:
    checks = (
        check_shippable_value(feature),
        check_no_technical_prescriptions(feature),
        check_useful_documents_real(feature, retrieved_sources),
        check_epic_alignment_traces(feature, epic),
    )
    return [c.to_dict() for c in checks if c]


# ---------------------------------------------------------------------------
# Story checks
# ---------------------------------------------------------------------------
_STORY_RE = re.compile(
    r"as\s+an?\s+(?P<role>.+?),\s*i\s+want\s+(?:to\s+)?(?P<action>.+?),\s*so\s+that\s+(?P<benefit>.+)",
    re.I | re.S,
)
_GWT_RE = re.compile(r"given\s+(?P<given>.+?),\s*when\s+(?P<when>.+?),\s*then\s+(?P<then>.+)", re.I | re.S)


def check_invest_fields(story: dict) -> ValidationFlag | None:
    """Structural: the story matches the As a/I want/so that template with all
    three parts non-empty, and has at least one acceptance criterion listed."""
    match = _STORY_RE.search((story.get("story") or "").strip())
    if not match or not all(match.group(g).strip() for g in ("role", "action", "benefit")):
        return ValidationFlag(
            "invest_fields_present",
            "Story doesn't match 'As a [role], I want [action], so that [benefit]' with all parts filled in.",
        )
    if not story.get("acceptance_criteria"):
        return ValidationFlag("invest_fields_present", "Story has no acceptance criteria.")
    return None


def check_min_acceptance_criteria(story: dict) -> ValidationFlag | None:
    ac = story.get("acceptance_criteria") or []
    if len(ac) < 2:
        return ValidationFlag(
            "min_acceptance_criteria", f"Only {len(ac)} acceptance criterion/criteria; expected at least 2."
        )
    return None


def check_bdd_completeness(story: dict) -> ValidationFlag | None:
    """Each AC must be Given -> When -> Then, in that order, each part non-empty."""
    bad = []
    for i, ac in enumerate(story.get("acceptance_criteria") or [], 1):
        match = _GWT_RE.search(ac.strip())
        if not match or not all(match.group(g).strip() for g in ("given", "when", "then")):
            bad.append(i)
    if bad:
        return ValidationFlag(
            "bdd_completeness", f"Acceptance criterion/criteria not in complete Given/When/Then form: #{bad}."
        )
    return None


def check_so_that_nontrivial(story: dict) -> ValidationFlag | None:
    """Non-trivial 'so that': at least 5 words, not a stock phrase, and not just
    a reworded copy of the 'I want' clause."""
    match = _STORY_RE.search((story.get("story") or "").strip())
    if not match:
        return None  # already covered by check_invest_fields
    benefit = match.group("benefit").strip().rstrip(".")
    action = match.group("action").strip()
    lower = benefit.lower()
    if len(benefit.split()) < 5:
        return ValidationFlag("so_that_nontrivial", f"'so that' clause is too short: {benefit!r}")
    if any(p in lower for p in _SO_THAT_STOCK_PHRASES):
        return ValidationFlag("so_that_nontrivial", f"'so that' clause is a stock/fluff phrase: {benefit!r}")
    benefit_words, action_words = _words(benefit), _words(action)
    if benefit_words and benefit_words <= action_words:
        return ValidationFlag(
            "so_that_nontrivial", f"'so that' clause just restates the 'I want' action: {benefit!r}"
        )
    return None


def check_sprint_sizing_proxy(story: dict) -> ValidationFlag | None:
    """Proxy for the 1-3 day INVEST sizing rule, which code can't verify directly:
    flags a story with more than 3 AC, or an 'I want' clause that bundles several
    actions with 'and'."""
    ac = story.get("acceptance_criteria") or []
    match = _STORY_RE.search((story.get("story") or "").strip())
    action = match.group("action") if match else ""
    if len(ac) > 3:
        return ValidationFlag("sprint_sizing_proxy", f"{len(ac)} acceptance criteria; may be too large for 1-3 days.")
    if re.search(r"\band\b", action, re.I):
        return ValidationFlag(
            "sprint_sizing_proxy", f"'I want' clause bundles multiple actions with 'and': {action!r}"
        )
    return None


def validate_story(story: dict) -> list[dict]:
    checks = (
        check_invest_fields(story),
        check_min_acceptance_criteria(story),
        check_bdd_completeness(story),
        check_so_that_nontrivial(story),
        check_sprint_sizing_proxy(story),
    )
    return [c.to_dict() for c in checks if c]


# ---------------------------------------------------------------------------
# Top-level pass
# ---------------------------------------------------------------------------
def validate_decomposition(
    epic: dict,
    features_with_stories: list[dict],
    retrieved_sources_by_feature: list[set[str]],
) -> list[dict]:
    """Attaches `validation_flags` to every Feature and Story (never removes or
    blocks anything). `features_with_stories[i]`'s `useful_documents` is checked
    against `retrieved_sources_by_feature[i]` - the Feature-phase retrieval
    sources the model actually saw when it wrote that field (the same set for
    every Feature in one EPIC, since they're all generated from one Feature-phase
    retrieval), not that Feature's own Story-phase retrieval.

    Returns a new list; input dicts are not mutated.
    """
    result = []
    for feature, sources in zip(features_with_stories, retrieved_sources_by_feature):
        stories = feature.get("stories", [])
        validated_stories = [{**s, "validation_flags": validate_story(s)} for s in stories]
        result.append(
            {
                **feature,
                "stories": validated_stories,
                "validation_flags": validate_feature(feature, epic, sources),
            }
        )
    return result
