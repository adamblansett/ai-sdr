import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import app, create_app


@pytest.mark.asyncio
async def test_health_and_readiness_endpoints() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ("/api/v1/health", "/api/v1/health/live", "/api/v1/health/ready"):
            response = await client.get(path)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["service"] == "ai-sdr"
            assert data["app_name"] == "AI SDR"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["x-frame-options"] == "DENY"


def test_production_security_validation_rejects_default_secret() -> None:
    insecure = Settings(app_env="production")
    with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
        create_app(insecure)
