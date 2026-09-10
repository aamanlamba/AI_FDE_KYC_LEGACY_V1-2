# Current Version

- Repository: AI FDE Brownfield KYC Legacy Repository
- Version: 1.0.1-workshop-audited
- Build date: 2026-09-09
- Dataset: 6 synthetic applicant cases / 13 synthetic identity-document images
- Runtime: Python 3.11+; release verification executed on Python 3.13
- API: FastAPI `/v1`
- Offline mode: deterministic sidecar OCR; no external API keys required
- Dependency policy: direct Python dependencies pinned to the release-tested versions
- Automated checks: preflight + deep dataset sanity + 22 pytest tests + live Uvicorn HTTP smoke test + compile check + SHA-256 manifest
- Workshop status: release-audited legacy baseline
