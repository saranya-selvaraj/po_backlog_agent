"""Retrieval over the local Chroma knowledge base (PRD FR2).

Exposes retrieve(query, k=3) -> top-k chunks with source filename and a
similarity score. No LLM calls here — retrieval only.

Run standalone to sanity-check retrieval against a few sample queries:
    python -m app.rag.retrieve
"""

from __future__ import annotations

from dataclasses import dataclass

import chromadb
from sentence_transformers import SentenceTransformer

from app.rag.ingest import CHROMA_DIR, COLLECTION_NAME, EMBEDDING_MODEL_NAME

# A cosine similarity below this is treated as "not strongly relevant"
# (see FR2 acceptance criteria: don't force a match for unrelated queries).
RELEVANCE_THRESHOLD = 0.3

_model: SentenceTransformer | None = None
_collection = None


@dataclass
class RetrievedChunk:
    text: str
    source: str
    chunk_index: int
    score: float  # cosine similarity, higher = more relevant


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


def _get_collection():
    global _collection
    if _collection is None:
        if not CHROMA_DIR.is_dir():
            raise FileNotFoundError(
                f"Chroma index not found at {CHROMA_DIR}. Run `python -m app.rag.ingest` first."
            )
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = client.get_collection(name=COLLECTION_NAME)
    return _collection


def retrieve(query: str, k: int = 3) -> list[RetrievedChunk]:
    """Return the top-k most relevant chunks for `query`.

    Each result includes the source filename and a cosine-similarity score.
    Results below RELEVANCE_THRESHOLD are dropped, so a query unrelated to
    the knowledge base can legitimately return an empty list rather than
    forcing a match.
    """
    global _collection

    model = _get_model()
    query_embedding = model.encode([query]).tolist()

    try:
        collection = _get_collection()
        results = collection.query(query_embeddings=query_embedding, n_results=k)
    except Exception:
        # The cached collection object goes stale if `ingest.py` rebuilt
        # the index (it deletes + recreates the collection) after this
        # process first fetched it - the old handle no longer points at
        # anything valid. Drop the cache and retry once before giving up.
        _collection = None
        collection = _get_collection()
        results = collection.query(query_embeddings=query_embedding, n_results=k)

    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]  # cosine distance = 1 - cosine similarity

    chunks: list[RetrievedChunk] = []
    for doc, meta, distance in zip(documents, metadatas, distances):
        score = 1 - distance
        if score < RELEVANCE_THRESHOLD:
            continue
        chunks.append(
            RetrievedChunk(
                text=doc,
                source=meta["source"],
                chunk_index=meta["chunk_index"],
                score=round(score, 4),
            )
        )

    return chunks


if __name__ == "__main__":
    import sys

    # Windows consoles often default to cp1252, which can't encode some
    # characters from the source docs (e.g. arrows in ASCII diagrams).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    sample_queries = [
        "What is our rollback plan policy for customer-facing features?",
        "How does the ultra-processing level classification work?",
        "What is the best pizza topping combination?",
    ]

    for q in sample_queries:
        print(f"\nQuery: {q!r}")
        hits = retrieve(q, k=3)
        if not hits:
            print("  No strongly relevant context found.")
            continue
        for hit in hits:
            preview = hit.text[:100].replace("\n", " ")
            print(f"  [{hit.score:.4f}] {hit.source} (chunk {hit.chunk_index}): {preview}...")
