import hashlib
import json
import uuid
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.auth import Actor
from app.core.config import Settings
from app.core.resilience import async_retry_with_backoff
from app.crm_sync.schemas import CrmSyncJobOut
from app.db.base import utcnow
from app.db.models import (
    Account,
    CrmDeal,
    CrmSyncJob,
    DuplicateMergeCandidate,
    QualificationRecord,
)


def sync_job_to_out(job: CrmSyncJob) -> CrmSyncJobOut:
    """Serialize a CrmSyncJob ORM row."""
    return CrmSyncJobOut(
        id=job.id,
        provider=job.provider,
        operation=job.operation,
        entity_type=job.entity_type,
        entity_id=job.entity_id,
        idempotency_key=job.idempotency_key,
        status=job.status,
        external_record_id=job.external_record_id,
        response_summary=job.response_summary,
        attempts=job.attempts,
        created_by=job.created_by,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


class CrmConnectorService:
    """Outbound CRM sync adapter for mock, HubSpot, and Salesforce REST APIs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def push(
        self,
        *,
        operation: str,
        payload: dict[str, Any],
    ) -> tuple[str, str]:
        """Push outbound sync payload and return (external_record_id, summary)."""
        provider = self.settings.crm_outbound_provider
        if provider == "mock":
            ext_id = f"crm-{uuid.uuid4().hex[:10]}"
            return ext_id, f"Synced {operation} via deterministic mock CRM connector."

        if provider == "hubspot":
            api_key = self.settings.hubspot_api_key.strip()
            if not api_key:
                raise RuntimeError("HUBSPOT_API_KEY is not configured.")

            async def _call_hs() -> str:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(
                        "https://api.hubapi.com/crm/v3/objects/notes",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={"properties": {"hs_note_body": json.dumps(payload)}},
                    )
                    response.raise_for_status()
                    data = response.json()
                    return str(data.get("id") or f"hs-{uuid.uuid4().hex[:10]}")

            ext_id = await async_retry_with_backoff(_call_hs, max_attempts=2)
            return ext_id, f"Synced {operation} to HubSpot ({ext_id})."

        if provider == "salesforce":
            token = self.settings.salesforce_access_token.strip()
            base = self.settings.salesforce_instance_url.strip().rstrip("/")
            if not token or not base:
                raise RuntimeError("Salesforce instance URL and access token are required.")

            async def _call_sf() -> str:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(
                        f"{base}/services/data/v59.0/sobjects/Task",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"Subject": f"AI SDR {operation}", "Description": json.dumps(payload)},
                    )
                    response.raise_for_status()
                    data = response.json()
                    return str(data.get("id") or f"sf-{uuid.uuid4().hex[:10]}")

            ext_id = await async_retry_with_backoff(_call_sf, max_attempts=2)
            return ext_id, f"Synced {operation} to Salesforce ({ext_id})."

        raise RuntimeError(f"Unsupported CRM outbound provider: {provider}")


async def push_crm_sync(
    db: AsyncSession,
    *,
    operation: str,
    entity_id: str,
    settings: Settings,
    actor: Actor,
    connector: CrmConnectorService | None = None,
) -> CrmSyncJob:
    """Idempotently push qualification, deal next step, or approved merge to CRM."""
    clean_op = operation.strip().lower()
    entity_type = ""
    payload: dict[str, Any] = {}

    if clean_op == "qualification_sync":
        qual = await db.get(QualificationRecord, entity_id)
        if qual is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Qualification '{entity_id}' not found.",
            )
        account = await db.get(Account, qual.account_id)
        entity_type = "qualification"
        payload = {
            "account_domain": account.domain if account else "",
            "icp_score": qual.icp_score,
            "intent_tier": qual.intent_tier,
            "grade": qual.grade,
            "bant": qual.bant_json,
        }
    elif clean_op == "deal_next_step_sync":
        deal = await db.get(CrmDeal, entity_id)
        if deal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"CRM deal '{entity_id}' not found.",
            )
        entity_type = "crm_deal"
        payload = {
            "external_id": deal.external_id,
            "name": deal.name,
            "stage": deal.stage,
            "hygiene_score": deal.hygiene_score,
            "next_step": deal.next_step,
        }
    elif clean_op == "contact_merge_sync":
        cand = await db.get(DuplicateMergeCandidate, entity_id)
        if cand is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Merge candidate '{entity_id}' not found.",
            )
        if cand.status != "merged":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Contact merge must be approved and executed before syncing to CRM.",
            )
        entity_type = "duplicate_merge_candidate"
        payload = {
            "primary_contact_id": cand.primary_contact_id,
            "duplicate_contact_id": cand.duplicate_contact_id,
            "match_reason": cand.match_reason,
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Unsupported sync operation. Use qualification_sync, "
                "deal_next_step_sync, or contact_merge_sync."
            ),
        )

    payload_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    provider = settings.crm_outbound_provider
    idem_key = f"{provider}:{clean_op}:{entity_id}:{payload_hash[:12]}"

    existing = (
        await db.execute(select(CrmSyncJob).where(CrmSyncJob.idempotency_key == idem_key))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    service = connector or CrmConnectorService(settings)
    ext_id, summary = await service.push(operation=clean_op, payload=payload)

    now = utcnow()
    job = CrmSyncJob(
        provider=provider,
        operation=clean_op,
        entity_type=entity_type,
        entity_id=entity_id,
        idempotency_key=idem_key,
        status="synced",
        external_record_id=ext_id,
        payload_json=payload,
        response_summary=summary[:300],
        attempts=1,
        created_by=actor.email,
        created_at=now,
        completed_at=now,
    )
    db.add(job)
    await db.flush()

    await record_audit_event(
        db,
        event_type="crm.outbound_synced",
        actor=actor,
        entity_type="crm_sync_job",
        entity_id=job.id,
        action="synced",
        details={
            "provider": provider,
            "operation": clean_op,
            "target_entity_id": entity_id,
            "external_record_id": ext_id,
        },
    )
    await db.commit()
    await db.refresh(job)
    return job
