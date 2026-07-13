"""
Production RAG — Phase 4. Replaces modules/rag_chatbot.py's per-call LightRAG
instantiation (a fresh on-disk knowledge graph rebuilt from scratch on every
insert/query, no citations, embeddings routed at a model that was never
actually served — see Phase 1 exploration notes) with a persistent Qdrant
collection, real BGE-M3 embeddings and BGE-Reranker-v2-m3 reranking (both via
core/model_router.py), and grounded answers with citations back to the
source document/page.

Design:
  - One Qdrant collection (settings.QDRANT_COLLECTION), 1024-dim (BGE-M3),
    cosine distance. Every point is tagged with user_id so a query only ever
    searches that user's own ingested documents (multi-tenant isolation).
  - Ingestion chunks at the PAGE level (the natural unit the OCR/summarizer
    pipelines already produce — see api/routers/assistant.py), further
    splitting any oversized page on paragraph boundaries.
  - Point IDs are deterministic (hash of doc_id/page/chunk-index) so
    re-ingesting the same document overwrites its old chunks instead of
    duplicating them.
  - Retrieval: embed the question, vector-search top_k candidates, rerank
    down to rerank_top_n with BGE-Reranker, build a numbered context block
    per source, ask the chat model to answer *only* from that context. Every
    source actually placed in the context is returned as a citation — not
    just the ones the model happened to reference — so "grounded" is a
    guarantee about what was available, not a hope about what the model
    chose to cite.
"""
import hashlib
import logging
from typing import List, Optional, TypedDict

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from core.config import settings
from core.model_router import Role, embed_texts, get_client_for_role, model_name_for_role, rerank

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024  # BGE-M3 dense vector size
MAX_CHUNK_CHARS = 2000  # oversized pages get split further, on paragraph boundaries


class Citation(TypedDict):
    doc_id: int
    filename: str
    page_label: str
    snippet: str


_client: Optional[QdrantClient] = None


def get_qdrant_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=settings.QDRANT_URL)
    return _client


def ensure_collection():
    client = get_qdrant_client()
    if not client.collection_exists(settings.QDRANT_COLLECTION):
        client.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config=qmodels.VectorParams(size=EMBEDDING_DIM, distance=qmodels.Distance.COSINE),
        )
        client.create_payload_index(
            settings.QDRANT_COLLECTION, field_name="user_id", field_schema=qmodels.PayloadSchemaType.INTEGER
        )
        client.create_payload_index(
            settings.QDRANT_COLLECTION, field_name="doc_id", field_schema=qmodels.PayloadSchemaType.INTEGER
        )
        logger.info(f"Created Qdrant collection {settings.QDRANT_COLLECTION}")


def _split_chunk(text: str) -> List[str]:
    """Splits an oversized page on paragraph boundaries, keeping each piece
    under MAX_CHUNK_CHARS. Pages under the limit pass through unchanged."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    parts, current = [], ""
    for para in text.split("\n\n"):
        if len(current) + len(para) + 2 > MAX_CHUNK_CHARS and current:
            parts.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        parts.append(current)
    return parts


def _point_id(doc_id: int, page_label: str, chunk_idx: int) -> str:
    return hashlib.md5(f"{doc_id}:{page_label}:{chunk_idx}".encode()).hexdigest()


def ingest_document(user_id: int, doc_id: int, filename: str, category: str, page_chunks: List[tuple]):
    """page_chunks: list of (page_label, text) — the natural unit the OCR/
    summarizer pipelines already produce. Empty/near-empty pages are skipped."""
    ensure_collection()
    client = get_qdrant_client()

    units = []  # (page_label, chunk_idx, text)
    for page_label, text in page_chunks:
        if not text or len(text.strip()) < 10:
            continue
        for i, sub in enumerate(_split_chunk(text)):
            units.append((page_label, i, sub))

    if not units:
        logger.warning(f"ingest_document: no non-empty chunks for doc {doc_id} ({filename})")
        return 0

    vectors = embed_texts([u[2] for u in units])

    points = [
        qmodels.PointStruct(
            id=_point_id(doc_id, page_label, chunk_idx),
            vector=vector,
            payload={
                "user_id": user_id,
                "doc_id": doc_id,
                "filename": filename,
                "category": category,
                "page_label": page_label,
                "chunk_index": chunk_idx,
                "text": text,
            },
        )
        for (page_label, chunk_idx, text), vector in zip(units, vectors)
    ]
    client.upsert(collection_name=settings.QDRANT_COLLECTION, points=points)
    logger.info(f"Ingested {len(points)} chunks for doc {doc_id} ({filename})")
    return len(points)


async def _retrieve(user_id: int, question: str, top_k: int, rerank_top_n: int):
    """Shared by query() and stream_query(): embed -> vector search (user-
    scoped) -> rerank -> numbered context blocks + matching citations."""
    ensure_collection()
    client = get_qdrant_client()

    query_vector = embed_texts([question])[0]
    hits = client.query_points(
        collection_name=settings.QDRANT_COLLECTION,
        query=query_vector,
        query_filter=qmodels.Filter(
            must=[qmodels.FieldCondition(key="user_id", match=qmodels.MatchValue(value=user_id))]
        ),
        limit=top_k,
    ).points

    if not hits:
        return None, []

    rerank_scores = rerank(question, [h.payload["text"] for h in hits])
    ranked = sorted(zip(hits, rerank_scores), key=lambda pair: pair[1], reverse=True)[:rerank_top_n]

    context_blocks = []
    citations: List[Citation] = []
    for i, (hit, score) in enumerate(ranked, start=1):
        p = hit.payload
        context_blocks.append(f"[{i}] (Source: {p['filename']}, {p['page_label']}):\n{p['text']}")
        citations.append({
            "doc_id": p["doc_id"],
            "filename": p["filename"],
            "page_label": p["page_label"],
            "snippet": p["text"][:200],
        })

    return "\n\n".join(context_blocks), citations


NO_DOCS_MESSAGE = (
    "I don't have any documents loaded to answer from yet — load a document into the "
    "AI Assistant from the Document Vault first."
)


def _build_prompt(context: str, question: str, target_language: str) -> str:
    return (
        f"Context (numbered sources):\n{context}\n\n"
        f"User question: {question}\n\n"
        f"Instructions: Answer using ONLY the information in the numbered sources above. "
        f"Cite sources inline using [N] matching the source numbers. If the answer isn't in the "
        f"provided sources, say so explicitly rather than guessing. Respond in {target_language}."
    )


async def stream_query(user_id: int, question: str, target_language: str = "English",
                        top_k: int = 20, rerank_top_n: int = 5):
    """Async generator: yields {"type": "citations", "citations": [...]} once,
    then {"type": "token", "text": "..."} per generated token, then
    {"type": "done"}. Used by the SSE endpoint (api/routers/assistant.py)."""
    context, citations = await _retrieve(user_id, question, top_k, rerank_top_n)
    yield {"type": "citations", "citations": citations}

    if context is None:
        yield {"type": "token", "text": NO_DOCS_MESSAGE}
        yield {"type": "done"}
        return

    prompt = _build_prompt(context, question, target_language)
    client_llm = get_client_for_role(Role.CHAT)
    stream = await client_llm.chat.completions.create(
        model=model_name_for_role(Role.CHAT),
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=1024,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield {"type": "token", "text": delta}
    yield {"type": "done"}


async def query(user_id: int, question: str, target_language: str = "English",
                 top_k: int = 20, rerank_top_n: int = 5) -> dict:
    """Non-streaming variant. Returns {"answer": str, "citations": List[Citation]}."""
    context, citations = await _retrieve(user_id, question, top_k, rerank_top_n)
    if context is None:
        return {"answer": NO_DOCS_MESSAGE, "citations": []}

    prompt = _build_prompt(context, question, target_language)

    client_llm = get_client_for_role(Role.CHAT)
    resp = await client_llm.chat.completions.create(
        model=model_name_for_role(Role.CHAT),
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=1024,
    )
    answer = resp.choices[0].message.content

    return {"answer": answer, "citations": citations}
