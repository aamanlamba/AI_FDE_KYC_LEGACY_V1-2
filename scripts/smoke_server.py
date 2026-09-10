from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request(url: str, *, method: str = "GET", body: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=3) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


port = free_port()
base = f"http://127.0.0.1:{port}"
env = os.environ.copy()
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "src.app:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
    cwd=ROOT,
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
)

try:
    deadline = time.time() + 15
    last_error: Exception | None = None
    while time.time() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"server exited early with code {proc.returncode}:\n{output}")
        try:
            status, health = request(base + "/health/ready")
            if status == 200 and health.get("status") == "ready":
                break
        except Exception as exc:
            last_error = exc
            time.sleep(0.2)
    else:
        raise RuntimeError(f"server did not become ready: {last_error}")

    with urllib.request.urlopen(base + "/docs", timeout=3) as response:
        if response.status != 200 or b"Swagger UI" not in response.read():
            raise RuntimeError("Swagger UI did not load correctly")

    status, openapi = request(base + "/openapi.json")
    if status != 200 or "/v1/documents/verify" not in openapi.get("paths", {}):
        raise RuntimeError("OpenAPI contract is missing the document verification endpoint")

    status, cases = request(base + "/v1/cases")
    if status != 200 or len(cases) != 6:
        raise RuntimeError(f"unexpected cases response: status={status} count={len(cases) if isinstance(cases, list) else 'n/a'}")

    status, result = request(
        base + "/v1/documents/verify",
        method="POST",
        body={"document_id": "CASE-001-PASSPORT"},
    )
    if status != 200 or result.get("decision") != "APPROVE":
        raise RuntimeError(f"unexpected document verification response: {result}")

    status, case = request(base + "/v1/cases/CASE-006/verify", method="POST")
    if status != 200 or case.get("decision") != "REJECT":
        raise RuntimeError(f"unexpected case verification response: {case}")

    print(f"SMOKE SERVER PASSED on ephemeral localhost port {port}")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
