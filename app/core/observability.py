"""OpenTelemetry bootstrap — Phase 1: traces only.

Wires the SDK, OTLP/gRPC exporter, and auto-instrumentation for the layers
this app actually touches: FastAPI (HTTP edge), SQLAlchemy (DB), Redis (cache),
and the stdlib logging module (so log records carry trace_id/span_id).

No-op when ``settings.OTEL_ENABLED`` is False, so local runs without a
collector pay zero cost.
"""

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from sqlalchemy.engine import Engine

from app.core.config import settings

_initialized = False


def init_observability(app: FastAPI, engine: Engine) -> None:
    """Initialize tracing once at process startup.

    Idempotent — repeated calls are a no-op so reloader-spawned workers don't
    double-instrument the engine and emit duplicated spans.
    """
    global _initialized
    if not settings.OTEL_ENABLED or _initialized:
        return

    resource = Resource.create(
        {
            "service.name": settings.OTEL_SERVICE_NAME,
            "service.version": settings.OTEL_SERVICE_VERSION,
            "deployment.environment": settings.ENVIRONMENT,
        }
    )
    sampler = ParentBased(TraceIdRatioBased(settings.OTEL_TRACES_SAMPLER_ARG))
    provider = TracerProvider(resource=resource, sampler=sampler)
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
                insecure=True,
            )
        )
    )
    trace.set_tracer_provider(provider)

    # /health is a kubelet/loadbalancer probe — high volume, low signal.
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
    SQLAlchemyInstrumentor().instrument(engine=engine)
    RedisInstrumentor().instrument()
    LoggingInstrumentor().instrument()

    _initialized = True
