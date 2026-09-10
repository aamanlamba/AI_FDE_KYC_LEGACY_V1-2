import logging, os, uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from .models import VerifyDocumentRequest, DocumentResult, CaseResult
from .service import verify_document, verify_case
from .repository import list_cases

logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO'),format='%(asctime)s %(levelname)s %(message)s')
log=logging.getLogger('kyc-v1')
app=FastAPI(title='AI FDE Brownfield KYC Repo 1.0',version='1.0.0',description='Synthetic training service; not for real identity decisions.')

@app.middleware('http')
async def correlation(request: Request, call_next):
    cid=request.headers.get('x-correlation-id') or str(uuid.uuid4())
    response=await call_next(request); response.headers['x-correlation-id']=cid
    log.info('request method=%s path=%s status=%s correlation_id=%s',request.method,request.url.path,response.status_code,cid)
    return response

@app.exception_handler(FileNotFoundError)
async def not_found(_request, exc):
    return JSONResponse(status_code=404,content={'detail':f'unknown synthetic identifier: {exc.args[0]}'})

@app.exception_handler(ValueError)
async def bad_identifier(_request, exc):
    return JSONResponse(status_code=400,content={'detail':str(exc)})

@app.get('/health/live')
def live(): return {'status':'ok'}

@app.get('/health/ready')
def ready():
    return {'status':'ready','offline_ocr':True,'dataset_cases':len(list_cases())}

@app.get('/v1/cases')
def cases():
    return [{'case_id':x['case_id'],'scenario':x['scenario'],'document_ids':x['document_ids']} for x in list_cases()]

@app.post('/v1/documents/verify',response_model=DocumentResult)
def document_verify(req: VerifyDocumentRequest): return verify_document(req.document_id)

@app.post('/v1/cases/{case_id}/verify',response_model=CaseResult)
def case_verify(case_id: str): return verify_case(case_id)
