from .repository import load_sidecar

def extract_text(document_id: str) -> str:
    """Brownfield OCR seam: deterministic sidecar replaces external OCR dependency."""
    return load_sidecar(document_id)
