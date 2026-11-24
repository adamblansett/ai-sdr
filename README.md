# AI SDR

> Open-source, self-hosted AI Sales Development Representative platform for multi-channel outbound prospecting, lead qualification, personalized sequences, and CRM pipeline hygiene.

**Roadmap Stage:** Phase 1 — Core Professional & Enterprise Operations · **Status:** Initialized Starter Scaffold

## Planned Core Capabilities

- **Outbound Prospecting:** Account research synthesis from public signals with strict opt-out and compliance checks.
- **Lead Qualification:** Structured ICP scoring, buying-intent classification, and BANT/MEDDIC field extraction.
- **Personalized Sequences:** Human-approved multi-touch email and follow-up drafts grounded in verified account facts.
- **CRM Pipeline Hygiene:** Automated contact deduplication, stage validation, and next-step summarization.

## Architecture & Engineering Standards

- **Backend (`backend/`):** Python 3.12+, FastAPI, Pydantic v2, typed settings with production fail-fast validation, pure ASGI security-header middleware, and versioned `/api/v1/health` probes.
- **Frontend (`frontend/`):** React 18, TypeScript, Vite, Tailwind CSS, and Vitest + Testing Library unit tests served behind unprivileged Nginx in production.
- **Privacy & AI Guardrails:** Offline deterministic `mock` mode for CI/dev, local-first open-weights Ollama support, and cloud PII-redaction switches enabled by default.
- **Containers & CI (`.github/workflows/ci.yml`):** Multi-stage Dockerfiles, PostgreSQL (`pgvector`) + Redis Compose topology, Ruff + Mypy + Pytest checks, TypeScript + Vitest + Vite build, `npm audit`, and Trivy filesystem scanning.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the domain module plan.

## Quickstart

### Backend (Local Dev & Tests)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

Verify lint, types, and tests:

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
