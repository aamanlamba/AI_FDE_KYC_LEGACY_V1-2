from pathlib import Path
import sys
import json
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from src.repository import list_cases
from src.service import verify_case
for c in list_cases():
    r=verify_case(c['case_id'])
    print(json.dumps({'case_id':r.case_id,'scenario':c['scenario'],'decision':r.decision,'reason_codes':r.reason_codes},indent=2))
