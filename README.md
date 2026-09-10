# AI FDE Brownfield KYC — Legacy Repo 1.0

A self-contained, synthetic, offline-friendly **legacy identity-document verification service** for AI Forward Deployed Engineer training.

## Purpose
This repository represents the **current system inherited by an engineering team**. It works, has users and operational dependencies, but has accumulated technical debt, brittle document handling and verification gaps. Participants are expected to inspect the system, reproduce its behavior, identify defects and constraints, and determine what intervention is required.

All identities, document numbers, images and cases are synthetic. No real government document artwork, logos, QR codes, barcodes or identities are used.

## Current capabilities
- FastAPI service with `/v1` endpoints
- Deterministic offline OCR sidecars
- Regex / line-prefix document parsing
- Baseline validation rules
- Document-level APPROVE / REVIEW / REJECT outcomes
- Case-level aggregation
- Health and readiness endpoints
- Correlation IDs and basic structured logging
- Docker packaging
- Synthetic application, image, OCR and ground-truth datasets
- Automated tests and sanity checks

## Included problem scenarios
- Clean passport, national-ID and driving-licence documents
- Noisy / degraded scan
- Rotated document
- Expired passport
- Name variation + deliberate OCR corruption
- Suspected tampering indicator
- Multiple documents belonging to the same applicant

## Quick start
### Option A — Python
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/workshop_preflight.py
python -m uvicorn src.app:app --host 0.0.0.0 --port 8000
```

Open `http://127.0.0.1:8000/docs`.

### Option B — Docker
```bash
docker build -t ai-fde-kyc-v1 .
docker run --rm -p 8000:8000 ai-fde-kyc-v1
```

## Example API calls
List cases:
```bash
curl http://127.0.0.1:8000/v1/cases
```

Verify one synthetic document:
```bash
curl -X POST http://127.0.0.1:8000/v1/documents/verify \
  -H "Content-Type: application/json" \
  -d '{"document_id":"CASE-001-PASSPORT"}'
```

Verify one applicant case:
```bash
curl -X POST http://127.0.0.1:8000/v1/cases/CASE-005/verify
```

Open a human review for a case whose decision is REVIEW (stage P6; see
`docs/data_dictionary.md` for the full review-workflow contract). As of stage P8 this
requires an authenticated reviewer credential (workshop default shown below; see
`docs/security/threat_model.md`):
```bash
curl -X POST http://127.0.0.1:8000/v1/cases/CASE-005/reviews \
  -H "X-API-Key: workshop-reviewer-key"
```

## Run checks
```bash
python scripts/workshop_preflight.py
python scripts/sanity_check.py
python -m pytest -q
python scripts/smoke_server.py
python scripts/run_evaluation.py
```
CI also runs lint (`ruff`) and security checks (`pip check`, `pip-audit`) — install
`requirements-dev.txt` locally to run those yourself: `ruff check src/ tests/ eval/
scripts/` and `pip-audit -r requirements.txt`. These are CI-only tooling, never
installed in the runtime Docker image.
`run_evaluation.py` is the AI evals / decision-quality harness (stage P7) — it is
independent of the pytest regression suite above, measures document-intelligence,
identity-resolution, decisioning and operational quality against a curated evaluation
case set, writes a machine-readable report to `var/eval/report.json`, and exits
non-zero if a release gate fails. See `docs/data_dictionary.md` for the full contract.

## Observability (stage P9)
Structured JSON logs, a nested trace span per pipeline stage, and `GET /metrics`
(Prometheus-text-compatible) are built in — see `docs/operations/runbook.md` for exact
commands to reconstruct what happened and why for any case, and
`docs/operations/slis_slos.md` for SLI definitions and proposed SLOs.

## Architecture (stage P10)
`docs/architecture/overview.md` documents module boundaries, the provider inventory,
dependency rules (checked by an automated import-graph test, not just described), and
concurrency findings. `docs/architecture/adr/` records the reasoning behind the most
consequential design decisions across every stage. `docs/operations/deployment.md`
covers environment variables, Docker, and process lifecycle.

See `WORKSHOP_RUNBOOK.md` for Windows, Linux/macOS, Docker and troubleshooting instructions.

## Suggested investigation order
1. `docs/business_problem_statement.md`
2. `docs/system_context.md`
3. `docs/scenario_catalog.md`
4. `docs/data_dictionary.md`
5. `docs/known_limitations.md`
6. `docs/operational_incidents.md`
7. `docs/engineering_challenge_register.md`
8. `tests/`
9. `src/`

## Training constraint
Treat this as a real brownfield handover. Do not assume the existing design is correct simply because its regression tests pass. Some tests intentionally preserve current behavior rather than proving that the behavior is sufficient for the business problem.
