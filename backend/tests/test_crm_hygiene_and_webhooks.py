import hashlib
import hmac
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.db.base import utcnow
from tests.conftest import MANAGER_HEADERS, SDR_HEADERS, app_client


@pytest.mark.asyncio
async def test_idempotent_crm_webhook_replay_and_hmac(tmp_path: Path) -> None:
    webhook_secret = "test-crm-hmac-signing-secret-32-bytes"
    async with app_client(tmp_path, webhook_signing_secret=webhook_secret) as (_, client):
        payload = {
            "event_id": "evt-hubspot-9001",
            "event_type": "contact.upsert",
            "data": {
                "external_id": "hs-501",
                "first_name": "Maya",
                "last_name": "Lin",
                "email": "maya.lin@meridianai.io",
                "title": "VP Sales",
                "company_name": "Meridian AI",
                "domain": "meridianai.io",
            },
        }
        raw_bytes = json.dumps(payload).encode("utf-8")

        bad_sig = await client.post(
            "/api/v1/crm/webhooks/hubspot",
            content=raw_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": "sha256=deadbeef",
            },
        )
        assert bad_sig.status_code == 401

        good_sig = hmac.new(
            webhook_secret.encode("utf-8"), raw_bytes, hashlib.sha256
        ).hexdigest()
        first = await client.post(
            "/api/v1/crm/webhooks/hubspot",
            content=raw_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": f"sha256={good_sig}",
            },
        )
        assert first.status_code == 200
        assert first.json()["duplicate_ignored"] is False

        replay = await client.post(
            "/api/v1/crm/webhooks/hubspot",
            content=raw_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": f"sha256={good_sig}",
            },
        )
        assert replay.status_code == 200
        assert replay.json()["duplicate_ignored"] is True
        assert replay.json()["id"] == first.json()["id"]

        contacts = (await client.get("/api/v1/prospecting/contacts", headers=SDR_HEADERS)).json()
        assert len(contacts) == 1
        assert contacts[0]["email"] == "maya.lin@meridianai.io"


@pytest.mark.asyncio
async def test_opt_out_webhook_suppresses_contact_and_blocks_touches(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        acc = (
            await client.post(
                "/api/v1/prospecting/accounts",
                headers=SDR_HEADERS,
                json={"name": "Cobalt Bio", "domain": "cobaltbio.io", "industry": "HealthTech"},
            )
        ).json()
        contact = (
            await client.post(
                "/api/v1/prospecting/contacts",
                headers=SDR_HEADERS,
                json={
                    "account_id": acc["id"],
                    "first_name": "Noah",
                    "last_name": "Kim",
                    "email": "noah@cobaltbio.io",
                    "title": "Director Ops",
                },
            )
        ).json()
        await client.post(
            "/api/v1/sequences/generate",
            headers=SDR_HEADERS,
            json={"account_id": acc["id"], "contact_id": contact["id"], "num_steps": 1},
        )

        opt_out_res = await client.post(
            "/api/v1/crm/webhooks/salesforce",
            headers=SDR_HEADERS,
            json={
                "event_id": "sf-optout-77",
                "event_type": "contact.opt_out",
                "data": {"email": "noah@cobaltbio.io", "reason": "CRM DoNotCall checked"},
            },
        )
        assert opt_out_res.status_code == 200
        assert "touches_blocked=1" in opt_out_res.json()["result_summary"]

        seqs = (await client.get("/api/v1/sequences", headers=SDR_HEADERS)).json()
        assert seqs[0]["status"] == "blocked_suppressed"


@pytest.mark.asyncio
async def test_duplicate_contact_scan_and_hitl_merge_preserves_opt_out(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        acc = (
            await client.post(
                "/api/v1/prospecting/accounts",
                headers=SDR_HEADERS,
                json={"name": "Kestrel Data", "domain": "kestreldata.io", "industry": "SaaS"},
            )
        ).json()
        primary = (
            await client.post(
                "/api/v1/prospecting/contacts",
                headers=SDR_HEADERS,
                json={
                    "account_id": acc["id"],
                    "first_name": "Owen",
                    "last_name": "Grant",
                    "email": "owen.grant@kestreldata.io",
                    "title": "VP Revenue",
                    "crm_external_id": "sf-100",
                },
            )
        ).json()
        duplicate = (
            await client.post(
                "/api/v1/prospecting/contacts",
                headers=SDR_HEADERS,
                json={
                    "account_id": acc["id"],
                    "first_name": "Owen",
                    "last_name": "Grant",
                    "email": "o.grant@kestreldata.io",
                    "phone": "+1-415-555-0100",
                },
            )
        ).json()

        deal = (
            await client.post(
                "/api/v1/crm/deals",
                headers=SDR_HEADERS,
                json={
                    "account_id": acc["id"],
                    "primary_contact_id": duplicate["id"],
                    "name": "Kestrel Expansion",
                    "stage": "discovery",
                    "amount_usd": 50000,
                },
            )
        ).json()

        # Suppress duplicate so merge must carry opt-out forward onto primary
        await client.post(
            "/api/v1/prospecting/suppressions",
            headers=SDR_HEADERS,
            json={"scope": "email", "value": duplicate["email"], "reason": "Opted out on alias"},
        )

        dedupe = (
            await client.post("/api/v1/crm/hygiene/deduplicate", headers=SDR_HEADERS)
        ).json()
        assert dedupe["candidates_created"] == 1
        cand = dedupe["candidates"][0]
        assert cand["match_reason"] == "name_and_domain"

        approve_res = await client.post(
            f"/api/v1/audit/approvals/{cand['approval_id']}/decide",
            headers=MANAGER_HEADERS,
            json={"decision": "approved", "notes": "Confirmed duplicate person"},
        )
        assert approve_res.status_code == 200

        active_contacts = (
            await client.get("/api/v1/prospecting/contacts", headers=SDR_HEADERS)
        ).json()
        assert len(active_contacts) == 1
        assert active_contacts[0]["id"] == primary["id"]
        assert active_contacts[0]["phone"] == "+1-415-555-0100"
        assert active_contacts[0]["do_not_contact"] is True

        deals = (await client.get("/api/v1/crm/deals", headers=SDR_HEADERS)).json()
        relinked = next(d for d in deals if d["id"] == deal["id"])
        assert relinked["primary_contact_id"] == primary["id"]


@pytest.mark.asyncio
async def test_deal_hygiene_validation_and_next_step_synthesis(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        acc = (
            await client.post(
                "/api/v1/prospecting/accounts",
                headers=SDR_HEADERS,
                json={"name": "Pulse Robotics", "domain": "pulserobotics.io", "industry": "Tech"},
            )
        ).json()
        stale_ts = (utcnow() - timedelta(days=20)).isoformat()
        past_close = (date.today() - timedelta(days=3)).isoformat()

        deal = (
            await client.post(
                "/api/v1/crm/deals",
                headers=SDR_HEADERS,
                json={
                    "account_id": acc["id"],
                    "name": "Pulse Robotics Suite",
                    "stage": "negotiation",
                    "amount_usd": 0,
                    "close_date": past_close,
                    "next_step": "",
                    "last_activity_at": stale_ts,
                },
            )
        ).json()
        issue_codes = {i["code"] for i in deal["hygiene_issues"]}
        assert {
            "past_close_date",
            "stale_activity",
            "missing_next_step",
            "missing_primary_contact",
            "missing_amount",
            "missing_qualification",
        }.issubset(issue_codes)
        assert deal["hygiene_score"] < 30

        val_res = (
            await client.post("/api/v1/crm/hygiene/validate", headers=SDR_HEADERS)
        ).json()
        assert val_res["deals_checked"] == 1
        assert val_res["deals_flagged"] == 1

        next_step_res = await client.post(
            f"/api/v1/crm/deals/{deal['id']}/next-step",
            headers=SDR_HEADERS,
        )
        assert next_step_res.status_code == 200
        updated_deal = next_step_res.json()
        assert "NEGOTIATION" in updated_deal["next_step"]
        assert updated_deal["hygiene_score"] > deal["hygiene_score"]


@pytest.mark.asyncio
async def test_webhook_deal_upsert_activity_logged_and_missing_key(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        missing_key = await client.post(
            "/api/v1/crm/webhooks/hubspot",
            headers=SDR_HEADERS,
            json={"event_type": "deal.upsert", "data": {"domain": "zeta.io"}},
        )
        assert missing_key.status_code == 400

        deal_evt = await client.post(
            "/api/v1/crm/webhooks/hubspot",
            headers={**SDR_HEADERS, "Idempotency-Key": "hs-deal-1"},
            json={
                "event_type": "deal.upsert",
                "data": {
                    "external_id": "opp-99",
                    "domain": "zeta.io",
                    "company_name": "Zeta Corp",
                    "name": "Zeta Rollout",
                    "stage": "discovery",
                    "amount_usd": 30000,
                },
            },
        )
        assert deal_evt.status_code == 200

        act_evt = await client.post(
            "/api/v1/crm/webhooks/hubspot",
            headers={**SDR_HEADERS, "Idempotency-Key": "hs-act-1"},
            json={
                "event_type": "activity.logged",
                "data": {"deal_external_id": "opp-99", "next_step": "Send MSA draft"},
            },
        )
        assert act_evt.status_code == 200

        webhooks = (await client.get("/api/v1/crm/webhooks", headers=SDR_HEADERS)).json()
        assert len(webhooks) == 2


@pytest.mark.asyncio
async def test_duplicate_candidate_dismissal(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        acc = (
            await client.post(
                "/api/v1/prospecting/accounts",
                headers=SDR_HEADERS,
                json={"name": "Echo Labs", "domain": "echolabs.io"},
            )
        ).json()
        await client.post(
            "/api/v1/prospecting/contacts",
            headers=SDR_HEADERS,
            json={
                "account_id": acc["id"],
                "first_name": "Alex",
                "last_name": "Ray",
                "email": "alex.ray@echolabs.io",
                "phone": "415-555-0111",
            },
        )
        await client.post(
            "/api/v1/prospecting/contacts",
            headers=SDR_HEADERS,
            json={
                "account_id": acc["id"],
                "first_name": "A.",
                "last_name": "Ray",
                "email": "aray@echolabs.io",
                "phone": "(415) 555-0111",
            },
        )

        dedupe = (
            await client.post("/api/v1/crm/hygiene/deduplicate", headers=SDR_HEADERS)
        ).json()
        assert dedupe["candidates_created"] == 1
        cand = dedupe["candidates"][0]
        assert cand["match_reason"] == "normalized_phone"

        reject_res = await client.post(
            f"/api/v1/audit/approvals/{cand['approval_id']}/decide",
            headers=MANAGER_HEADERS,
            json={"decision": "rejected", "notes": "Shared desk line"},
        )
        assert reject_res.status_code == 200

        dups = (
            await client.get("/api/v1/crm/hygiene/duplicates", headers=SDR_HEADERS)
        ).json()
        assert dups[0]["status"] == "dismissed"
