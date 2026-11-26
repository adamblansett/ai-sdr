# AI SDR

> Open-source, self-hosted AI Sales Development Representative platform for multi-channel outbound prospecting, lead qualification, personalized sequences, and CRM pipeline hygiene.

**Roadmap Stage:** Phase 1 & Phase 2 — Autonomous Operations & Enterprise Hardening · **Status:** Implemented & Audited

## Implemented Capabilities

- **Outbound Prospecting & Semantic Retrieval (`backend/app/prospecting/`, `backend/app/retrieval/`):** Target account enrichment, verified public buying signals indexed with dense vector embeddings (`deterministic` or `ollama`), AI account research briefs, bulk CSV contact import, semantic case-study/playbook search, and immediate email/domain opt-out suppression.
- **Lead Qualification (`backend/app/qualification/`):** Customizable 5-dimension ICP rubric scoring, buying-intent tiering (`high`/`medium`/`low`/`disqualified`), grade assignment (`A`–`D`), deterministic BANT & MEDDIC extraction, and signal + semantic evidence citations.
- **Personalized Sequences, Email Delivery & Inbound Replies (`backend/app/sequences/`):** Grounded multi-touch drafts with mandatory unsubscribe footers, manager-gated send dispatch via pluggable providers (`mock`, `smtp`, `resend`, `sendgrid`), scheduled follow-up timestamps, and automated inbound reply classification (`unsubscribe`, `interested`, `ooo`, `objection`, `neutral`) that auto-suppresses opt-outs.
- **CRM Pipeline Hygiene & Bi-Directional Sync (`backend/app/crm_sync/`):** Deal stage hygiene scoring, duplicate contact detection with opt-out-preserving HITL merges, AI next-step synthesis, idempotent HMAC-verified inbound CRM webhooks, and idempotent outbound CRM sync connectors (`mock`, `hubspot`, `salesforce`).
- **Background Workers & Hardening (`backend/app/workers/`, `backend/app/core/`, `backend/app/audit/`):** Inline or Celery + Redis scheduled sweeps (`crm_hygiene_sweep`, `sequence_followup_sweep`), `scrypt`-hashed persisted user auth (`POST /api/v1/auth/register`, `POST /api/v1/auth/login`), Redis/in-memory rate limiting (`RATE_LIMIT_ENABLED`), OpenTelemetry tracing hooks + Prometheus metrics (`/api/v1/metrics/prometheus`), outbound cloud PII scrubbing, and an immutable SHA-256 hash-chained audit trail.
- **Multi-Tab Operations Workspace (`frontend/src/`):** React 18 + TypeScript + Tailwind UI with JWT sign-in, role switching, semantic evidence search, HITL approval queues, inbound reply simulation, outbound CRM sync, worker sweep triggers, and live metrics.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for module details, API routes, and security invariants.

## Quickstart

### Backend (Local Dev & Tests)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Optional: set `SEED_DEMO_DATA=true` on startup or click **Load Demo Dataset** in the UI (`POST /api/v1/seed/demo`) to populate sample accounts, signals, knowledge chunks, demo users (`manager@acme-sdr.local` / `DemoPassword123!`), qualifications, a 3-touch sequence, CRM deals, a duplicate merge candidate, an inbound reply, a CRM sync job, and a worker run.

Verify lint, static types, and tests:

```bash
ruff check app tests
mypy app
pytest -v
```

### Frontend (Local Dev & Tests)

```bash
cd frontend
npm ci
npm run dev
```

Verify typecheck, unit tests, and production bundle:

```bash
npx tsc --noEmit
npm run test
npm run build
```

### Docker Compose

```bash
docker compose up --build
```

- Frontend UI: `http://localhost:3000`
- Backend API & OpenAPI Docs: `http://localhost:8000/docs`
- Celery Worker: runs automatically as the `worker` service against Redis + PostgreSQL (`pgvector`).

---

## License

Licensed under the [MIT License](LICENSE).
