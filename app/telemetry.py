"""OpenTelemetry tracing setup.

Each chat request produces one trace:
    relay.chat_completion            (root: team, policy, provider, status)
      relay.masking                  (how many entities were masked)
      relay.routing                  (policy, sensitivity, candidate order)
      relay.provider_call            (one span per attempt: provider, model, outcome, tokens)
      relay.unmasking

Like the usage log, spans carry metadata only: no prompt, completion or PII ever goes into a
span attribute, because traces are shipped to a third-party backend and kept for weeks.

Spans are sent over OTLP/HTTP to an OpenTelemetry Collector, which forwards them to whatever
backend is configured there (Tempo, Jaeger, a SaaS...). Without an endpoint, tracing still
works in-process (useful for tests) but nothing is exported.
"""

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Module-level tracer: it delegates to whatever provider setup_tracing() installs.
tracer = trace.get_tracer("relay")

_provider: TracerProvider | None = None


def setup_tracing(service_name: str, otlp_endpoint: str | None) -> TracerProvider:
    """Install the global tracer provider (once per process; later calls reuse it)."""
    global _provider
    if _provider is None:
        _provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
        if otlp_endpoint:
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint.rstrip("/") + "/v1/traces")
            # Batching: spans are exported in the background, never on the request path.
            _provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(_provider)
    return _provider
