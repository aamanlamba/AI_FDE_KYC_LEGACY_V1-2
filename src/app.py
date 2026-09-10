import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Header, Path, Request, Response
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
    get_default_authorizer,
    review_transition_idempotency_cache,
    review_transition_rate_limiter,
)
from .observability import bind_trace_context, configure_logging, start_span
from .observability import metrics as obs_metrics

# Bounded, allowlist-pattern path parameter -- rejects oversized/malformed identifiers
# (422) before any handler code or file I/O runs (P8 requirement 2: input validation
# and resource bounds at the boundary, not just deep in the call stack).
def _identifier_path(description: str):
    return Path(min_length=1, max_length=MAX_IDENTIFIER_LENGTH, pattern=IDENTIFIER_PATTERN_STR, description=description)

configure_logging(level=os.getenv('LOG_LEVEL','INFO'))
log=logging.getLogger('kyc-v1')

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup: fail fast and loudly if a core dependency is broken, rather than
    # accepting traffic and 500ing on the first request (P10 requirement 10:
    # graceful startup/shutdown).
    dataset_cases=len(list_cases())
    get_default_review_store()  # eagerly opens the SQLite connection and runs schema migration
    log.info('startup',extra={'event':'startup','count':dataset_cases})
    try:
        yield
    finally:
        # Shutdown: close the review store's SQLite connection cleanly instead of
        # relying on process exit / garbage collection to do it implicitly.
        get_default_review_store().close()
        log.info('shutdown',extra={'event':'shutdown'})

app=FastAPI(title='AI FDE Brownfield KYC Repo 1.0',version='1.0.0',description='Synthetic training service; not for real identity decisions.',lifespan=lifespan)

@app.middleware('http')
async def correlation(request: Request, call_next):
    cid=request.headers.get('x-correlation-id') or str(uuid.uuid4())
    start=time.perf_counter()
    # One trace/correlation context bound for the whole request -- every span opened
    # anywhere in src.service/src.document_intelligence/src.identity_resolution/
    # src.evidence_validation/src.fraud_signals/src.decision_policy/src.review during
    # this request nests under the root 'http.request' span below (P9 requirement 1).
    with bind_trace_context(correlation_id=cid):
        with start_span('http.request',http_method=request.method,http_path=request.url.path) as span:
            response=await call_next(request)
            span.attributes['http_status']=response.status_code
        response.headers['x-correlation-id']=cid
        response.headers['x-trace-id']=cid
        latency_ms=(time.perf_counter()-start)*1000
        obs_metrics.request_count.inc(path=request.url.path,method=request.method)
        obs_metrics.request_latency_ms.observe(latency_ms)
        if response.status_code>=400:
            obs_metrics.error_count.inc(path=request.url.path,status=str(response.status_code))
        log.info('request',extra={'event':'http_request','path':request.url.path,'method':request.method,
            'http_status':response.status_code,'latency_ms':round(latency_ms,3)})
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
    obs_metrics.error_count.inc(path=request.url.path,status='500')
    log.exception('unhandled_exception',extra={'event':'unhandled_exception','path':request.url.path,
        'error_type':type(exc).__name__})
    return JSONResponse(status_code=500,content={'detail':'internal error','correlation_id':cid})

@app.get('/health/live')
def live(): return {'status':'ok'}

@app.get('/health/ready')
def ready():
    # Readiness that actually verifies its dependencies, not just "the process is up":
    # the dataset is readable with the expected shape, the review store's SQLite
    # connection responds, and at least one reviewer credential is configured (if not,
    # every /v1/reviews* endpoint would be permanently inaccessible -- worth surfacing
    # here rather than discovering it only when a reviewer's first request 401s).
    checks={}
    try:
        dataset_cases=len(list_cases())
        checks['dataset']='ok' if dataset_cases>0 else 'degraded: no cases found'
    except Exception as exc:
        dataset_cases=0
        checks['dataset']=f'error: {type(exc).__name__}'
    try:
        get_default_review_store().list_reviews()
        checks['review_store']='ok'
    except Exception as exc:
        checks['review_store']=f'error: {type(exc).__name__}'
    try:
        checks['auth_config']='ok' if get_default_authorizer().is_configured() else 'degraded: no reviewer credentials configured'
    except Exception as exc:
        checks['auth_config']=f'error: {type(exc).__name__}'
    overall='ready' if all(v=='ok' for v in checks.values()) else 'degraded'
    return {'status':overall,'offline_ocr':True,'dataset_cases':dataset_cases,'checks':checks}

@app.get('/metrics')
def metrics_endpoint():
    return Response(content=obs_metrics.registry.render_prometheus_text(),media_type='text/plain; version=0.0.4')

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
                       idempotency_key: str | None = Header(default=None,alias='Idempotency-Key'),
                       store: ReviewStore = Depends(review_store_dependency),
                       principal: AuthPrincipal = Depends(require_reviewer)):
    review_transition_rate_limiter.check(principal.subject)
    # A retried request with the same Idempotency-Key (e.g. after a client-side
    # timeout, unsure whether the first attempt landed) returns the original result
    # rather than re-attempting the transition, which could otherwise 409 on a retry
    # of an already-successful request (P10 requirement 10: idempotency).
    # get_or_compute holds one lock across the whole check-compute-store sequence so
    # concurrent retries of the same key can never race each other into the store
    # (P11 red-team finding: separate get()/put() calls left a window where a
    # concurrent retry could 409 instead of returning the cached success).
    def compute():
        return store.apply_transition(review_id,req.new_status,req.analyst_action,req.rationale,req.correction)
    cache_key=f'{review_id}:{idempotency_key}' if idempotency_key else None
    if cache_key:
        return review_transition_idempotency_cache.get_or_compute(cache_key,compute)
    return compute()
