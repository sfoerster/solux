# Contributing to Solus

## Development Setup

1. Use Python 3.11+.
2. Install local + dev dependencies:

```bash
pip install -e '.[dev]'
```

## Required Checks

Run these before opening a merge request:

```bash
ruff format src/ tests/
ruff check src/ tests/
mypy src/solus/
pytest
```

## Merge Request Standards

1. Keep changes scoped and reviewable.
2. Include tests for behavior changes and regressions.
3. Update docs when commands, config, or workflow behavior changes.
4. At least one reviewer approval is required before merge.
5. Do not merge failing CI.

## Contributor IP Terms

1. Contributions must be original work you are authorized to submit.
2. Before a first merged contribution, complete the project's contributor IP agreement with the maintainer.
3. Every commit in a merge request must include a `Signed-off-by:` trailer (Developer Certificate of Origin).
4. Do not submit code copied from third-party sources unless license compatibility and attribution have been reviewed.
5. See `docs/CONTRIBUTOR_IP.md` and templates under `docs/legal/` for the project's CLA/CAA process.

## Security and Secrets

1. Never commit real credentials, API keys, or tokens.
2. Use `${env:VAR_NAME}` in config/workflows for secrets.
3. Follow `SECURITY.md` for vulnerability reporting.
