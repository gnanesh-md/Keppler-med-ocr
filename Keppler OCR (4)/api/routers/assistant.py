import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from core.rate_limit import limiter
from core.schemas import ChatRequest, ChatResponse, IngestTextRequest, IngestVaultDocRequest
from core.security import get_current_user, CurrentUser
from database.db_utils import get_chat_history, get_document_full, log_audit_event, save_chat_message
from modules.rag_engine import ingest_document, query as rag_query, stream_query

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])

DEFAULT_SESSION = "default"
CHAT_APP_TYPE = "LightRAG"  # kept as-is (not "RAG"/"Qdrant") so existing chat_history rows stay in one thread


@router.post("/ingest/text")
async def ingest_text(payload: IngestTextRequest, current_user: CurrentUser = Depends(get_current_user)):
    if not payload.documents:
        raise HTTPException(status_code=400, detail="No documents provided.")
    total_chunks = 0
    for i, text in enumerate(payload.documents):
        doc_id = abs(hash(f"{current_user.user_id}:{text[:100]}")) % 1_000_000_000
        total_chunks += ingest_document(
            current_user.user_id, doc_id, f"Pasted Text {i + 1}", "manual", [("Text", text)]
        )
    return {"message": f"Ingested {len(payload.documents)} document(s) ({total_chunks} chunks) into the knowledge base."}


@router.post("/ingest/vault")
async def ingest_vault_docs(payload: IngestVaultDocRequest, current_user: CurrentUser = Depends(get_current_user)):
    """Load previously-OCR'd vault documents straight into the RAG index, without re-upload —
    mirrors the Document Vault's 'Load into RAG' action. Ingests at page granularity when the
    stored metadata has it (OCR's "pages" / the summarizer's "page_texts"), so citations can
    point at a specific page instead of just the whole document."""
    ingested = 0
    for doc_id in payload.doc_ids:
        doc = get_document_full(doc_id, current_user.user_id)
        if not doc:
            continue

        metadata = doc.get("metadata") or {}
        if metadata.get("pages"):
            page_chunks = [(p["label"], p["text"]) for p in metadata["pages"]]
        elif metadata.get("page_texts"):
            page_chunks = [(f"Page {k}", v) for k, v in metadata["page_texts"].items()]
        else:
            page_chunks = [("Document", doc["markdown"])]

        ingest_document(current_user.user_id, doc_id, doc["filename"], doc["doc_category"], page_chunks)
        ingested += 1

    if ingested == 0:
        raise HTTPException(status_code=404, detail="None of the requested documents were found.")
    return {"message": f"Loaded {ingested} vault document(s) into the knowledge base."}


@router.get("/history")
async def history(session_id: str = DEFAULT_SESSION, current_user: CurrentUser = Depends(get_current_user)):
    return get_chat_history(current_user.user_id, CHAT_APP_TYPE, session_id)


@router.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat(request: Request, payload: ChatRequest, current_user: CurrentUser = Depends(get_current_user)):
    save_chat_message(current_user.user_id, CHAT_APP_TYPE, payload.session_id, "user", payload.message)
    try:
        result = await rag_query(current_user.user_id, payload.message, payload.target_language)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error querying knowledge base: {e}")

    save_chat_message(current_user.user_id, CHAT_APP_TYPE, payload.session_id, "assistant", result["answer"])
    log_audit_event(current_user.user_id, "assistant.chat", "session", payload.session_id,
                     detail={"citations": len(result["citations"])})
    return ChatResponse(content=result["answer"], citations=result["citations"])


@router.post("/chat/stream")
@limiter.limit("30/minute")
async def chat_stream(request: Request, payload: ChatRequest, current_user: CurrentUser = Depends(get_current_user)):
    """Server-Sent Events: one `data:` line per event — {"type":"citations",...}
    once, then {"type":"token","text":...} per generated token, then
    {"type":"done"}. EventSource doesn't support POST+auth headers, so the
    frontend consumes this via fetch + ReadableStream (see lib/api.ts)."""
    save_chat_message(current_user.user_id, CHAT_APP_TYPE, payload.session_id, "user", payload.message)
    log_audit_event(current_user.user_id, "assistant.chat_stream", "session", payload.session_id)

    async def event_generator():
        full_answer = ""
        try:
            async for event in stream_query(current_user.user_id, payload.message, payload.target_language):
                if event["type"] == "token":
                    full_answer += event["text"]
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        if full_answer:
            save_chat_message(current_user.user_id, CHAT_APP_TYPE, payload.session_id, "assistant", full_answer)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
