from __future__ import annotations

from datetime import date
from pathlib import Path
import json
import re
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.observability import bind_trace_context
from src.repository import list_cases, load_ground_truth, load_sidecar
from src.service import verify_case

# decision_lineage.trace_id (P9) is unique per call by design; bind a fixed value so
# the drift check below compares a true regression snapshot rather than failing on an
# intentionally-random field every run. The committed expected_baseline_outputs were
# generated under this same fixed trace_id.
BASELINE_TRACE_ID = "baseline"

EXPECTED_CASES = 6
EXPECTED_DOCUMENTS = 13
APP_REQUIRED = {"case_id", "submitted_name", "submitted_dob", "submitted_address", "document_ids", "scenario"}
GT_REQUIRED = {
    "document_id", "case_id", "document_type", "full_name", "date_of_birth", "document_number",
    "issue_date", "expiry_date", "address", "nationality", "scenario_flags"
}
SUPPORTED_TYPES = {"passport", "national_id", "driving_licence"}
FORBIDDEN_PHRASES = (
    "repo 2.0",
    "repo2.0",
    "target-state architecture",
    "target state architecture",
    "acceptance criteria for 2.0",
)

errors: list[str] = []


def err(message: str) -> None:
    errors.append(message)


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        err(f"invalid JSON {path.relative_to(ROOT)}: {exc}")
        return {}
    if not isinstance(value, dict):
        err(f"expected JSON object in {path.relative_to(ROOT)}")
        return {}
    return value


config_path = ROOT / "config" / "baseline.json"
if not config_path.exists():
    err("missing config/baseline.json")
else:
    config = read_json(config_path)
    if set(config.get("supported_document_types", [])) != SUPPORTED_TYPES:
        err("config supported_document_types does not match the documented dataset types")
    if config.get("offline_ocr_mode") is not True:
        err("baseline config must declare offline_ocr_mode=true for the workshop build")

cases = list_cases()
if len(cases) != EXPECTED_CASES:
    err(f"expected {EXPECTED_CASES} cases, found {len(cases)}")

case_ids: list[str] = []
referenced_docs: list[str] = []
for case in cases:
    missing = APP_REQUIRED - set(case)
    if missing:
        err(f"application {case.get('case_id', '<unknown>')} missing keys: {sorted(missing)}")
        continue
    case_id = case["case_id"]
    case_ids.append(case_id)
    if not re.fullmatch(r"CASE-\d{3}", case_id):
        err(f"invalid case_id format: {case_id}")
    try:
        date.fromisoformat(case["submitted_dob"])
    except Exception:
        err(f"invalid submitted_dob in {case_id}: {case['submitted_dob']}")
    if not isinstance(case["document_ids"], list) or not case["document_ids"]:
        err(f"{case_id} has no document_ids")
        continue

    for doc_id in case["document_ids"]:
        referenced_docs.append(doc_id)
        if not re.fullmatch(r"CASE-\d{3}-(PASSPORT|NID|DL)", doc_id):
            err(f"unexpected document_id format: {doc_id}")

        image_path = ROOT / "data" / "input_documents" / f"{doc_id}.png"
        sidecar_path = ROOT / "data" / "sidecar_ocr" / f"{doc_id}.txt"
        gt_path = ROOT / "data" / "ground_truth" / f"{doc_id}.json"
        for path in (image_path, sidecar_path, gt_path):
            if not path.exists():
                err(f"missing {path.relative_to(ROOT)}")

        if image_path.exists():
            try:
                with Image.open(image_path) as image:
                    image.verify()
                with Image.open(image_path) as image:
                    if image.width < 100 or image.height < 100:
                        err(f"implausibly small image {image_path.name}: {image.size}")
            except Exception as exc:
                err(f"invalid PNG {image_path.name}: {exc}")

        gt = load_ground_truth(doc_id) if gt_path.exists() else {}
        if gt:
            missing_gt = GT_REQUIRED - set(gt)
            if missing_gt:
                err(f"ground truth {doc_id} missing keys: {sorted(missing_gt)}")
            if gt.get("document_id") != doc_id:
                err(f"ground-truth document mismatch {doc_id}")
            if gt.get("case_id") != case_id:
                err(f"ground-truth case mismatch {doc_id}")
            if gt.get("document_type") not in SUPPORTED_TYPES:
                err(f"unsupported ground-truth document_type in {doc_id}: {gt.get('document_type')}")
            for field in ("date_of_birth", "issue_date", "expiry_date"):
                try:
                    date.fromisoformat(gt[field])
                except Exception:
                    err(f"invalid {field} in ground truth {doc_id}: {gt.get(field)}")

        if sidecar_path.exists():
            sidecar = load_sidecar(doc_id)
            if not sidecar.strip():
                err(f"empty OCR sidecar {doc_id}")
            if "DOCUMENT TYPE:" not in sidecar or "DOCUMENT NO:" not in sidecar:
                err(f"sidecar missing core labels {doc_id}")

    try:
        with bind_trace_context(trace_id=BASELINE_TRACE_ID):
            actual = verify_case(case_id).model_dump(mode="json")
    except Exception as exc:
        err(f"case flow failed {case_id}: {exc}")
        continue
    expected_path = ROOT / "data" / "expected_baseline_outputs" / f"{case_id}.json"
    if not expected_path.exists():
        err(f"missing expected baseline output for {case_id}")
    else:
        expected = read_json(expected_path)
        if expected != actual:
            err(f"expected baseline output drift for {case_id}")

if len(set(case_ids)) != len(case_ids):
    err("duplicate case_id detected")
if len(referenced_docs) != EXPECTED_DOCUMENTS:
    err(f"expected {EXPECTED_DOCUMENTS} referenced documents, found {len(referenced_docs)}")
if len(set(referenced_docs)) != len(referenced_docs):
    err("same document_id is referenced more than once")

for folder, suffix in (("input_documents", ".png"), ("sidecar_ocr", ".txt"), ("ground_truth", ".json")):
    found = {p.stem for p in (ROOT / "data" / folder).glob(f"*{suffix}")}
    expected = set(referenced_docs)
    orphaned = found - expected
    missing = expected - found
    if orphaned:
        err(f"orphaned files in data/{folder}: {sorted(orphaned)}")
    if missing:
        err(f"missing files in data/{folder}: {sorted(missing)}")

expected_case_outputs = {p.stem for p in (ROOT / "data" / "expected_baseline_outputs").glob("*.json")}
if expected_case_outputs != set(case_ids):
    err("expected_baseline_outputs case set does not exactly match application case set")

# Prevent accidental leakage of future-state solution material into the legacy exercise.
for path in ROOT.rglob("*"):
    if path.resolve() == Path(__file__).resolve():
        continue
    if not path.is_file() or path.suffix.lower() not in {".md", ".py", ".json", ".txt", ".ini"}:
        continue
    if any(part in {".pytest_cache", "__pycache__", ".venv"} for part in path.parts):
        continue
    try:
        text = path.read_text(encoding="utf-8").lower()
    except UnicodeDecodeError:
        continue
    for phrase in FORBIDDEN_PHRASES:
        if phrase in text:
            err(f"future-state phrase '{phrase}' found in {path.relative_to(ROOT)}")

if errors:
    print("SANITY CHECK FAILED")
    for item in errors:
        print(f"- {item}")
    raise SystemExit(1)

print(
    f"SANITY CHECK PASSED: {len(cases)} cases, {len(referenced_docs)} documents, "
    "images/JSON/sidecars consistent, expected outputs stable, all baseline flows executable"
)
