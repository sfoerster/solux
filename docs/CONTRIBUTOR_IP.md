# Contributor IP Policy

This document defines contribution provenance expectations for Solux.

## Goals

1. Preserve clear chain-of-title for all source code.
2. Reduce legal uncertainty in commercial diligence.
3. Prevent accidental inclusion of incompatible third-party code.

## Requirements

1. Contributors must only submit code they wrote or have explicit rights to contribute.
2. Contributors must complete the project contributor IP agreement with the maintainer before first merged contribution.
3. All commits must include a `Signed-off-by:` trailer (DCO style attestation).
4. Third-party code may only be included after license compatibility review and required attribution updates.

Agreement templates:

1. `docs/legal/CLA_TEMPLATE.md` (license grant model)
2. `docs/legal/CAA_TEMPLATE.md` (assignment model)

## Operational Steps

1. Verify `Signed-off-by:` is present on all commits in each merge request.
2. Reject contributions containing copied external code without documented license review.
3. Update `THIRD_PARTY_NOTICES.md` when dependency or bundled-component footprint changes.
