# AI SDR — Architecture Blueprint

## Overview

Open-source, self-hosted AI Sales Development Representative platform for multi-channel outbound prospecting, lead qualification, personalized sequences, and CRM pipeline hygiene.

## Backend Modules (`backend/app/`)

- `core/` — Typed Pydantic v2 settings (`config.py`), pure ASGI security-header + correlation-log middleware (`middleware.py`), Redis/in-memory sliding-window rate limiter (`rate_limit.py`), exponential backoff + jitter retries (`resilience.py`), Prometheus + OpenTelemetry hooks (`telemetry.py`), and `scrypt` password hashing + HS256 JWT / RBAC (`auth.py`).
- `db/` & `alembic/` — Async SQLAlchemy 2.0 ORM (17 models including `User`, `InboundReply`, `KnowledgeChunk`, `CrmSyncJob`, `BackgroundJob`), tuned connection pooling, and reversible Alembic migrations `0001_initial_schema` -> `0002_phase2_schema`.
- `llm/` — `LLMRouter` supporting deterministic offline `mock`, local `ollama`, and guarded cloud `gemini` adapters, preceded by `redact_pii()` scrubbing emails, phone numbers, SSNs, Luhn-valid payment cards, and API/Bearer tokens when `LLM_REDACT_PII_FOR_CLOUD=true`.
- `retrieval/` — Local-first dense vector embeddings (`deterministic` hashing or `ollama`) and cosine-similarity search across `KnowledgeChunk` records, automatically indexing verified account signals and grounding qualification + sequence drafts.
- `audit/` — Immutable SHA-256 hash-chained `AuditEvent` ledger (`record_audit_event`, `verify_audit_chain`), HITL `ApprovalRequest` lifecycle (`decide_approval`), and `/api/v1/audit/pii-preview`.
- `prospecting/` — Modularized into `service.py` (enrichment, research, bulk-batched `contacts_to_out`, CSV import) and `suppression.py` (email/domain opt-out enforcement & retroactive touch blocking).
- `qualification/` — Weighted 5-dimension ICP rubric scoring, buying-intent classification, deterministic BANT/MEDDIC extraction, and signal + semantic evidence citations.
- `sequences/` — Fact-grounded multi-touch draft generation (`composer.py`), pluggable email delivery (`delivery.py`: `mock`, `smtp`, `resend`, `sendgrid`), and automated inbound reply classification (`replies.py`).
- `crm_sync/` — Split across `hygiene.py` (stage hygiene & HITL duplicate merges), `webhooks.py` (idempotent HMAC-verified inbound webhooks), and `connectors.py` (idempotent outbound HubSpot/Salesforce/mock sync).
- `workers/` — Celery (`celery_app.py`) + inline execution (`tasks.py`) for `crm_hygiene_sweep` and `sequence_followup_sweep`.
- `seed/` — Idempotent demo dataset loader (`POST /api/v1/seed/demo`).

## API Surface (`/api/v1`)

- **Health, Auth & Metrics:** `/health`, `/health/live`, `/health/ready`, `/auth/me`, `/auth/dev-token`, `/auth/register`, `/auth/login`, `/auth/users`, `/overview`, `/metrics`, `/metrics/prometheus`
- **Prospecting & Retrieval:** `/prospecting/accounts`, `/prospecting/accounts/{id}/signals`, `/prospecting/accounts/{id}/research`, `/prospecting/contacts`, `/prospecting/contacts/import-csv`, `/prospecting/suppressions`, `/retrieval/documents`, `/retrieval/search`
- **Qualification:** `/qualification/records`, `/qualification/evaluate`
- **Sequences & Replies:** `/sequences`, `/sequences/generate`, `/sequences/touches/{id}`, `/sequences/touches/{id}/send`, `/sequences/replies`, `/sequences/replies/inbound`
- **CRM Sync & Workers:** `/crm/deals`, `/crm/deals/{id}/next-step`, `/crm/hygiene/validate`, `/crm/hygiene/deduplicate`, `/crm/hygiene/duplicates`, `/crm/webhooks`, `/crm/webhooks/{source}`, `/crm/sync/jobs`, `/crm/sync/push`, `/workers/jobs`, `/workers/jobs/{job_type}/run`
- **Audit & Seed:** `/audit/approvals`, `/audit/approvals/{id}/decide`, `/audit/events`, `/audit/verify`, `/audit/pii-preview`, `/seed/demo`

## Security & Operational Invariants

1. **Fail-Fast Production Validation:** `validate_production_security()` refuses startup in `APP_ENV=production` if default dev secrets or wildcard CORS origins remain active, and production mode enforces Bearer token authentication (disabling `dev-token` and dev actor headers).
2. **Cloud PII Redaction:** Outbound cloud LLM adapters run `redact_pii()` scrubbing when `LLM_REDACT_PII_FOR_CLOUD=true`.
3. **Human-in-the-Loop Approvals:** Outbound sequence sends (`sequence_touch`) and duplicate contact merges (`crm_merge`) require explicit `sales_manager` or `admin` approval recorded in the SHA-256 hash-chained audit trail; editing an approved touch resets it to `pending_approval`.
4. **Strict Opt-Out Compliance:** Email and domain suppression entries (manual, CSV, CRM webhook, or inbound reply classifier) block sequence generation, retroactively halt pending touches/approvals, and are re-verified immediately prior to approval and send dispatch.
5. **Non-Root Hardened Containers & Rate Limiting:** API, Celery worker, and Nginx frontend containers run as non-root users with `.dockerignore` hygiene, `Content-Security-Policy` headers, and Redis-backed sliding-window rate limiting.
