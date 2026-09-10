import logging, os, uuid
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Request
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
from .security import (
    AuthenticationError,
    AuthorizationError,
    AuthPrincipal,
    IDENTIFIER_PATTERN_STR,
    MAX_IDENTIFIER_LENGTH,
    RateLimitExceededError,
    ROLE_REVIEWER,
    authorize,
    review_transition_rate_limiter,
)

# Bounded, allowlist-pattern path parameter -- rejects oversized/malformed identifiers
# (422) before any handler code or file I/O runs (P8 requirement 2: input validation
# and resource bounds at the boundary, not just deep in the call stack).
def _identifier_path(description: str):
    return Path(min_length=1, max_length=MAX_IDENTIFIER_LENGTH, pattern=IDENTIFIER_PATTERN_STR, description=description)

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

@app.exception_handler(AuthenticationError)
async def authentication_error(_request, exc):
    return JSONResponse(status_code=401,content={'detail':'authentication required'},headers={'WWW-Authenticate':'ApiKey'})

@app.exception_handler(AuthorizationError)
async def authorization_error(_request, exc):
    return JSONResponse(status_code=403,content={'detail':'insufficient permissions'})

@app.exception_handler(RateLimitExceededError)
async def rate_limit_error(_request, exc):
    return JSONResponse(status_code=429,content={'detail':'rate limit exceeded'})

# Centralized secure error handling: any exception not matched above (including bugs)
# is logged in full server-side (with the correlation ID a client can quote when
# reporting an issue) but the client only ever sees a generic message -- never a stack
# trace, exception type name, or internal detail that could aid an attacker or leak
# implementation internals.
@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    cid=request.headers.get('x-correlation-id') or 'unknown'
    log.exception('unhandled_exception correlation_id=%s path=%s',cid,request.url.path)
    return JSONResponse(status_code=500,content={'detail':'internal error','correlation_id':cid})

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
def case_verify(case_id: str = _identifier_path('synthetic case identifier')): return verify_case(case_id)

def review_store_dependency() -> ReviewStore:
    return get_default_review_store()

# Review data aggregates identity attributes (names, DOB) and fraud/discrepancy
# findings for human consumption -- every /v1/reviews* and /v1/cases/{id}/reviews
# operation (read and mutate) requires an authenticated 'reviewer' credential.
# /v1/documents/verify and /v1/cases/{id}/verify remain open, consistent with this
# training service's existing scope; extending auth to those is a documented,
# deliberately out-of-scope next step (see docs/security/threat_model.md).
def require_reviewer(x_api_key: str | None = Header(default=None)) -> AuthPrincipal:
    return authorize(x_api_key, ROLE_REVIEWER)

@app.post('/v1/cases/{case_id}/reviews',response_model=ReviewCase,status_code=201)
def open_review(case_id: str = _identifier_path('synthetic case identifier'),
                 store: ReviewStore = Depends(review_store_dependency),
                 _principal: AuthPrincipal = Depends(require_reviewer)):
    case_result = verify_case(case_id)
    return open_review_case(case_result, store)

@app.get('/v1/reviews',response_model=list[ReviewCase])
def list_reviews(status: ReviewStatus | None = None, store: ReviewStore = Depends(review_store_dependency),
                  _principal: AuthPrincipal = Depends(require_reviewer)):
    return store.list_reviews(status)

@app.get('/v1/reviews/{review_id}',response_model=ReviewCase)
def get_review(review_id: str = _identifier_path('review identifier'),
                store: ReviewStore = Depends(review_store_dependency),
                _principal: AuthPrincipal = Depends(require_reviewer)):
    review = store.get_review(review_id)
    if review is None: raise ReviewNotFoundError(review_id)
    return review

@app.get('/v1/reviews/{review_id}/history',response_model=list[ReviewAuditEntry])
def review_history(review_id: str = _identifier_path('review identifier'),
                    store: ReviewStore = Depends(review_store_dependency),
                    _principal: AuthPrincipal = Depends(require_reviewer)):
    if store.get_review(review_id) is None: raise ReviewNotFoundError(review_id)
    return store.get_audit_log(review_id)

@app.post('/v1/reviews/{review_id}/transitions',response_model=ReviewCase)
def transition_review(req: ReviewTransitionRequest,
                       review_id: str = _identifier_path('review identifier'),
                       store: ReviewStore = Depends(review_store_dependency),
                       principal: AuthPrincipal = Depends(require_reviewer)):
    review_transition_rate_limiter.check(principal.subject)
    return store.apply_transition(review_id,req.new_status,req.analyst_action,req.rationale,req.correction)
