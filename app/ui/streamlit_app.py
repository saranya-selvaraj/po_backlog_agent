"""Minimal Streamlit UI for the PO Backlog Agent (PRD §10-11).

Paste an initiative, hit Generate, and see the EPIC, the retrieved RAG
context, the Features, and the Stories + Acceptance Criteria for each.
Optionally writes the resulting tree to the mock backlog API (Stage 1).

Run with:
    streamlit run app/ui/streamlit_app.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# `streamlit run app/ui/streamlit_app.py` (the standard invocation) only
# adds this file's own directory (app/ui) to sys.path, not the project
# root - so the `app.*` imports below would fail unless invoked as
# `python -m streamlit run ...` from the project root. Make the project
# root importable regardless of how/from-where this script is launched.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from app.agent.epic import EXAMPLE_INITIATIVE, EpicDraftError
from app.agent.features import RETRIEVAL_K, FeatureDraftError
from app.agent.pipeline import BACKLOG_API_BASE_URL, WriteBackError, run_pipeline
from app.agent.stories import StoryDraftError
from app.rag.ingest import CHROMA_DIR, build_index
from app.rag.retrieve import retrieve

# On by default, so local dev behaves exactly as before with zero setup.
# Set ENABLE_WRITEBACK=false as an environment variable on a hosted
# deploy (e.g. Streamlit Community Cloud, where the mock FastAPI backend
# is never running) to hide the checkbox there and skip write-back
# entirely, so the app is usable end-to-end without FastAPI.
WRITEBACK_ENABLED = os.environ.get("ENABLE_WRITEBACK", "true").lower() == "true"


@st.cache_resource(show_spinner="Building knowledge-base index (first run only)...")
def _ensure_index_built() -> None:
    """Build the Chroma index if it isn't there yet.

    chroma_db/ is gitignored (not committed) and, on top of that, hosted
    platforms like Streamlit Community Cloud reset local disk on every
    restart/redeploy - so the index needs to be (re)built at startup
    rather than assumed to exist. st.cache_resource makes this run once
    per live app instance rather than on every script rerun.
    """
    if not CHROMA_DIR.is_dir():
        build_index()


_ensure_index_built()

st.set_page_config(page_title="PO Backlog Agent", layout="wide")

st.title("PO Backlog Agent")
st.caption(
    "Paste a raw initiative (meeting notes, a ticket, a business-case excerpt) "
    "and generate a structured EPIC → Features → Stories backlog tree."
)

initiative_text = st.text_area(
    "Initiative",
    value=st.session_state.get("initiative_text", EXAMPLE_INITIATIVE),
    height=200,
    placeholder="Paste your raw initiative text here (100-500 words)...",
)

if WRITEBACK_ENABLED:
    write_back = st.checkbox(
        "Write result to mock backlog API",
        value=False,
        help=f"POSTs the epic/features/stories to {BACKLOG_API_BASE_URL}. "
        "Requires `uvicorn app.api.main:app --reload` running separately.",
    )
else:
    write_back = False

generate_clicked = st.button("Generate", type="primary")

if generate_clicked:
    if not initiative_text.strip():
        st.warning("Paste an initiative first.")
    else:
        st.session_state["initiative_text"] = initiative_text
        try:
            with st.spinner("Drafting EPIC → Features → Stories (this can take ~15-30s)..."):
                result = run_pipeline(initiative_text, write_back=write_back)

            # Re-fetch the same retrieved context draft_features used
            # internally, purely so it can be displayed - this makes the
            # grounding inspectable (PRD FR2 / §11), not a second draft.
            epic = result["epic"]
            query = f"{epic.get('title', '')}. {epic.get('problem_statement', '')}".strip()
            context_chunks = retrieve(query, k=RETRIEVAL_K)

            st.session_state["result"] = result
            st.session_state["context_chunks"] = context_chunks
            st.session_state["write_back_done"] = write_back

        except (EpicDraftError, FeatureDraftError, StoryDraftError) as e:
            st.error(f"The model's output didn't validate, so nothing was generated:\n\n{e}")
        except WriteBackError as e:
            st.error(f"Generated the backlog tree, but writing it to the mock API failed:\n\n{e}")

result = st.session_state.get("result")

if result:
    epic = result["epic"]
    features = result["features"]

    st.header("EPIC")
    if "id" in epic:
        st.caption(f"id: {epic['id']}")
    st.subheader(epic["title"])
    st.markdown(f"**Problem statement:** {epic['problem_statement']}")
    st.markdown(f"**Business value:** {epic['business_value']}")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**In scope**")
        for item in epic["in_scope"]:
            st.markdown(f"- {item}")
    with col2:
        st.markdown("**Out of scope**")
        for item in epic["out_of_scope"]:
            st.markdown(f"- {item}")

    st.header("Retrieved context")
    st.caption("Knowledge-base chunks retrieved for this EPIC and passed to the Features step.")
    context_chunks = st.session_state.get("context_chunks", [])
    if not context_chunks:
        st.info("No strongly relevant context found in the knowledge base.")
    else:
        for chunk in context_chunks:
            with st.expander(f"{chunk.source} (score {chunk.score:.4f})"):
                st.write(chunk.text)

    st.header(f"Features ({len(features)})")
    for feature in features:
        with st.expander(feature["title"], expanded=False):
            if "id" in feature:
                st.caption(f"id: {feature['id']}")
            st.markdown(feature["description"])
            if feature.get("tech_notes"):
                st.markdown(f"**Tech notes:** {feature['tech_notes']}")

            st.markdown("**Stories**")
            for story in feature["stories"]:
                st.markdown(f"- {story['story']}")
                for ac in story["acceptance_criteria"]:
                    st.markdown(f"  - ✓ {ac}")

    if st.session_state.get("write_back_done"):
        epic_id = epic.get("id")
        st.success(
            f"Written to the mock backlog API. Verify with "
            f"`GET {BACKLOG_API_BASE_URL}/epics/{epic_id}`."
        )
