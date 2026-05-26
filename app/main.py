from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from app.core.config import settings
from app.core.database import engine
from app.core.observability import init_observability
from app.graphql.apq.middleware import GraphQLAPQMiddleware
from app.graphql.router import graphql_router


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """Reject requests whose body exceeds settings.MAX_REQUEST_BYTES.

    First-line DoS shield — kills oversized payloads before JSON parse or
    GraphQL lex/validate. Only enforced when Content-Length is present.
    """

    async def dispatch(self, request, call_next):
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > settings.MAX_REQUEST_BYTES:
                    return JSONResponse(
                        {"detail": "Request body too large"}, status_code=413
                    )
            except ValueError:
                pass
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="GraphQL API for the Tonic platform",
    lifespan=lifespan,
    docs_url=None,   # No REST endpoints — GraphiQL playground at /graphql instead
    redoc_url=None,
)

# OTel auto-instrumentation must run after `app` exists but before middleware
# is added — FastAPIInstrumentor inserts its own ASGI middleware and we want it
# at the outermost layer so spans cover gzip/CORS/body-size work too.
init_observability(app, engine)

# Middleware order: outermost runs first. Registration is reverse: last add = outermost.
# APQ middleware sits inside GZip so it sees uncompressed bodies; outside the
# GraphQL router so it can intercept before Strawberry's HTTP view rejects
# query-less requests.
app.add_middleware(GraphQLAPQMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(origin).strip("/") for origin in settings.BACKEND_CORS_ORIGINS],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:[0-9]+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)
app.add_middleware(MaxBodySizeMiddleware)

app.include_router(graphql_router, prefix="/graphql")


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.PROJECT_NAME}
