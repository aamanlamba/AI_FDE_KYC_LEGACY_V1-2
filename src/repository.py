from pathlib import Path
import json

from .security.identifiers import validate_identifier

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'

# Resource bound: this repository's largest legitimate fixture file is a few KB of
# text/JSON. A file far beyond that is either corrupted or hostile; refuse to read it
# into memory rather than trusting file size implicitly.
MAX_FILE_BYTES=1_000_000

def safe_id(value: str) -> str:
    return validate_identifier(value, label='identifier')

def _read_bounded(path: Path) -> str:
    size=path.stat().st_size
    if size>MAX_FILE_BYTES:
        raise ValueError(f'refusing to read {path.name}: {size} bytes exceeds the {MAX_FILE_BYTES}-byte bound')
    return path.read_text(encoding='utf-8')

def load_json(folder: str, ident: str) -> dict:
    ident=safe_id(ident)
    path=DATA/folder/f'{ident}.json'
    if not path.exists():
        raise FileNotFoundError(ident)
    return json.loads(_read_bounded(path))

def load_application(case_id: str) -> dict:
    return load_json('applications',case_id)

def load_ground_truth(document_id: str) -> dict:
    return load_json('ground_truth',document_id)

def load_sidecar(document_id: str) -> str:
    document_id=safe_id(document_id)
    path=DATA/'sidecar_ocr'/f'{document_id}.txt'
    if not path.exists(): raise FileNotFoundError(document_id)
    return _read_bounded(path)

def list_cases() -> list[dict]:
    out=[]
    for p in sorted((DATA/'applications').glob('*.json')):
        out.append(json.loads(p.read_text(encoding='utf-8')))
    return out
