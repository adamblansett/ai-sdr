from pathlib import Path

import pytest

from tests.conftest import MANAGER_HEADERS, SDR_HEADERS, VIEWER_HEADERS, app_client


@pytest.mark.asyncio
async def test_account_signal_creation_and_ai_research(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        viewer_res = await client.post(
            "/api/v1/prospecting/accounts",
            headers=VIEWER_HEADERS,
            json={"name": "Blocked Viewer", "domain": "viewer.io"},
        )
        assert viewer_res.status_code == 403

        acc_res = await client.post(
            "/api/v1/prospecting/accounts",
            headers=SDR_HEADERS,
            json={
                "name": "Nimbus Data",
                "domain": "https://www.NimbusData.io/pricing",
                "industry": "Cloud Infrastructure",
                "employee_count": 280,
                "annual_revenue_usd": 36_000_000,
                "tech_stack": ["Snowflake", "Salesforce", "AWS"],
            },
        )
        assert acc_res.status_code == 201
        acc = acc_res.json()
        assert acc["domain"] == "nimbusdata.io"
        assert acc["status"] == "active"

        sig_res = await client.post(
            f"/api/v1/prospecting/accounts/{acc['id']}/signals",
            headers=SDR_HEADERS,
            json={
                "signal_type": "funding",
                "title": "Closed $30M Series B",
                "summary": "Doubling enterprise SDR pod in Q2.",
                "source_url": "https://nimbusdata.io/press",
                "confidence": 0.9,
                "weight": 30,
            },
        )
        assert sig_res.status_code == 201

        res_brief = await client.post(
            f"/api/v1/prospecting/accounts/{acc['id']}/research",
            headers=SDR_HEADERS,
        )
        assert res_brief.status_code == 200
        data = res_brief.json()
        assert data["llm_provider"] == "mock"
        assert data["account"]["signal_score"] >= 27
        assert data["account"]["icp_fit_score"] >= 60
        assert "Nimbus Data" in data["account"]["research_summary"]


@pytest.mark.asyncio
async def test_csv_import_and_domain_suppression_flagging(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        sup_res = await client.post(
            "/api/v1/prospecting/suppressions",
            headers=SDR_HEADERS,
            json={
                "scope": "domain",
                "value": "BlockedCorp.io",
                "reason": "Competitor policy",
            },
        )
        assert sup_res.status_code == 201

        csv_payload = (
            "first_name,last_name,email,title,company_name,domain\n"
            "Aria,Chen,aria@novadata.io,VP of Sales,NovaData,novadata.io\n"
            "Sam,Lee,sam@blockedcorp.io,CRO,BlockedCorp,blockedcorp.io\n"
            "Bad,Row,not-an-email,SDR,BadCo,badco.io\n"
        )
        imp_res = await client.post(
            "/api/v1/prospecting/contacts/import-csv",
            headers=SDR_HEADERS,
            json={"csv_text": csv_payload},
        )
        assert imp_res.status_code == 200
        imp = imp_res.json()
        assert imp["accounts_created"] == 2
        assert imp["contacts_created"] == 2
        assert imp["contacts_skipped"] == 1
        assert imp["suppressed_flagged"] == 1
        assert len(imp["errors"]) == 1

        contacts_res = await client.get("/api/v1/prospecting/contacts", headers=SDR_HEADERS)
        assert contacts_res.status_code == 200
        by_email = {c["email"]: c for c in contacts_res.json()}
        assert by_email["aria@novadata.io"]["is_suppressed"] is False
        assert by_email["sam@blockedcorp.io"]["is_suppressed"] is True
        assert by_email["sam@blockedcorp.io"]["do_not_contact"] is True


@pytest.mark.asyncio
async def test_suppression_retroactively_blocks_touches_and_manager_deactivate(
    tmp_path: Path,
) -> None:
    async with app_client(tmp_path) as (_, client):
        acc = (
            await client.post(
                "/api/v1/prospecting/accounts",
                headers=SDR_HEADERS,
                json={"name": "Orbit AI", "domain": "orbitai.io", "industry": "SaaS"},
            )
        ).json()
        contact = (
            await client.post(
                "/api/v1/prospecting/contacts",
                headers=SDR_HEADERS,
                json={
                    "account_id": acc["id"],
                    "first_name": "Nina",
                    "last_name": "Patel",
                    "email": "nina@orbitai.io",
                    "title": "VP Growth",
                },
            )
        ).json()

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
        assert len(seq["touches"]) == 2

        sup_res = await client.post(
            "/api/v1/prospecting/suppressions",
            headers=SDR_HEADERS,
            json={
                "scope": "email",
                "value": "nina@orbitai.io",
                "reason": "Unsubscribed via reply",
            },
        )
        assert sup_res.status_code == 201
        sup_data = sup_res.json()
        assert sup_data["contacts_affected"] == 1
        assert sup_data["touches_blocked"] == 2
        entry_id = sup_data["entry"]["id"]

        seqs_after = (await client.get("/api/v1/sequences", headers=SDR_HEADERS)).json()
        assert seqs_after[0]["status"] == "blocked_suppressed"
        assert all(t["status"] == "blocked_suppressed" for t in seqs_after[0]["touches"])

        approvals = (await client.get("/api/v1/audit/approvals", headers=SDR_HEADERS)).json()
        assert all(a["status"] == "rejected" for a in approvals)

        sdr_del = await client.delete(
            f"/api/v1/prospecting/suppressions/{entry_id}",
            headers=SDR_HEADERS,
        )
        assert sdr_del.status_code == 403

        mgr_del = await client.delete(
            f"/api/v1/prospecting/suppressions/{entry_id}",
            headers=MANAGER_HEADERS,
        )
        assert mgr_del.status_code == 200
        assert mgr_del.json()["active"] is False

        contacts_after = (
            await client.get("/api/v1/prospecting/contacts", headers=SDR_HEADERS)
        ).json()
        assert contacts_after[0]["is_suppressed"] is False


@pytest.mark.asyncio
async def test_list_account_signals_and_duplicate_domain_conflict(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        acc = (
            await client.post(
                "/api/v1/prospecting/accounts",
                headers=SDR_HEADERS,
                json={"name": "SignalCo", "domain": "signalco.io"},
            )
        ).json()
        dup = await client.post(
            "/api/v1/prospecting/accounts",
            headers=SDR_HEADERS,
            json={"name": "SignalCo Dup", "domain": "https://www.signalco.io/"},
        )
        assert dup.status_code == 409

        await client.post(
            f"/api/v1/prospecting/accounts/{acc['id']}/signals",
            headers=SDR_HEADERS,
            json={"signal_type": "expansion", "title": "Opened EU hub"},
        )
        sigs = await client.get(
            f"/api/v1/prospecting/accounts/{acc['id']}/signals",
            headers=SDR_HEADERS,
        )
        assert sigs.status_code == 200
        assert len(sigs.json()) == 1
        assert sigs.json()[0]["title"] == "Opened EU hub"
