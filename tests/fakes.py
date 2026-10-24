"""Canned provider responses used by the tests (no real provider is ever called)."""

from typing import Any

ANTHROPIC_URL = "https://api.anthropic.test/v1/messages"
GEMINI_URL = "https://gemini.test/v1beta/models/gemini-2.5-flash:generateContent"
OLLAMA_URL = "http://ollama.test/api/chat"


def anthropic_body(text: str, prompt_tokens: int = 10, completion_tokens: int = 5) -> Any:
    return {
        "id": "msg_1",
        "model": "claude-opus-5-5",
        "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": prompt_tokens, "output_tokens": completion_tokens},
    }


def gemini_body(text: str, prompt_tokens: int = 10, completion_tokens: int = 5) -> Any:
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": completion_tokens,
        },
    }


def ollama_body(text: str, prompt_tokens: int = 10, completion_tokens: int = 5) -> Any:
    return {
        "model": "llama-test",
        "message": {"role": "assistant", "content": text},
        "done_reason": "stop",
        "prompt_eval_count": prompt_tokens,
        "eval_count": completion_tokens,
    }


class FakeAnalyzer:
    """Stands in for Presidio's AnalyzerEngine: "detects" a fixed list of known PII values.

    The real Presidio *anonymizer* still runs, so placeholders, overlaps and unmasking are
    tested for real; only the spaCy-based detection is replaced (it is covered by the
    `presidio` tests and the eval suite).
    """

    KNOWN = {
        "Jean Dupont": "PERSON",
        "Marie Curie": "PERSON",
        "jean.dupont@example.fr": "EMAIL_ADDRESS",
        "06 12 34 56 78": "PHONE_NUMBER",
    }

    def analyze(
        self,
        text: str,
        language: str,
        entities: list[str] | None = None,
        score_threshold: float | None = None,
    ) -> list[Any]:
        from presidio_analyzer import RecognizerResult

        results = []
        for value, entity_type in self.KNOWN.items():
            start = text.find(value)
            while start != -1:
                results.append(RecognizerResult(entity_type, start, start + len(value), 0.9))
                start = text.find(value, start + 1)
        return results
