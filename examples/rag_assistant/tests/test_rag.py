import json
import sys
from pathlib import Path

import httpx
import pytest
import respx
from relay_client import RelayClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rag  # noqa: E402


@pytest.fixture(scope="module")
def index() -> rag.BM25:
    return rag.BM25(rag.load_chunks())


def test_docs_are_split_into_sections() -> None:
    chunks = rag.load_chunks()
    assert len(chunks) == 12  # 4 documents x 3 sections
    assert {c.source for c in chunks} == {
        "expenses.md",
        "onboarding.md",
        "remote_work.md",
        "security.md",
    }


@pytest.mark.parametrize(
    "question, expected_source, expected_title",
    [
        (
            "How many days do I have to submit an expense receipt?",
            "expenses.md",
            "How to submit an expense",
        ),
        ("Can I work from another country?", "remote_work.md", "Working from abroad"),
        (
            "My laptop was stolen, who do I report it to?",
            "security.md",
            "How to report an incident",
        ),
        ("How long is the trial period for engineers?", "onboarding.md", "Trial period"),
    ],
)
def test_retrieval_finds_the_right_section(
    index: rag.BM25, question: str, expected_source: str, expected_title: str
) -> None:
    top = index.search(question, k=1)[0]
    assert (top.source, top.title) == (expected_source, expected_title)


def test_unrelated_question_retrieves_nothing(index: rag.BM25) -> None:
    assert index.search("xylophone quantum") == []


@respx.mock
def test_answer_sends_context_through_relay(index: rag.BM25) -> None:
    route = respx.post("http://relay.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "llama3.2:3b",
                "choices": [
                    {"message": {"role": "assistant", "content": "Within 30 days [expenses.md]."}}
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 8},
                "relay": {"provider": "ollama", "fallback_used": False, "masked_entities": 0},
            },
        )
    )
    with RelayClient("http://relay.test", api_key="rk_test") as client:
        result = rag.answer("How long do I have to submit an expense?", client, index)

    sent = json.loads(route.calls.last.request.content)
    assert sent["metadata"] == {"policy": "data_policy"}
    assert "[expenses.md]" in sent["messages"][0]["content"]
    assert sent["messages"][1] == {
        "role": "user",
        "content": "How long do I have to submit an expense?",
    }
    assert result.content == "Within 30 days [expenses.md]."
