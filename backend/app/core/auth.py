import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import Literal, cast

from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.core.config import Settings, get_settings

ActorRole = Literal["viewer", "sdr", "sales_manager", "admin"]
VALID_ROLES: tuple[ActorRole, ...] = ("viewer", "sdr", "sales_manager", "admin")


class Actor(BaseModel):
    """Authenticated or development-scoped user/actor context."""

    email: str
    role: ActorRole
    auth_method: str


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(token_part: str) -> bytes:
    padding = "=" * (-len(token_part) % 4)
    return base64.urlsafe_b64decode(token_part + padding)


def create_access_token(
    email: str,
    role: ActorRole,
    secret_key: str,
    ttl_seconds: int = 3600,
) -> str:
    """Create an HMAC-SHA256 signed bearer token."""
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8"))
    payload_dict = {
        "sub": email,
        "role": role,
        "exp": int(time.time()) + ttl_seconds,
    }
    payload = _b64url_encode(json.dumps(payload_dict, sort_keys=True).encode("utf-8"))
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url_encode(signature)}"


def verify_access_token(token: str, secret_key: str) -> Actor:
    """Validate an HMAC-SHA256 bearer token and return the Actor."""
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token format.",
        )

    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        actual_sig = _b64url_decode(sig_b64)
        payload_bytes = _b64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed authentication token.",
        ) from exc

    if not hmac.compare_digest(actual_sig, expected_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token signature.",
        )

    exp = payload.get("exp")
    if not isinstance(exp, int | float) or exp < time.time():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired.",
        )

    email = str(payload.get("sub") or "").strip()
    role_raw = str(payload.get("role") or "").strip().lower()
    if not email or role_raw not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token claims.",
        )

    return Actor(email=email, role=cast(ActorRole, role_raw), auth_method="bearer_token")


def resolve_request_settings(request: Request, settings: Settings | None = None) -> Settings:
    """Resolve app-scoped settings before falling back to global settings."""
    if settings is not None:
        return settings
    app_cfg = getattr(request.app.state, "settings", None)
    if isinstance(app_cfg, Settings):
        return app_cfg
    return get_settings()


async def get_current_actor(request: Request) -> Actor:
    """Resolve current actor from Bearer token or development actor headers."""
    settings = resolve_request_settings(request)
    auth_header = request.headers.get("authorization", "").strip()
    if auth_header:
        if not auth_header.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header must use Bearer scheme.",
            )
        token = auth_header[7:].strip()
        return verify_access_token(token, settings.auth_secret_key)

    is_prod = settings.app_env.strip().lower() == "production"
    if settings.auth_require_token or is_prod:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token authentication is required.",
        )

    email = request.headers.get("x-actor-email", "manager@acme-sdr.local").strip()
    if not email:
        email = "manager@acme-sdr.local"
    role_raw = request.headers.get("x-actor-role", "sales_manager").strip().lower()
    if role_raw not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Actor-Role '{role_raw}'. Expected one of: {', '.join(VALID_ROLES)}.",
        )
    return Actor(email=email, role=cast(ActorRole, role_raw), auth_method="dev_header")


def require_roles(*roles: ActorRole) -> Callable[..., Actor]:
    """Dependency enforcing that the active actor holds one of the allowed roles."""

    def _checker(actor: Actor = Depends(get_current_actor)) -> Actor:
        if actor.role not in roles:
            allowed = ", ".join(roles)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions; required role: {allowed}.",
            )
        return actor

    return _checker
