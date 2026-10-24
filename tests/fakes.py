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
