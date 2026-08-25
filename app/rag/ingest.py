"""Ingest the mock knowledge base into a local Chroma collection (PRD §8, §9).

Reads every .md file in app/docs/, splits each into ~200-word chunks,
embeds the chunks locally with sentence-transformers (all-MiniLM-L6-v2,
no API key / no external calls), and stores them in a Chroma collection
persisted to ./chroma_db at the project root.

Run standalone to (re)build the index:
    python -m app.rag.ingest
"""

from __future__ import annotations

import re
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Paths / config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = PROJECT_ROOT / "app" / "docs"
CHROMA_DIR = PROJECT_ROOT / "chroma_db"

COLLECTION_NAME = "po_backlog_kb"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
CHUNK_SIZE_WORDS = 200


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
# Matches a markdown heading line, tolerant of a stray leading "#" and/or
# escaped "\#" that some of the seed docs carry on every line (e.g. a line
# that reads "# \## 3. Ultra-Processing Transparency Policy"). Requires at
# least one real "#" and some non-hash text after it, so a bare "#"
# separator line does not count as a heading.
_HEADING_RE = re.compile(r"^[#\\\s]*#[#\\\s]*(\S.*)$")


def _split_into_sections(text: str) -> list[str]:
    """Split markdown text on heading lines, so each heading's body stays
    with that heading rather than bleeding into neighboring sections.
    Falls back to the whole text as one "section" if no headings match.
    """
    sections: list[list[str]] = []
    current: list[str] = []

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        match = _HEADING_RE.match(line)
        if match:
            if current:
                sections.append(current)
            current = [match.group(1).strip()]
        else:
            current.append(line)

    if current:
        sections.append(current)

    if not sections:
        return [text.strip()] if text.strip() else []

    return [" ".join(section) for section in sections]


def _merge_short_chunks(chunks: list[str], chunk_size: int, min_words: int = 15) -> list[str]:
    """Fold a run of very short chunks (e.g. a doc title immediately
    followed by a bare heading, both split from their real body by a
    malformed source line) forward into whatever comes next, so a heading
    never ends up detached from its own body. Keeps absorbing chunks
    while the accumulated text is still under min_words, not just one hop
    forward, so a short heading isn't satisfied by merging with another
    short heading and left still separated from its body.
    """
    merged: list[str] = []
    i = 0
    while i < len(chunks):
        current = chunks[i]
        j = i + 1
        while len(current.split()) < min_words and j < len(chunks):
            combined_words = len(current.split()) + len(chunks[j].split())
            if combined_words > chunk_size:
                break
            current = f"{current} {chunks[j]}"
            j += 1
        merged.append(current)
        i = j
    return merged


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE_WORDS) -> list[str]:
    """Split text into chunks of up to ~chunk_size words, first breaking on
    markdown heading boundaries (so unrelated sections never get merged
    into one chunk), word-splitting any section longer than chunk_size,
    and re-folding stray short heading-only fragments into their body.
    """
    chunks: list[str] = []

    for section in _split_into_sections(text):
        words = section.split()
        if len(words) <= chunk_size:
            chunks.append(section)
        else:
            for i in range(0, len(words), chunk_size):
                chunks.append(" ".join(words[i : i + chunk_size]))

    return _merge_short_chunks(chunks, chunk_size)


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------
def load_documents() -> list[tuple[str, str]]:
    """Return [(filename, full_text), ...] for every .md file in app/docs/."""
    if not DOCS_DIR.is_dir():
        raise FileNotFoundError(f"Docs directory not found: {DOCS_DIR}")

    md_files = sorted(DOCS_DIR.glob("*.md"))
    if not md_files:
        raise FileNotFoundError(f"No .md files found in {DOCS_DIR}")

    return [(path.name, path.read_text(encoding="utf-8")) for path in md_files]


def build_index() -> int:
    """Chunk + embed all docs and (re)write the Chroma collection.

    Returns the number of chunks indexed.
    """
    documents = load_documents()

    ids: list[str] = []
    texts: list[str] = []
    metadatas: list[dict] = []

    for filename, text in documents:
        doc_chunks = chunk_text(text)
        for i, chunk in enumerate(doc_chunks):
            ids.append(f"{filename}::chunk_{i}")
            texts.append(chunk)
            metadatas.append({"source": filename, "chunk_index": i})

    print(f"Loaded {len(documents)} document(s) -> {len(texts)} chunk(s).")

    print(f"Embedding with '{EMBEDDING_MODEL_NAME}' (local, no API)...")
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    embeddings = model.encode(texts, show_progress_bar=False).tolist()

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # Drop any existing collection so re-running ingest doesn't duplicate
    # or leave stale chunks behind.
    try:
        client.delete_collection(name=COLLECTION_NAME)
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    collection.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)

    print(f"Indexed {len(texts)} chunk(s) into Chroma collection '{COLLECTION_NAME}' at {CHROMA_DIR}")
    return len(texts)


if __name__ == "__main__":
    build_index()
