# Contributing to AI SDR

## Development Workflow

1. Create a feature branch from `main`.
2. Keep backend Python 3.12+ typed (`mypy app`) and formatted/linted (`ruff check app tests`).
3. Keep frontend TypeScript strict (`npx tsc --noEmit`) with Vitest coverage (`npm run test`).
4. Verify Docker Compose (`docker compose config -q`) and ensure no `.env`, local SQLite files, or build outputs are committed.

## Verification Checklist

```bash
cd backend && ruff check app tests && mypy app && pytest -v
cd frontend && npx tsc --noEmit && npm run test && npm run build
docker compose config -q
```
