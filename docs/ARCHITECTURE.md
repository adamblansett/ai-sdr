# AI SDR — Architecture Blueprint

## Overview

Open-source, self-hosted AI Sales Development Representative platform for multi-channel outbound prospecting, lead qualification, personalized sequences, and CRM pipeline hygiene.

This starter repository establishes the production baseline (typed configuration, security headers, health endpoints, CI checks, and Docker Compose topology) so domain features can be implemented cleanly without re-scaffolding infrastructure.

## Planned Domain Modules (`backend/app/`)

- `prospecting/` — Account enrichment, signal scoring, and suppression-list enforcement
- `qualification/` — Rubric-driven lead grading with cited evidence snippets
- `sequences/` — Multi-step draft composer with mandatory human send approval
- `crm_sync/` — Idempotent CRM webhook & pipeline hygiene reconciliation workers

## Security & Operational Invariants

1. **Fail-Fast Production Validation:** `validate_production_security()` refuses startup in `APP_ENV=production` if default dev secrets or wildcard CORS origins remain active.
2. **Cloud PII Redaction:** Outbound cloud LLM adapters run PII scrubbing when `LLM_REDACT_PII_FOR_CLOUD=true`.
3. **Human-in-the-Loop Approvals:** High-impact external writes (emails, accounting entries, identity changes, record merges) require explicit review states and immutable audit trails.
4. **Non-Root Containers:** Both the FastAPI API image and Nginx frontend image run as non-root users with `/api/v1/health/live` and `/api/v1/health/ready` probes.
