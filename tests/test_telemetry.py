import httpx
import respx
from fakes import GEMINI_URL, OLLAMA_URL, gemini_body
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.telemetry import setup_tracing


@respx.mock
def test_request_produces_one_trace_with_expected_spans(client: TestClient) -> None:
    exporter = InMemorySpanExporter()
    setup_tracing("relay-test", None).add_span_processor(SimpleSpanProcessor(exporter))
    respx.post(OLLAMA_URL).mock(return_value=httpx.Response(500))
    respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, json=gemini_body("Hi <PERSON_1>")))

    client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "Greet Jean Dupont"}]},
    )
    spans = exporter.get_finished_spans()
    names = [s.name for s in spans]
    assert names.count("relay.chat_completion") == 1
    for child in ("relay.masking", "relay.routing", "relay.unmasking"):
        assert names.count(child) == 1
    assert names.count("relay.provider_call") == 2  # ollama failed, gemini answered

    root = next(s for s in spans if s.name == "relay.chat_completion")
    assert len({s.context.trace_id for s in spans}) == 1  # all in the same trace
    # Every Relay step is a direct child of the request span. (The request span itself sits
    # under FastAPI's built-in HTTP server span, which also continues incoming traceparents.)
    relay_children = [s for s in spans if s.name.startswith("relay.") and s is not root]
    assert all(
        s.parent is not None and s.parent.span_id == root.context.span_id for s in relay_children
    )
    assert root.attributes is not None
    assert root.attributes["relay.fallback_used"] is True
    assert root.attributes["http.response.status_code"] == 200

    # No content or PII in any attribute of any span.
    for span in spans:
        for value in (span.attributes or {}).values():
            assert "Jean" not in str(value) and "Greet" not in str(value)
