# Security Policy

## Security Baseline

AI SDR ships with the following built-in guardrails:

- **Production Secret Guard:** `APP_ENV=production` enforces overriding `AUTH_SECRET_KEY` (>= 32 bytes) and disallows wildcard `*` in `CORS_ORIGINS`.
- **ASGI Security Headers:** All HTTP responses include `X-Request-ID`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, and HSTS in production.
- **Supply-Chain Hygiene:** GitHub Actions runs `npm audit --omit=dev --audit-level=high` and Trivy filesystem vulnerability/secret scanning alongside GitHub Dependabot alerts.

## Reporting a Vulnerability

Please report security issues privately through GitHub Security Advisories or directly to the repository maintainer before public disclosure.
