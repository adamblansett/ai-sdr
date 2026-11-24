# AI SDR — Architecture Blueprint

## Overview

Open-source, self-hosted AI Sales Development Representative platform for multi-channel outbound prospecting, lead qualification, personalized sequences, and CRM pipeline hygiene.

## Backend Modules (`backend/app/`)

- `core/` — Typed Pydantic v2 settings (`config.py`), pure ASGI security-header middleware (`middleware.py`), and RBAC + HS256 bearer token authentication (`auth.py`) supporting `viewer`, `sdr`, `sales_manager`, and `admin` roles.
- `db/` & `alembic/` — Async SQLAlchemy 2.0 ORM (`Account`, `AccountSignal`, `Contact`, `SuppressionEntry`, `QualificationRecord`, `OutreachSequence`, `SequenceTouch`, `CrmDeal`, `DuplicateMergeCandidate`, `CrmWebhookEvent`, `ApprovalRequest`, `AuditEvent`) and Alembic migration `0001_initial_schema` portable across SQLite and PostgreSQL.
- `llm/` — `LLMRouter` supporting deterministic offline `mock`, local `ollama`, and guarded cloud `gemini` adapters, preceded by `redact_pii()` scrubbing emails, phone numbers, SSNs, Luhn-valid payment cards, and API/Bearer tokens when `LLM_REDACT_PII_FOR_CLOUD=true`.
- `audit/` — Immutable SHA-256 hash-chained `AuditEvent` ledger (`record_audit_event`, `verify_audit_chain`), HITL `ApprovalRequest` lifecycle (`decide_approval`), and `/api/v1/audit/pii-preview`.
- `prospecting/` — Domain/email normalization, verified public signal tracking, AI account research synthesis, CSV bulk contact import, and immediate email/domain suppression enforcement.
- `qualification/` — Weighted 5-dimension ICP rubric scoring, buying-intent classification, deterministic BANT/MEDDIC extraction, and signal-grounded evidence citations.
- `sequences/` — Fact-grounded multi-touch outbound draft generation with mandatory unsubscribe footers, suppression hard-gates at generation/approval/send time, and manager-gated send dispatch.
- `crm_sync/` — Deal stage hygiene validation, AI next-step synthesis, duplicate contact scanning with HITL opt-out-preserving merges, and idempotent HMAC-verified CRM webhook ingestion (`/api/v1/crm/webhooks/{source}`).
- `seed/` — Idempotent demo dataset loader (`POST /api/v1/seed/demo`).

## API Surface (`/api/v1`)

- **Health & Auth:** `/health`, `/health/live`, `/health/ready`, `/auth/me`, `/auth/dev-token`, `/overview`
- **Prospecting:** `/prospecting/accounts`, `/prospecting/accounts/{id}/signals`, `/prospecting/accounts/{id}/research`, `/prospecting/contacts`, `/prospecting/contacts/import-csv`, `/prospecting/suppressions`
- **Qualification:** `/qualification/records`, `/qualification/evaluate`
- **Sequences:** `/sequences`, `/sequences/generate`, `/sequences/touches/{id}`, `/sequences/touches/{id}/send`
- **CRM Sync:** `/crm/deals`, `/crm/deals/{id}/next-step`, `/crm/hygiene/validate`, `/crm/hygiene/deduplicate`, `/crm/hygiene/duplicates`, `/crm/webhooks`, `/crm/webhooks/{source}`
- **Audit & Seed:** `/audit/approvals`, `/audit/approvals/{id}/decide`, `/audit/events`, `/audit/verify`, `/audit/pii-preview`, `/seed/demo`

## Security & Operational Invariants

1. **Fail-Fast Production Validation:** `validate_production_security()` refuses startup in `APP_ENV=production` if default dev secrets or wildcard CORS origins remain active, and production mode enforces Bearer token authentication (disabling `dev-token` and dev actor headers).
2. **Cloud PII Redaction:** Outbound cloud LLM adapters run `redact_pii()` scrubbing when `LLM_REDACT_PII_FOR_CLOUD=true`.
3. **Human-in-the-Loop Approvals:** Outbound sequence sends (`sequence_touch`) and duplicate contact merges (`crm_merge`) require explicit `sales_manager` or `admin` approval recorded in the SHA-256 hash-chained audit trail; editing an approved touch resets it to `pending_approval`.
4. **Strict Opt-Out Compliance:** Email and domain suppression entries block sequence generation, retroactively halt pending touches/approvals, and are re-verified immediately prior to approval and send dispatch.
5. **Non-Root Containers:** Both the FastAPI API image and Nginx frontend image run as non-root users with `/api/v1/health/live` and `/api/v1/health/ready` probes.
