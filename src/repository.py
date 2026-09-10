from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'

def safe_id(value: str) -> str:
    if not value or any(x in value for x in ('/','\\','..')):
        raise ValueError('invalid identifier')
    return value

def load_json(folder: str, ident: str) -> dict:
    ident=safe_id(ident)
    path=DATA/folder/f'{ident}.json'
    if not path.exists():
        raise FileNotFoundError(ident)
    return json.loads(path.read_text(encoding='utf-8'))

def load_application(case_id: str) -> dict:
    return load_json('applications',case_id)

def load_ground_truth(document_id: str) -> dict:
    return load_json('ground_truth',document_id)

def load_sidecar(document_id: str) -> str:
    document_id=safe_id(document_id)
    path=DATA/'sidecar_ocr'/f'{document_id}.txt'
    if not path.exists(): raise FileNotFoundError(document_id)
    return path.read_text(encoding='utf-8')

def list_cases() -> list[dict]:
    out=[]
    for p in sorted((DATA/'applications').glob('*.json')):
        out.append(json.loads(p.read_text(encoding='utf-8')))
    return out
