from pathlib import Path

import pytest

from app.core.config import Settings
from app.llm.pii import redact_pii
from app.llm.router import LLMRouter
from tests.conftest import SDR_HEADERS, app_client


class _RecordingCloudAdapter:
    provider_name = "gemini"
    model_name = "gemini-2.5-flash"

    def __init__(self) -> None:
        self.last_prompt = ""
        self.last_system = ""

    async def generate(self, prompt: str, system_prompt: str, task_type: str) -> str:
        _ = task_type
        self.last_prompt = prompt
        self.last_system = system_prompt
        return "Cloud rationale generated safely."


class _FailingAdapter:
    provider_name = "ollama"
    model_name = "llama-3.1-8b-instruct"

    async def generate(self, prompt: str, system_prompt: str, task_type: str) -> str:
        _ = (prompt, system_prompt, task_type)
        raise RuntimeError("Ollama offline")


def test_redact_pii_scrubs_sensitive_tokens() -> None:
    sample = (
        "Contact elena.rostova@helioscloud.io or +1-512-555-0142. "
        "SSN 123-45-6789, card 4532-0151-1283-0366, token sk-live-secret1234567890, "
        "ref id 1234567890123456."
    )
    result = redact_pii(sample)
    assert "[REDACTED_EMAIL]" in result.redacted_text
    assert "[REDACTED_PHONE]" in result.redacted_text
    assert "[REDACTED_SSN]" in result.redacted_text
    assert "[REDACTED_CARD]" in result.redacted_text
    assert "[REDACTED_SECRET]" in result.redacted_text
    assert "elena.rostova@helioscloud.io" not in result.redacted_text
    assert "123-45-6789" not in result.redacted_text
    assert "1234567890123456" in result.redacted_text
    assert result.total_redactions == 5


@pytest.mark.asyncio
async def test_llm_router_redacts_pii_before_cloud_call() -> None:
    cfg = Settings(
        llm_default_provider="gemini",
        llm_fallback_providers="mock",
        llm_redact_pii_for_cloud=True,
    )
    router = LLMRouter(cfg)
    recorder = _RecordingCloudAdapter()
    router.adapters["gemini"] = recorder

    res = await router.generate(
        prompt="Reach john.doe@acme.com at 415-555-0199 with Bearer topsecret_token_987654",
        system_prompt="Reply to ops@acme.com",
        task_type="general",
    )

    assert res.provider == "gemini"
    assert res.pii_redacted is True
    assert res.redaction_count == 4
    assert "john.doe@acme.com" not in recorder.last_prompt
    assert "415-555-0199" not in recorder.last_prompt
    assert "ops@acme.com" not in recorder.last_system
    assert "[REDACTED_EMAIL]" in recorder.last_prompt
    assert "[REDACTED_PHONE]" in recorder.last_prompt
    assert "[REDACTED_SECRET]" in recorder.last_prompt


@pytest.mark.asyncio
async def test_llm_router_falls_back_from_failing_ollama_to_mock() -> None:
    cfg = Settings(
        llm_default_provider="ollama",
        llm_fallback_providers="mock",
    )
    router = LLMRouter(cfg)
    router.adapters["ollama"] = _FailingAdapter()

    res = await router.generate(
        prompt="Account: Acme Cloud\nIndustry: SaaS\nVerified Signals: Series B raised",
        task_type="account_research",
    )
    assert res.provider == "mock"
    assert res.model == "deterministic-sdr-v1"
    assert "Acme Cloud" in res.content


@pytest.mark.asyncio
async def test_audit_pii_preview_endpoint(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        res = await client.post(
            "/api/v1/audit/pii-preview",
            headers=SDR_HEADERS,
            json={"text": "Email alice@corp.io or call (617) 555-0188"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["total_redactions"] == 2
        assert "[REDACTED_EMAIL]" in body["redacted_text"]
        assert "[REDACTED_PHONE]" in body["redacted_text"]
