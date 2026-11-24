from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.auth import create_access_token
from app.core.config import Settings
from app.main import app, create_app
from tests.conftest import app_client


@pytest.mark.asyncio
async def test_health_and_readiness_endpoints(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        for path in ("/api/v1/health", "/api/v1/health/live", "/api/v1/health/ready"):
            response = await client.get(path)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["service"] == "ai-sdr"
            assert data["app_name"] == "AI SDR"
            assert data["database"] == "ok"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.asyncio
async def test_default_app_liveness_probe() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_production_security_validation_rejects_default_secret() -> None:
    insecure = Settings(app_env="production")
    with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
        create_app(insecure)


def test_production_security_rejects_wildcard_cors() -> None:
    insecure = Settings(
        app_env="production",
        auth_secret_key="super-strong-production-secret-key-32-bytes-minimum",
        cors_origins="*",
    )
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        create_app(insecure)


@pytest.mark.asyncio
async def test_production_jwt_auth_and_dev_token_disabled(tmp_path: Path) -> None:
    strong_secret = "super-strong-production-secret-key-32-bytes-minimum"
    async with app_client(
        tmp_path,
        app_env="production",
        auth_secret_key=strong_secret,
        cors_origins="https://sdr.example.com",
    ) as (_, client):
        ready = await client.get("/api/v1/health/ready")
        assert ready.status_code == 200
        assert "strict-transport-security" in ready.headers

        unauth = await client.get("/api/v1/auth/me")
        assert unauth.status_code == 401

        dev_tok = await client.post(
            "/api/v1/auth/dev-token",
            json={"email": "attacker@example.com", "role": "admin"},
        )
        assert dev_tok.status_code == 403

        token = create_access_token("vp@example.com", "sales_manager", strong_secret)
        authed = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert authed.status_code == 200
        assert authed.json() == {
            "email": "vp@example.com",
            "role": "sales_manager",
            "auth_method": "bearer_token",
        }

        expired = create_access_token(
            "vp@example.com", "sales_manager", strong_secret, ttl_seconds=-10
        )
        expired_res = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {expired}"},
        )
        assert expired_res.status_code == 401


@pytest.mark.asyncio
async def test_dev_token_and_invalid_role_header(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        bad_role = await client.get(
            "/api/v1/auth/me",
            headers={"X-Actor-Role": "superuser"},
        )
        assert bad_role.status_code == 400

        tok_res = await client.post(
            "/api/v1/auth/dev-token",
            json={"email": "sdr@local.test", "role": "sdr", "ttl_seconds": 600},
        )
        assert tok_res.status_code == 200
        token = tok_res.json()["access_token"]

        me_res = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_res.status_code == 200
        assert me_res.json()["role"] == "sdr"
        assert me_res.json()["auth_method"] == "bearer_token"
