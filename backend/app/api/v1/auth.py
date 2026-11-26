from datetime import datetime
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.auth import (
    VALID_ROLES,
    Actor,
    ActorRole,
    create_access_token,
    get_current_actor,
    hash_password,
    require_roles,
    resolve_request_settings,
    verify_password,
)
from app.db.models import User
from app.db.session import get_db

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


class UserOut(BaseModel):
    """Serialized persisted user (never exposes password_hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str
    role: str
    active: bool
    created_at: datetime


class RegisterUserRequest(BaseModel):
    """Payload to register a persisted workspace user."""

    email: str = Field(..., min_length=3, max_length=255)
    full_name: str = Field(default="", max_length=160)
    role: ActorRole = "sdr"
    password: str = Field(..., min_length=8, max_length=128)


class RegisterUserResponse(BaseModel):
    """Registration receipt with issued bearer token."""

    user: UserOut
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600


class LoginRequest(BaseModel):
    """Email + password login payload."""

    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)


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


@router.post(
    "/register",
    response_model=RegisterUserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_user(
    body: RegisterUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RegisterUserResponse:
    """Register a persisted user with scrypt password hashing."""
    cfg = resolve_request_settings(request)
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Valid email address is required.",
        )

    existing_any = (await db.execute(select(User.id).limit(1))).scalar_one_or_none()
    is_prod = cfg.app_env.strip().lower() == "production"
    if is_prod and existing_any is not None:
        caller = await get_current_actor(request)
        if caller.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin privileges required to register additional users in production.",
            )

    dup = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User '{email}' already exists.",
        )

    user = User(
        email=email,
        full_name=body.full_name.strip() or email.split("@", 1)[0].replace(".", " ").title(),
        role=body.role,
        password_hash=hash_password(body.password),
        active=True,
    )
    db.add(user)
    await db.flush()

    actor_obj = Actor(email=user.email, role=body.role, auth_method="bearer_token")
    await record_audit_event(
        db,
        event_type="auth.user_registered",
        actor=actor_obj,
        entity_type="user",
        entity_id=user.id,
        action="registered",
        details={"role": user.role},
    )
    await db.commit()
    await db.refresh(user)

    token = create_access_token(
        email=user.email,
        role=body.role,
        secret_key=cfg.auth_secret_key,
        ttl_seconds=3600,
    )
    return RegisterUserResponse(
        user=UserOut.model_validate(user),
        access_token=token,
    )


@router.post("/login", response_model=DevTokenResponse)
async def login_user(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DevTokenResponse:
    """Authenticate email + password and issue an HS256 bearer token."""
    cfg = resolve_request_settings(request)
    email = body.email.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None or not user.active or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    role_val: ActorRole = (
        cast(ActorRole, user.role) if user.role in VALID_ROLES else "viewer"
    )
    actor_obj = Actor(email=user.email, role=role_val, auth_method="bearer_token")
    await record_audit_event(
        db,
        event_type="auth.user_logged_in",
        actor=actor_obj,
        entity_type="user",
        entity_id=user.id,
        action="login",
        details={"role": role_val},
    )
    await db.commit()

    token = create_access_token(
        email=user.email,
        role=role_val,
        secret_key=cfg.auth_secret_key,
        ttl_seconds=3600,
    )
    return DevTokenResponse(
        access_token=token,
        expires_in=3600,
        actor=actor_obj,
    )


@router.get("/users", response_model=list[UserOut])
async def list_users(
    actor: Actor = Depends(require_roles("sales_manager", "admin")),
    db: AsyncSession = Depends(get_db),
) -> list[UserOut]:
    """List workspace users (sales_manager/admin only)."""
    _ = actor
    users = list((await db.execute(select(User).order_by(User.created_at.asc()))).scalars().all())
    return [UserOut.model_validate(u) for u in users]
