import json
from pathlib import Path

from PIL import Image

from src.observability import bind_trace_context
from src.repository import list_cases
from src.service import verify_case, verify_document

ROOT = Path(__file__).resolve().parents[1]
# decision_lineage.trace_id (P9) is otherwise unique per call by design; binding a
# fixed value here keeps this a true byte-for-byte regression snapshot rather than
# stripping a field out of the comparison. The golden files were generated under this
# same fixed trace_id.
BASELINE_TRACE_ID = "baseline"


def test_every_referenced_document_executes_and_image_decodes():
    for case in list_cases():
        for document_id in case["document_ids"]:
            result = verify_document(document_id)
            assert result.document_id == document_id
            image_path = ROOT / "data" / "input_documents" / f"{document_id}.png"
            with Image.open(image_path) as image:
                image.verify()


def test_expected_case_outputs_are_current_regression_snapshots():
    for case in list_cases():
        case_id = case["case_id"]
        expected = json.loads(
            (ROOT / "data" / "expected_baseline_outputs" / f"{case_id}.json").read_text(encoding="utf-8")
        )
        with bind_trace_context(trace_id=BASELINE_TRACE_ID):
            actual = verify_case(case_id).model_dump(mode="json")
        assert actual == expected
