import os
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
)
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
import requests
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.aiohttp_client import (
    AioHttpClientInstrumentor
)

"""
This file contains initialization code and global vars that are
used throughout the entire integration
"""

def init_otel():
    """Initialize the open telemetry config"""
    resource = Resource(attributes={"service.name": "rise_edr"})
    provider = TracerProvider(resource=resource)
    COLLECTOR_ENDPOINT = "127.0.0.1"
    COLLECTOR_GRPC_PORT = 4317 # jaeger's port to accept OpenTelemetry Protocol (OTLP) over gRPC

    processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=f"http://{COLLECTOR_ENDPOINT}:{COLLECTOR_GRPC_PORT}"))
    provider.add_span_processor(processor)

    # Sets the global default tracer provider
    trace.set_tracer_provider(provider)

    AioHttpClientInstrumentor().instrument()
    print("Initialized open telemetry")

init_otel()
requests.packages.urllib3.util.connection.HAS_IPV6 = False  # type: ignore

TRACER = trace.get_tracer("my.tracer.name")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))