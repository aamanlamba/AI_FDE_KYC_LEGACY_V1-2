import logging, os, uuid
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from .models import VerifyDocumentRequest, DocumentResult, CaseResult
from .service import verify_document, verify_case
from .repository import list_cases
from .review import (
    InvalidTransitionError,
    ReviewAuditEntry,
    ReviewCase,
    ReviewNotEligibleError,
    ReviewNotFoundError,
    ReviewStatus,
    ReviewStore,
    ReviewTransitionRequest,
    get_default_review_store,
    open_review_case,
)

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

@app.exception_handler(ReviewNotFoundError)
async def review_not_found(_request, exc):
    return JSONResponse(status_code=404,content={'detail':f'unknown review_id: {exc.args[0]}'})

@app.exception_handler(ReviewNotEligibleError)
async def review_not_eligible(_request, exc):
    return JSONResponse(status_code=409,content={'detail':str(exc)})

@app.exception_handler(InvalidTransitionError)
async def invalid_transition(_request, exc):
    return JSONResponse(status_code=409,content={'detail':str(exc)})

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

def review_store_dependency() -> ReviewStore:
    return get_default_review_store()

@app.post('/v1/cases/{case_id}/reviews',response_model=ReviewCase,status_code=201)
def open_review(case_id: str, store: ReviewStore = Depends(review_store_dependency)):
    case_result = verify_case(case_id)
    return open_review_case(case_result, store)

@app.get('/v1/reviews',response_model=list[ReviewCase])
def list_reviews(status: ReviewStatus | None = None, store: ReviewStore = Depends(review_store_dependency)):
    return store.list_reviews(status)

@app.get('/v1/reviews/{review_id}',response_model=ReviewCase)
def get_review(review_id: str, store: ReviewStore = Depends(review_store_dependency)):
    review = store.get_review(review_id)
    if review is None: raise ReviewNotFoundError(review_id)
    return review

@app.get('/v1/reviews/{review_id}/history',response_model=list[ReviewAuditEntry])
def review_history(review_id: str, store: ReviewStore = Depends(review_store_dependency)):
    if store.get_review(review_id) is None: raise ReviewNotFoundError(review_id)
    return store.get_audit_log(review_id)

@app.post('/v1/reviews/{review_id}/transitions',response_model=ReviewCase)
def transition_review(review_id: str, req: ReviewTransitionRequest, store: ReviewStore = Depends(review_store_dependency)):
    return store.apply_transition(review_id,req.new_status,req.analyst_action,req.rationale,req.correction)
