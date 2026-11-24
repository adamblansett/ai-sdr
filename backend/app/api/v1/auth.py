from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.auth import (
    Actor,
    ActorRole,
    create_access_token,
    get_current_actor,
    resolve_request_settings,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class DevTokenRequest(BaseModel):
    """Request payload for issuing a development/test HMAC bearer token."""

    email: str = Field(default="manager@acme-sdr.local", min_length=3, max_length=255)
    role: ActorRole = "sales_manager"
    ttl_seconds: int = Field(default=3600, ge=60, le=86400)


class DevTokenResponse(BaseModel):
    """Response payload returning a signed development bearer token."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    actor: Actor


@router.get("/me", response_model=Actor)
async def get_me(actor: Actor = Depends(get_current_actor)) -> Actor:
    """Return the active authenticated or development actor context."""
    return actor


@router.post("/dev-token", response_model=DevTokenResponse)
async def issue_dev_token(
    body: DevTokenRequest,
    request: Request,
) -> DevTokenResponse:
    """Issue a signed bearer token when running outside production mode."""
    cfg = resolve_request_settings(request)
    if cfg.app_env.strip().lower() == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Development token issuance is disabled in production.",
        )
    token = create_access_token(
        email=body.email.strip(),
        role=body.role,
        secret_key=cfg.auth_secret_key,
        ttl_seconds=body.ttl_seconds,
    )
    return DevTokenResponse(
        access_token=token,
        expires_in=body.ttl_seconds,
        actor=Actor(email=body.email.strip(), role=body.role, auth_method="bearer_token"),
    )
