from pathlib import Path

import pytest

from tests.conftest import SDR_HEADERS, app_client


@pytest.mark.asyncio
async def test_rubric_icp_scoring_and_bant_meddic_extraction(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        acc = (
            await client.post(
                "/api/v1/prospecting/accounts",
                headers=SDR_HEADERS,
                json={
                    "name": "Stratos Cloud",
                    "domain": "stratoscloud.io",
                    "industry": "SaaS",
                    "employee_count": 320,
                    "annual_revenue_usd": 45_000_000,
                    "tech_stack": ["Salesforce", "Snowflake", "AWS"],
                },
            )
        ).json()

        sig = (
            await client.post(
                f"/api/v1/prospecting/accounts/{acc['id']}/signals",
                headers=SDR_HEADERS,
                json={
                    "signal_type": "funding",
                    "title": "Raised $38M Series B for enterprise GTM",
                    "summary": "Hiring RevOps and SDR leadership.",
                    "evidence_excerpt": "Expanding outbound GTM team in Q2.",
                    "source_url": "https://stratoscloud.io/series-b",
                    "confidence": 0.95,
                    "weight": 40,
                },
            )
        ).json()

        contact = (
            await client.post(
                "/api/v1/prospecting/contacts",
                headers=SDR_HEADERS,
                json={
                    "account_id": acc["id"],
                    "first_name": "Claire",
                    "last_name": "Bennett",
                    "email": "claire@stratoscloud.io",
                    "title": "VP of Revenue Operations",
                },
            )
        ).json()

        qual_res = await client.post(
            "/api/v1/qualification/evaluate",
            headers=SDR_HEADERS,
            json={
                "account_id": acc["id"],
                "contact_id": contact["id"],
                "discovery_notes": (
                    "Budget approved for Q2 outbound automation pilot. "
                    "Manual CRM hygiene pain slowing 25% SQL conversion target. "
                    "Security criteria require PII redaction."
                ),
            },
        )
        assert qual_res.status_code == 201
        qual = qual_res.json()
        assert qual["icp_score"] >= 75
        assert qual["intent_tier"] == "high"
        assert qual["grade"] in ("A", "B")
        assert "Budget approved" in qual["bant"]["budget"]
        assert "Q2" in qual["bant"]["timeline"]
        assert "25%" in qual["meddic"]["metrics"]
        assert "PII redaction" in qual["meddic"]["decision_criteria"]
        assert len(qual["rubric_breakdown"]) == 5
        assert qual["evidence_citations"][0]["signal_id"] == sig["id"]
        assert qual["evidence_citations"][0]["source_url"] == "https://stratoscloud.io/series-b"


@pytest.mark.asyncio
async def test_suppressed_account_auto_disqualified_and_filtering(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        suppressed_acc = (
            await client.post(
                "/api/v1/prospecting/accounts",
                headers=SDR_HEADERS,
                json={"name": "Rival Co", "domain": "rivalco.io", "industry": "SaaS"},
            )
        ).json()
        await client.post(
            "/api/v1/prospecting/suppressions",
            headers=SDR_HEADERS,
            json={"scope": "domain", "value": "rivalco.io", "reason": "Competitor"},
        )

        disq_res = await client.post(
            "/api/v1/qualification/evaluate",
            headers=SDR_HEADERS,
            json={"account_id": suppressed_acc["id"]},
        )
        assert disq_res.status_code == 201
        disq = disq_res.json()
        assert disq["icp_score"] == 0
        assert disq["intent_tier"] == "disqualified"
        assert disq["grade"] == "D"

        filtered = await client.get(
            "/api/v1/qualification/records?intent_tier=disqualified",
            headers=SDR_HEADERS,
        )
        assert filtered.status_code == 200
        assert len(filtered.json()) == 1
        assert filtered.json()[0]["id"] == disq["id"]


@pytest.mark.asyncio
async def test_custom_rubric_weights_adjust_icp_score(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        acc = (
            await client.post(
                "/api/v1/prospecting/accounts",
                headers=SDR_HEADERS,
                json={
                    "name": "LeanStart",
                    "domain": "leanstart.io",
                    "industry": "SaaS",
                    "employee_count": 120,
                    "tech_stack": ["Salesforce", "AWS", "Snowflake"],
                },
            )
        ).json()
        eval_res = await client.post(
            "/api/v1/qualification/evaluate",
            headers=SDR_HEADERS,
            json={
                "account_id": acc["id"],
                "rubric_weights": {
                    "company_size": 40,
                    "industry_fit": 40,
                    "tech_stack_fit": 20,
                    "buying_signals": 0,
                    "buyer_authority": 0,
                },
            },
        )
        assert eval_res.status_code == 201
        data = eval_res.json()
        assert data["icp_score"] >= 85
        assert data["grade"] == "A"
