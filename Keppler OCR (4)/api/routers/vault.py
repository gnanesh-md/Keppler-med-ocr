from fastapi import APIRouter, Depends, HTTPException

from core.schemas import VaultDocDetail, VaultDocSummary
from core.security import get_current_user, CurrentUser
from database.db_utils import get_document_markdown, get_user_vault

router = APIRouter(prefix="/api/v1/vault", tags=["vault"])


@router.get("", response_model=list[VaultDocSummary])
async def list_vault(current_user: CurrentUser = Depends(get_current_user)):
    rows = get_user_vault(current_user.user_id)
    return [
        VaultDocSummary(
            id=row[0],
            filename=row[1],
            doc_category=row[2],
            confidence_score=row[3],
            extraction_date=str(row[4]) if row[4] else None,
        )
        for row in rows
    ]


@router.get("/{doc_id}", response_model=VaultDocDetail)
async def get_vault_doc(doc_id: int, current_user: CurrentUser = Depends(get_current_user)):
    markdown = get_document_markdown(doc_id, current_user.user_id)
    if markdown is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return VaultDocDetail(id=doc_id, markdown=markdown)
