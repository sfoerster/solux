# Third-Party Notices

This product includes third-party software components. Their licenses remain with their respective authors.

## Python Runtime Dependencies (Core)

These are declared in `pyproject.toml` under `[project].dependencies`.

| Package | Purpose | License |
|---|---|---|
| `requests` | HTTP client | Apache-2.0 |
| `PyYAML` | YAML parsing | MIT |
| `defusedxml` | Safe XML parsing hardening | PSF License |

## Python Optional Dependencies

Optional extras are not always installed. If an extra is included in a distribution, include the corresponding upstream license text for every installed package in that extra.

Extras currently defined in `pyproject.toml`:

- `dev`
- `pdf`
- `ocr`
- `s3`
- `vector`
- `oidc`

## System/Container Components

Container builds may include additional system-level software with separate licensing terms.

- `ffmpeg` (installed in `Dockerfile`)
- `yt-dlp` (installed in `Dockerfile`)

When distributing container images or binaries, include third-party notices/license texts required by those components and by the base image.

## Release Compliance Checklist

1. Generate an SBOM for the exact artifact to be shipped.
2. Capture exact package versions (Python + system packages).
3. Include all required license texts/notices in the shipped artifact.
4. Run legal review before commercial distribution.

Helpful command for declared Python dependency license metadata:

```bash
python dev/third_party_inventory.py
```

Release CI enforcement:

- CI generates compliance artifacts (`sbom.cdx.json`, `license-report.md`) on tagged releases.
- The pipeline fails when denied license patterns are detected by `dev/check_licenses.py`.
