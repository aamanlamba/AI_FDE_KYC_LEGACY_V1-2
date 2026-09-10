from __future__ import annotations

import importlib
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "fastapi": "0.128.2",
    "uvicorn": "0.48.0",
    "pydantic": "2.13.4",
    "PIL": "12.3.0",
    "httpx": "0.28.1",
    "pytest": "9.0.2",
}


def fail(message: str) -> None:
    print(f"[FAIL] {message}")
    raise SystemExit(1)


print(f"Python: {platform.python_version()} ({sys.executable})")
if sys.version_info < (3, 11):
    fail("Python 3.11 or newer is required for this workshop repository")

mismatches: list[str] = []
for name, expected in REQUIRED.items():
    try:
        module = importlib.import_module(name)
    except Exception as exc:  # import problems should be visible to workshop facilitators
        fail(f"cannot import {name}: {exc}")
    actual = getattr(module, "__version__", None)
    if actual and actual != expected:
        mismatches.append(f"{name}={actual} (release-tested {expected})")

required_paths = [
    ROOT / "data" / "applications",
    ROOT / "data" / "input_documents",
    ROOT / "data" / "sidecar_ocr",
    ROOT / "data" / "ground_truth",
    ROOT / "src" / "app.py",
]
for path in required_paths:
    if not path.exists():
        fail(f"required repository path is missing: {path.relative_to(ROOT)}")

if mismatches:
    print("[WARN] Dependency versions differ from the release-tested set:")
    for item in mismatches:
        print(f"  - {item}")
else:
    print("Dependencies: release-tested versions detected")

print("Repository paths: present")
print("PREFLIGHT PASSED")
