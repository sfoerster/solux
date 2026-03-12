# Security Policy

## Reporting a Vulnerability

Do not open public issues for suspected vulnerabilities.

Report vulnerabilities privately through your Git hosting provider's private
security reporting channel (or a private maintainer contact) and include:

1. A clear description of the issue and impact.
2. Reproduction steps or a minimal proof of concept.
3. Affected versions/commit hashes.
4. Suggested mitigation, if known.

## Scope

Security-sensitive components include:

1. Web server/auth/webhook endpoints under `src/solus/serve/`.
2. Workflow validation/execution under `src/solus/workflows/`.
3. External module loading under `src/solus/modules/`.
4. Queue/worker state handling under `src/solus/db.py` and `src/solus/worker.py`.

## Hardening Expectations

1. Keep `security.mode = "untrusted"` for untrusted workflows or runtime inputs.
2. Require webhook signatures (`security.webhook_secret`) for internet-exposed webhook endpoints.
3. Require OIDC auth when binding the web server to non-local interfaces.
