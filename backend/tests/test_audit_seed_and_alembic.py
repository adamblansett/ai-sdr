import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text

from alembic import command
from tests.conftest import MANAGER_HEADERS, SDR_HEADERS, app_client


@pytest.mark.asyncio
async def test_audit_hash_chain_verify_and_tamper_detection(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (test_app, client):
        seed_res = await client.post("/api/v1/seed/demo", headers=MANAGER_HEADERS)
        assert seed_res.status_code == 200
        assert seed_res.json()["seeded"] is True

        verify_ok = await client.get("/api/v1/audit/verify", headers=MANAGER_HEADERS)
        assert verify_ok.status_code == 200
        vdata = verify_ok.json()
        assert vdata["valid"] is True
        assert vdata["total_events"] >= 5

        async with test_app.state.session_factory() as session:
            await session.execute(
                text("UPDATE audit_events SET action = 'tampered_action' WHERE sequence_no = 2")
            )
            await session.commit()

        verify_tampered = await client.get("/api/v1/audit/verify", headers=MANAGER_HEADERS)
        assert verify_tampered.status_code == 200
        tdata = verify_tampered.json()
        assert tdata["valid"] is False
        assert tdata["broken_sequence_no"] == 2
        assert "tamper" in tdata["message"].lower()


@pytest.mark.asyncio
async def test_demo_seed_idempotent_and_reset(tmp_path: Path) -> None:
    async with app_client(tmp_path) as (_, client):
        sdr_attempt = await client.post("/api/v1/seed/demo", headers=SDR_HEADERS)
        assert sdr_attempt.status_code == 403

        first = await client.post("/api/v1/seed/demo", headers=MANAGER_HEADERS)
        assert first.status_code == 200
        assert first.json()["seeded"] is True

        second = await client.post("/api/v1/seed/demo", headers=MANAGER_HEADERS)
        assert second.status_code == 200
        assert second.json()["seeded"] is False

        overview = (await client.get("/api/v1/overview", headers=MANAGER_HEADERS)).json()
        assert overview["accounts_total"] == 4
        assert overview["suppressed_accounts"] == 1
        assert overview["signals_total"] == 7
        assert overview["qualifications_total"] == 2
        assert overview["touches_pending_approval"] == 3
        assert overview["deals_open"] == 3
        assert overview["pending_merges"] == 1
        assert overview["pending_approvals"] == 4

        reset_res = await client.post("/api/v1/seed/demo?reset=true", headers=MANAGER_HEADERS)
        assert reset_res.status_code == 200
        assert reset_res.json()["seeded"] is True

        verify_after_reset = (
            await client.get("/api/v1/audit/verify", headers=MANAGER_HEADERS)
        ).json()
        assert verify_after_reset["valid"] is True


def test_alembic_upgrade_head_creates_all_12_tables(tmp_path: Path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "alembic_migrated.db"
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")

    command.upgrade(alembic_cfg, "head")

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    expected = {
        "accounts",
        "account_signals",
        "contacts",
        "suppression_entries",
        "qualification_records",
        "outreach_sequences",
        "sequence_touches",
        "crm_deals",
        "duplicate_merge_candidates",
        "crm_webhook_events",
        "approval_requests",
        "audit_events",
        "alembic_version",
    }
    assert expected.issubset(tables)
