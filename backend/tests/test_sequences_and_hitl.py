from pathlib import Path

import pytest

from tests.conftest import MANAGER_HEADERS, SDR_HEADERS, app_client


async def _create_account_and_contact(client, domain: str = "vectortech.io"):  # type: ignore[no-untyped-def]
    acc = (
        await client.post(
            "/api/v1/prospecting/accounts",
            headers=SDR_HEADERS,
            json={
                "name": "VectorTech",
                "domain": domain,
                "industry": "DevOps",
                "employee_count": 210,
                "tech_stack": ["AWS", "Kubernetes", "Salesforce"],
            },
        )
    ).json()
    await client.post(
        f"/api/v1/prospecting/accounts/{acc['id']}/signals",
        headers=SDR_HEADERS,
        json={
            "signal_type": "hiring",
            "title": "Hiring VP of Sales & 5 SDRs",
            "summary": "Scaling outbound GTM team.",
            "source_url": f"https://{domain}/careers",
            "confidence": 0.9,
            "weight": 25,
        },
    )
    contact = (
        await client.post(
            "/api/v1/prospecting/contacts",
            headers=SDR_HEADERS,
            json={
                "account_id": acc["id"],
                "first_name": "Liam",
                "last_name": "Torres",
                "email": f"liam@{domain}",
                "title": "VP Sales",
            },
        )
    ).json()
    return acc, contact


@pytest.mark.asyncio
async def test_suppressed_contact_blocked_from_sequence_generation(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        acc, contact = await _create_account_and_contact(client)
        await client.post(
            "/api/v1/prospecting/suppressions",
            headers=SDR_HEADERS,
            json={"scope": "email", "value": contact["email"], "reason": "Opted out"},
        )

        gen_res = await client.post(
            "/api/v1/sequences/generate",
            headers=SDR_HEADERS,
            json={"account_id": acc["id"], "contact_id": contact["id"]},
        )
        assert gen_res.status_code == 409
        assert "blocked" in gen_res.json()["detail"].lower()

        events = (await client.get("/api/v1/audit/events", headers=SDR_HEADERS)).json()
        assert any(ev["event_type"] == "sequence.blocked_suppressed" for ev in events)


@pytest.mark.asyncio
async def test_sequence_hitl_approval_send_and_rbac(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        acc, contact = await _create_account_and_contact(client)
        seq = (
            await client.post(
                "/api/v1/sequences/generate",
                headers=SDR_HEADERS,
                json={
                    "account_id": acc["id"],
                    "contact_id": contact["id"],
                    "num_steps": 2,
                },
            )
        ).json()
        touch1 = seq["touches"][0]
        assert touch1["status"] == "pending_approval"
        assert touch1["unsubscribe_footer_included"] is True
        assert "UNSUBSCRIBE" in touch1["body"]
        assert len(touch1["grounded_facts"]) >= 1

        unapproved_send = await client.post(
            f"/api/v1/sequences/touches/{touch1['id']}/send",
            headers=MANAGER_HEADERS,
        )
        assert unapproved_send.status_code == 409

        sdr_approve = await client.post(
            f"/api/v1/audit/approvals/{touch1['approval_id']}/decide",
            headers=SDR_HEADERS,
            json={"decision": "approved", "notes": "SDR self-approve attempt"},
        )
        assert sdr_approve.status_code == 403

        mgr_approve = await client.post(
            f"/api/v1/audit/approvals/{touch1['approval_id']}/decide",
            headers=MANAGER_HEADERS,
            json={"decision": "approved", "notes": "Verified facts and tone"},
        )
        assert mgr_approve.status_code == 200
        assert mgr_approve.json()["status"] == "approved"

        sdr_send = await client.post(
            f"/api/v1/sequences/touches/{touch1['id']}/send",
            headers=SDR_HEADERS,
        )
        assert sdr_send.status_code == 403

        mgr_send = await client.post(
            f"/api/v1/sequences/touches/{touch1['id']}/send",
            headers=MANAGER_HEADERS,
        )
        assert mgr_send.status_code == 200
        sent_touch = mgr_send.json()
        assert sent_touch["status"] == "sent"
        assert sent_touch["provider_message_id"].startswith("msg-")


@pytest.mark.asyncio
async def test_editing_approved_touch_resets_to_pending_approval(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        acc, contact = await _create_account_and_contact(client)
        seq = (
            await client.post(
                "/api/v1/sequences/generate",
                headers=SDR_HEADERS,
                json={"account_id": acc["id"], "contact_id": contact["id"], "num_steps": 1},
            )
        ).json()
        touch = seq["touches"][0]
        await client.post(
            f"/api/v1/audit/approvals/{touch['approval_id']}/decide",
            headers=MANAGER_HEADERS,
            json={"decision": "approved", "notes": "Initial approval"},
        )

        edited = (
            await client.patch(
                f"/api/v1/sequences/touches/{touch['id']}",
                headers=SDR_HEADERS,
                json={"subject": "Updated subject line", "body": "Edited body copy"},
            )
        ).json()
        assert edited["status"] == "pending_approval"
        assert edited["approved_by"] is None
        assert edited["approval_id"] != touch["approval_id"]
        assert "UNSUBSCRIBE" in edited["body"]

        blocked_send = await client.post(
            f"/api/v1/sequences/touches/{touch['id']}/send",
            headers=MANAGER_HEADERS,
        )
        assert blocked_send.status_code == 409


@pytest.mark.asyncio
async def test_post_approval_opt_out_blocks_send(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        acc, contact = await _create_account_and_contact(client)
        seq = (
            await client.post(
                "/api/v1/sequences/generate",
                headers=SDR_HEADERS,
                json={"account_id": acc["id"], "contact_id": contact["id"], "num_steps": 1},
            )
        ).json()
        touch = seq["touches"][0]
        await client.post(
            f"/api/v1/audit/approvals/{touch['approval_id']}/decide",
            headers=MANAGER_HEADERS,
            json={"decision": "approved", "notes": "Looks good"},
        )

        await client.post(
            "/api/v1/prospecting/suppressions",
            headers=SDR_HEADERS,
            json={"scope": "email", "value": contact["email"], "reason": "Do not contact"},
        )

        send_res = await client.post(
            f"/api/v1/sequences/touches/{touch['id']}/send",
            headers=MANAGER_HEADERS,
        )
        assert send_res.status_code == 409
