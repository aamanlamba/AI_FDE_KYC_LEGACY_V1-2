# QA / Release Report — Legacy Baseline

Build date: 2026-09-09

## Release-readiness verification performed
- Repository was unpacked into a clean audit workspace before verification.
- Python runtime and all direct dependency versions were checked.
- Application JSON, ground-truth JSON and baseline configuration were parsed and structurally validated.
- Six unique cases and thirteen unique referenced identity documents were verified.
- Every referenced document resolves to exactly one PNG image, OCR sidecar and ground-truth record; orphaned dataset files are rejected by the sanity checker.
- Every PNG image was decoded and verified with Pillow.
- Dates, case/document identifiers, document types and mandatory ground-truth fields were validated.
- Every case flow executes end-to-end.
- Stored expected baseline outputs were compared byte-for-byte at the JSON-object level with fresh service results to detect drift.
- FastAPI live, readiness, case-list, document-verification, case-verification, input-validation, 404 and correlation-ID behavior were exercised.
- A real Uvicorn process was started on an ephemeral localhost port; readiness, Swagger UI, OpenAPI, document verification and case verification were smoke-tested over HTTP.
- Python source, scripts and tests were compiled with `compileall`.
- The release test suite contains 22 tests and was executed successfully during packaging.
- The legacy-content scan checks that future-state repository or target-architecture material has not leaked into the workshop source.
- Generated Python/pytest caches are removed before packaging.
- A SHA-256 release manifest is generated for all packaged files other than the manifest itself.

## Container note
The Dockerfile is included and uses the same pinned dependency set and verified Uvicorn startup command. A Docker/Podman daemon was not available in the packaging execution environment, so an actual container image build could not be executed there. Facilitators using Docker should run the documented `docker build` command once on the target workshop machine during pre-event setup.

## Scope of this QA result
A passing release verification demonstrates that the repository is reproducible and that its **documented legacy behavior** is stable. It does **not** claim that the inherited KYC design satisfies all business, identity-verification, fraud, security, privacy or operational requirements. Those shortcomings are intentionally retained as the brownfield engineering problem.

## Data safety
All records, names, IDs and document images are synthetic. Images visibly state `SYNTHETIC` / `NOT A REAL ID` and do not reproduce real government document templates.
