from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.retrieval.embeddings import cosine_similarity, deterministic_embed
from app.sequences.delivery import EmailDeliveryService
from app.sequences.replies import classify_reply
from tests.conftest import MANAGER_HEADERS, SDR_HEADERS, app_client


def test_deterministic_embeddings_and_reply_classifier() -> None:
    v1 = deterministic_embed("Snowflake telemetry and Series B cloud outbound")
    v2 = deterministic_embed("Cloud outbound automation for Snowflake telemetry")
    v3 = deterministic_embed("Refrigerated freight fleet logistics invoice")
    assert len(v1) == 384
    assert cosine_similarity(v1, v2) > cosine_similarity(v1, v3)

    assert (
        classify_reply("Re: Quick question", "Please unsubscribe me immediately")[0]
        == "unsubscribe"
    )
    assert classify_reply("Automatic reply: OOO", "I am out of office until Monday")[0] == "ooo"
    assert (
        classify_reply("Re: Demo", "Interested — let's schedule a 15-min call")[0]
        == "interested"
    )
    assert (
        classify_reply("Re: Notes", "We already have a competitor and no budget")[0]
        == "objection"
    )


@pytest.mark.asyncio
async def test_semantic_search_grounds_qualification_and_sequence(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        acc = (
            await client.post(
                "/api/v1/prospecting/accounts",
                headers=SDR_HEADERS,
                json={
                    "name": "Aurora Observability",
                    "domain": "auroraobs.io",
                    "industry": "Cloud Infrastructure",
                    "employee_count": 260,
                    "tech_stack": ["Snowflake", "Salesforce", "AWS"],
                },
            )
        ).json()
        contact = (
            await client.post(
                "/api/v1/prospecting/contacts",
                headers=SDR_HEADERS,
                json={
                    "account_id": acc["id"],
                    "first_name": "Dana",
                    "last_name": "Kerr",
                    "email": "dana@auroraobs.io",
                    "title": "VP Revenue Operations",
                },
            )
        ).json()
        await client.post(
            "/api/v1/retrieval/documents",
            headers=SDR_HEADERS,
            json={
                "source_type": "case_study",
                "title": "Cloud Observability Snowflake Outbound Benchmark",
                "content": "Helped cloud observability teams lift Snowflake GTM pipeline 40%.",
                "source_url": "https://acme-sdr.local/cases/aurora",
            },
        )
        await client.post(
            "/api/v1/retrieval/documents",
            headers=SDR_HEADERS,
            json={
                "source_type": "playbook",
                "title": "Retail Warehouse Inventory Guide",
                "content": "Physical barcode scanner deployment for brick-and-mortar retail.",
            },
        )

        search_res = await client.post(
            "/api/v1/retrieval/search",
            headers=SDR_HEADERS,
            json={
                "query": "Snowflake cloud observability pipeline",
                "account_id": acc["id"],
                "top_k": 2,
            },
        )
        assert search_res.status_code == 200
        hits = search_res.json()
        assert len(hits) >= 1
        assert "Snowflake" in hits[0]["chunk"]["title"]

        qual = (
            await client.post(
                "/api/v1/qualification/evaluate",
                headers=SDR_HEADERS,
                json={
                    "account_id": acc["id"],
                    "contact_id": contact["id"],
                    "discovery_notes": (
                        "Evaluating Snowflake observability outbound workflow in Q2."
                    ),
                },
            )
        ).json()
        assert any("Snowflake" in c["title"] for c in qual["evidence_citations"])

        seq = (
            await client.post(
                "/api/v1/sequences/generate",
                headers=SDR_HEADERS,
                json={
                    "account_id": acc["id"],
                    "contact_id": contact["id"],
                    "goal": "Lift Snowflake observability pipeline",
                    "num_steps": 1,
                },
            )
        ).json()
        assert any("CASE_STUDY" in f for f in seq["touches"][0]["grounded_facts"])


@pytest.mark.asyncio
async def test_inbound_reply_opt_out_and_interested_pause(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        acc = (
            await client.post(
                "/api/v1/prospecting/accounts",
                headers=SDR_HEADERS,
                json={"name": "Beacon AI", "domain": "beaconai.io", "industry": "SaaS"},
            )
        ).json()
        c_opt = (
            await client.post(
                "/api/v1/prospecting/contacts",
                headers=SDR_HEADERS,
                json={
                    "account_id": acc["id"],
                    "first_name": "Eva",
                    "last_name": "Moon",
                    "email": "eva@beaconai.io",
                    "title": "VP Sales",
                },
            )
        ).json()
        c_int = (
            await client.post(
                "/api/v1/prospecting/contacts",
                headers=SDR_HEADERS,
                json={
                    "account_id": acc["id"],
                    "first_name": "Leo",
                    "last_name": "Park",
                    "email": "leo@beaconai.io",
                    "title": "CRO",
                },
            )
        ).json()

        await client.post(
            "/api/v1/sequences/generate",
            headers=SDR_HEADERS,
            json={"account_id": acc["id"], "contact_id": c_opt["id"], "num_steps": 2},
        )
        await client.post(
            "/api/v1/sequences/generate",
            headers=SDR_HEADERS,
            json={"account_id": acc["id"], "contact_id": c_int["id"], "num_steps": 1},
        )

        opt_reply = await client.post(
            "/api/v1/sequences/replies/inbound",
            headers=SDR_HEADERS,
            json={
                "sender_email": "eva@beaconai.io",
                "subject": "Re: Quick question",
                "body": "Please unsubscribe me from all future emails.",
            },
        )
        assert opt_reply.status_code == 200
        assert opt_reply.json()["classification"] == "unsubscribe"

        int_reply = await client.post(
            "/api/v1/sequences/replies/inbound",
            headers=SDR_HEADERS,
            json={
                "sender_email": "leo@beaconai.io",
                "subject": "Re: Intro",
                "body": "Interested! Send calendar times for Thursday.",
            },
        )
        assert int_reply.status_code == 200
        assert int_reply.json()["classification"] == "interested"

        seqs = (await client.get("/api/v1/sequences", headers=MANAGER_HEADERS)).json()
        by_contact = {s["contact_id"]: s for s in seqs}
        assert by_contact[c_opt["id"]]["status"] == "blocked_suppressed"
        assert by_contact[c_int["id"]]["status"] == "paused"

        replies_list = (await client.get("/api/v1/sequences/replies", headers=SDR_HEADERS)).json()
        assert len(replies_list) == 2


@pytest.mark.asyncio
async def test_resend_email_delivery_provider_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _MockResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"id": "resend_msg_999"}

    class _MockAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _ = (args, kwargs)

        async def __aenter__(self) -> "_MockAsyncClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> _MockResponse:
            captured["url"] = url
            captured["headers"] = kwargs.get("headers")
            captured["json"] = kwargs.get("json")
            return _MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _MockAsyncClient)
    service = EmailDeliveryService(
        Settings(
            email_provider="resend",
            resend_api_key="re_test_123456",
            email_from_address="outreach@acme-sdr.local",
        )
    )
    res = await service.send_email(
        to_email="prospect@example.com",
        subject="Hello",
        body="Body text",
    )
    assert res.provider == "resend"
    assert res.message_id == "resend_msg_999"
    assert captured["headers"]["Authorization"] == "Bearer re_test_123456"
    assert captured["json"]["to"] == ["prospect@example.com"]
