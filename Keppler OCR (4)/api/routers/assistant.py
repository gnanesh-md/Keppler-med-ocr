from fastapi import APIRouter, Depends, HTTPException

from core.schemas import ChatRequest, ChatResponse, IngestTextRequest, IngestVaultDocRequest
from core.security import get_current_user, CurrentUser
from database.db_utils import get_chat_history, get_document_markdown, save_chat_message
from modules.rag_chatbot import _async_insert_text, _async_query_graph

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])

DEFAULT_SESSION = "default"


@router.post("/ingest/text")
async def ingest_text(payload: IngestTextRequest, current_user: CurrentUser = Depends(get_current_user)):
    if not payload.documents:
        raise HTTPException(status_code=400, detail="No documents provided.")
    await _async_insert_text(current_user.user_id, payload.documents)
    return {"message": f"Ingested {len(payload.documents)} document(s) into the knowledge graph."}


@router.post("/ingest/vault")
async def ingest_vault_docs(payload: IngestVaultDocRequest, current_user: CurrentUser = Depends(get_current_user)):
    """Load previously-OCR'd vault documents straight into the RAG graph, without re-upload —
    mirrors the Streamlit Document Vault's 'Load into RAG' action."""
    documents = []
    for doc_id in payload.doc_ids:
        markdown = get_document_markdown(doc_id, current_user.user_id)
        if markdown:
            documents.append(markdown)
    if not documents:
        raise HTTPException(status_code=404, detail="None of the requested documents were found.")
    await _async_insert_text(current_user.user_id, documents)
    return {"message": f"Loaded {len(documents)} vault document(s) into the knowledge graph."}


@router.get("/history")
async def history(session_id: str = DEFAULT_SESSION, current_user: CurrentUser = Depends(get_current_user)):
    return get_chat_history(current_user.user_id, "LightRAG", session_id)


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, current_user: CurrentUser = Depends(get_current_user)):
    save_chat_message(current_user.user_id, "LightRAG", payload.session_id, "user", payload.message)
    try:
        response = await _async_query_graph(
            current_user.user_id, payload.message, payload.target_language, llm_model="openai/qwen2.5-vl-7b"
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error querying knowledge graph: {e}")

    save_chat_message(current_user.user_id, "LightRAG", payload.session_id, "assistant", response)
    return ChatResponse(content=response)
