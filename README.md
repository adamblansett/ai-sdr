# AI SDR

> Open-source, self-hosted AI Sales Development Representative platform for multi-channel outbound prospecting, lead qualification, personalized sequences, and CRM pipeline hygiene.

**Roadmap Stage:** Phase 1 — Core Professional & Enterprise Operations · **Status:** Phase 1 Implemented

## Implemented Core Capabilities

- **Outbound Prospecting (`backend/app/prospecting/`):** Target account enrichment, verified public buying signals, AI account research briefs, bulk CSV contact import, and strict email/domain opt-out suppression enforcement that retroactively blocks unsent sequence touches.
- **Lead Qualification (`backend/app/qualification/`):** Customizable 5-dimension ICP rubric scoring, buying-intent tiering (`high`/`medium`/`low`/`disqualified`), grade assignment (`A`–`D`), structured BANT & MEDDIC extraction, and cited public signal evidence.
- **Personalized Sequences & HITL Approvals (`backend/app/sequences/`):** Signal-grounded multi-touch drafts with mandatory unsubscribe footers, edit-resets-approval safeguards, post-approval opt-out re-checks before sending, and manager-gated send execution.
- **CRM Pipeline Hygiene (`backend/app/crm_sync/`):** Stage hygiene scoring (stale activity, past close dates, missing next steps, suppressed primary contacts, late-stage qualification checks), duplicate contact detection with atomic HITL merge execution, AI next-step synthesis, and idempotent HMAC-verified CRM webhooks.
- **Guardrails, Auth & Audit (`backend/app/llm/`, `backend/app/audit/`, `backend/app/core/auth.py`):** Local-first LLM routing (`mock`, `ollama`, `gemini` fallback chain) with outbound cloud PII/PCI/secret scrubbing (`LLM_REDACT_PII_FOR_CLOUD=true`), RBAC (`viewer`, `sdr`, `sales_manager`, `admin`) with HS256 bearer tokens, and an immutable SHA-256 hash-chained audit trail.
- **Multi-Tab Operations Workspace (`frontend/src/`):** React 18 + TypeScript + Tailwind UI covering Overview KPIs, Prospecting & Suppression, Lead Qualification, Sequences & Approvals, CRM Hygiene, and Audit & PII Guardrails.

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

Optional: set `SEED_DEMO_DATA=true` on startup or click **Load Demo Dataset** in the UI (`POST /api/v1/seed/demo`) to populate sample accounts, signals, suppression entries, qualifications, a 3-touch sequence, CRM deals, and a duplicate merge candidate.

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

---

## License

Licensed under the [MIT License](LICENSE).
