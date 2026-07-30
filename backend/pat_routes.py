"""Account endpoints for managing Personal Access Tokens (the MCP connector creds).

All auth-gated via require_user_id — a user only ever sees/creates/revokes their
OWN tokens. The plaintext token is returned exactly once, on create.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_user_id
import pat

router = APIRouter(prefix="/account/tokens", tags=["tokens"])


class CreateTokenRequest(BaseModel):
    name: str | None = None


@router.post("")
async def create_token(req: CreateTokenRequest, user_id: str = Depends(require_user_id)):
    try:
        return pat.create_token(user_id, name=req.name or "API token")
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Token storage not configured")


@router.get("")
async def list_tokens(user_id: str = Depends(require_user_id)):
    return {"tokens": pat.list_tokens(user_id)}


@router.delete("/{token_id}")
async def revoke_token(token_id: str, user_id: str = Depends(require_user_id)):
    if not pat.revoke_token(user_id, token_id):
        raise HTTPException(status_code=404, detail="Token not found")
    return {"ok": True}
