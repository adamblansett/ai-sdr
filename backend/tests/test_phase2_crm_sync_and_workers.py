from pathlib import Path

import pytest

from tests.conftest import MANAGER_HEADERS, SDR_HEADERS, app_client


@pytest.mark.asyncio
async def test_outbound_crm_sync_idempotency_and_workers(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        seed = await client.post("/api/v1/seed/demo", headers=MANAGER_HEADERS)
        assert seed.status_code == 200

        quals = (await client.get("/api/v1/qualification/records", headers=SDR_HEADERS)).json()
        qual_id = quals[0]["id"]

        push1 = await client.post(
            "/api/v1/crm/sync/push",
            headers=SDR_HEADERS,
            json={"operation": "qualification_sync", "entity_id": qual_id},
        )
        assert push1.status_code == 200
        job1 = push1.json()
        assert job1["status"] == "synced"
        assert job1["provider"] == "mock"

        push2 = await client.post(
            "/api/v1/crm/sync/push",
            headers=SDR_HEADERS,
            json={"operation": "qualification_sync", "entity_id": qual_id},
        )
        assert push2.status_code == 200
        assert push2.json()["id"] == job1["id"]

        sweep_hygiene = await client.post(
            "/api/v1/workers/jobs/crm_hygiene_sweep/run",
            headers=SDR_HEADERS,
        )
        assert sweep_hygiene.status_code == 201
        hjob = sweep_hygiene.json()
        assert hjob["status"] == "completed"
        assert hjob["result_json"]["deals_checked"] == 3

        sweep_followup = await client.post(
            "/api/v1/workers/jobs/sequence_followup_sweep/run",
            headers=SDR_HEADERS,
        )
        assert sweep_followup.status_code == 201
        assert sweep_followup.json()["result_json"]["touches_awaiting_approval"] == 3

        jobs_list = (await client.get("/api/v1/workers/jobs", headers=SDR_HEADERS)).json()
        assert len(jobs_list) >= 3


@pytest.mark.asyncio
async def test_full_phase2_cross_module_lifecycle_e2e(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "director@acme-sdr.local",
                "full_name": "Director",
                "role": "sales_manager",
                "password": "DirectorPassword123!",
            },
        )
        assert reg.status_code == 201
        headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}

        acc = (
            await client.post(
                "/api/v1/prospecting/accounts",
                headers=headers,
                json={
                    "name": "Zenith Data",
                    "domain": "zenithdata.io",
                    "industry": "SaaS",
                    "employee_count": 300,
                    "tech_stack": ["Snowflake", "Salesforce", "AWS"],
                },
            )
        ).json()
        await client.post(
            f"/api/v1/prospecting/accounts/{acc['id']}/signals",
            headers=headers,
            json={
                "signal_type": "funding",
                "title": "Raised $50M Series B for GTM scale",
                "summary": "Scaling outbound SDRs.",
                "weight": 35,
            },
        )
        contact = (
            await client.post(
                "/api/v1/prospecting/contacts",
                headers=headers,
                json={
                    "account_id": acc["id"],
                    "first_name": "Nadia",
                    "last_name": "Vance",
                    "email": "nadia@zenithdata.io",
                    "title": "VP Sales",
                },
            )
        ).json()
        qual = (
            await client.post(
                "/api/v1/qualification/evaluate",
                headers=headers,
                json={"account_id": acc["id"], "contact_id": contact["id"]},
            )
        ).json()
        assert qual["intent_tier"] == "high"

        seq = (
            await client.post(
                "/api/v1/sequences/generate",
                headers=headers,
                json={"account_id": acc["id"], "contact_id": contact["id"], "num_steps": 2},
            )
        ).json()
        touch1 = seq["touches"][0]

        await client.post(
            f"/api/v1/audit/approvals/{touch1['approval_id']}/decide",
            headers=headers,
            json={"decision": "approved", "notes": "Ready"},
        )
        sent = (
            await client.post(
                f"/api/v1/sequences/touches/{touch1['id']}/send",
                headers=headers,
            )
        ).json()
        assert sent["status"] == "sent"
        assert sent["delivery_provider"] == "mock"

        seqs_after_send = (await client.get("/api/v1/sequences", headers=headers)).json()
        assert seqs_after_send[0]["touches"][1]["scheduled_for"] is not None

        await client.post(
            "/api/v1/crm/sync/push",
            headers=headers,
            json={"operation": "qualification_sync", "entity_id": qual["id"]},
        )
        await client.post(
            "/api/v1/sequences/replies/inbound",
            headers=headers,
            json={
                "sender_email": "nadia@zenithdata.io",
                "subject": "Re: Quick question",
                "body": "Unsubscribe me please.",
            },
        )

        verify = (await client.get("/api/v1/audit/verify", headers=headers)).json()
        assert verify["valid"] is True
