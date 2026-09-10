# Workshop Runbook — Legacy KYC Service

This repository is designed to be run as an inherited brownfield service during an AI FDE workshop. It contains only synthetic identities and synthetic document images.

## 1. Prerequisites

- Python 3.11, 3.12 or 3.13
- `pip`
- Optional: Docker Desktop / Docker Engine

No API keys, cloud accounts, external databases or model endpoints are required at runtime.

## 2. Five-minute local setup

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts\workshop_preflight.py
pytest -q
python scripts\smoke_server.py
python -m uvicorn src.app:app --host 127.0.0.1 --port 8000
```

If `py -3.11` is unavailable, use `python -m venv .venv` with Python 3.11+.

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/workshop_preflight.py
pytest -q
python scripts/smoke_server.py
python -m uvicorn src.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` after startup.

## 3. Docker setup

```bash
docker build -t ai-fde-kyc-legacy .
docker run --rm -p 8000:8000 ai-fde-kyc-legacy
```

Then open `http://127.0.0.1:8000/docs`.

## 4. Workshop verification commands

Run these before a session:

```bash
python scripts/workshop_preflight.py
python scripts/sanity_check.py
pytest -q
python scripts/smoke_server.py
python scripts/run_evaluation.py
```

Expected result: every command exits with status code `0`. `run_evaluation.py` (stage
P7) also writes a machine-readable evaluation report to `var/eval/report.json` and
exits non-zero if a release gate fails — see `docs/data_dictionary.md`.

## 5. Useful endpoints

- `GET /health/live`
- `GET /health/ready`
- `GET /v1/cases`
- `POST /v1/documents/verify`
- `POST /v1/cases/{case_id}/verify`
- `GET /docs`

Example request body:

```json
{"document_id":"CASE-001-PASSPORT"}
```

## 6. Common workshop setup failures

### `ModuleNotFoundError`
Activate the virtual environment and run:

```bash
python -m pip install -r requirements.txt
```

### Port 8000 is already in use
Use another port:

```bash
python -m uvicorn src.app:app --host 127.0.0.1 --port 8001
```

### PowerShell blocks virtual-environment activation
Either use Command Prompt activation (`.venv\\Scripts\\activate.bat`) or follow your organization's approved PowerShell execution-policy process.

### Browser cannot reach Swagger UI
Confirm `/health/live` responds first. Corporate endpoint controls, proxies or host firewall rules may block local ports even when the application is healthy.

## 7. Data safety

Every identity, number and image in this repository is fabricated for training. Do not replace the synthetic dataset with real identity documents in a classroom environment.
