from fastapi import APIRouter, Depends, HTTPException

from core.schemas import LoginRequest, RegisterRequest, TokenResponse, MessageResponse
from core.security import create_access_token, get_current_user, CurrentUser
from database.db_utils import register_user, verify_login

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=MessageResponse)
async def register(payload: RegisterRequest):
    ok, message = register_user(payload.username, payload.password)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return MessageResponse(message=message)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    ok, user_id = verify_login(payload.username, payload.password)
    if not ok:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    token = create_access_token(user_id=user_id, username=payload.username)
    return TokenResponse(access_token=token, user_id=user_id, username=payload.username)


@router.get("/me")
async def me(current_user: CurrentUser = Depends(get_current_user)):
    return {"user_id": current_user.user_id, "username": current_user.username}
