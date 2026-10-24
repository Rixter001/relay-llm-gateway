import importlib.util
import json

import httpx
import pytest
import respx
from fakes import OLLAMA_URL, FakeAnalyzer, ollama_body
from fastapi.testclient import TestClient

from app.masking import Mapping, Masker, french_address_recognizer, unmask


def fake_masker() -> Masker:
    return Masker(FakeAnalyzer(), ["en"])


def test_mask_replaces_pii_with_numbered_placeholders() -> None:
    result = fake_masker().mask(["Write to Jean Dupont at jean.dupont@example.fr"])
    assert result.texts == ["Write to <PERSON_1> at <EMAIL_ADDRESS_1>"]
    assert result.count == 2
    assert result.mapping.to_original == {
        "<PERSON_1>": "Jean Dupont",
        "<EMAIL_ADDRESS_1>": "jean.dupont@example.fr",
    }


def test_same_value_gets_same_placeholder_across_messages() -> None:
    result = fake_masker().mask(
        ["Jean Dupont called.", "Tell Jean Dupont that Marie Curie will call back."]
    )
    assert result.texts == [
        "<PERSON_1> called.",
        "Tell <PERSON_1> that <PERSON_2> will call back.",
    ]
    assert result.count == 3


def test_text_without_pii_is_unchanged() -> None:
    result = fake_masker().mask(["What is the capital of France?"])
    assert result.texts == ["What is the capital of France?"]
    assert result.count == 0


def test_unmask_restores_values_and_leaves_unknown_placeholders() -> None:
    mapping = Mapping()
    mapping.placeholder_for("PERSON", "Jean Dupont")
    assert (
        unmask("Hello <PERSON_1>, see <PERSON_9>.", mapping) == "Hello Jean Dupont, see <PERSON_9>."
    )


def test_unmask_is_single_pass() -> None:
    # An original value that looks like a placeholder must not be expanded again.
    mapping = Mapping()
    mapping.placeholder_for("PERSON", "<PERSON_2>")
    mapping.placeholder_for("PERSON", "Marie Curie")
    assert unmask("<PERSON_1> and <PERSON_2>", mapping) == "<PERSON_2> and Marie Curie"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("J'habite au 12 rue de la Paix, 75002 Paris.", "12 rue de la Paix, 75002 Paris"),
        ("Livrer au 8 bis avenue Jean Jaurès 69007 Lyon", "8 bis avenue Jean Jaurès 69007 Lyon"),
        ("RDV au 5 impasse des Lilas, merci", "5 impasse des Lilas"),
    ],
)
def test_french_address_recognizer(text: str, expected: str) -> None:
    results = french_address_recognizer("fr").analyze(text, ["FR_ADDRESS"])
    best = max(results, key=lambda r: (r.score, r.end - r.start))
    assert text[best.start : best.end] == expected


def test_french_address_recognizer_ignores_plain_numbers() -> None:
    assert (
        french_address_recognizer("fr").analyze("J'ai 12 chats et 3 chiens.", ["FR_ADDRESS"]) == []
    )


@respx.mock
def test_provider_only_sees_masked_prompt_and_caller_gets_restored_answer(
    client: TestClient,
) -> None:
    route = respx.post(OLLAMA_URL).mock(
        return_value=httpx.Response(200, json=ollama_body("Sure, I will email <PERSON_1>."))
    )
    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [
                {"role": "system", "content": "You help Jean Dupont."},
                {"role": "user", "content": "Email Jean Dupont at jean.dupont@example.fr"},
            ],
            "metadata": {"sensitivity": "high"},
        },
    )
    sent = route.calls.last.request.content.decode()
    assert "Jean Dupont" not in sent
    assert "jean.dupont@example.fr" not in sent
    assert json.loads(sent)["messages"][1]["content"] == "Email <PERSON_1> at <EMAIL_ADDRESS_1>"

    body = response.json()
    assert body["choices"][0]["message"]["content"] == "Sure, I will email Jean Dupont."
    assert body["relay"]["masked_entities"] == 3
    assert body["relay"]["masked_messages"] is None  # debug flag is off by default


@respx.mock
def test_debug_flag_returns_masked_prompt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("RELAY_DEBUG_SHOW_MASKED_PROMPT", "true")
    get_settings.cache_clear()
    respx.post(OLLAMA_URL).mock(return_value=httpx.Response(200, json=ollama_body("ok")))
    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Call 06 12 34 56 78"}],
            "metadata": {"sensitivity": "high"},
        },
    )
    assert response.json()["relay"]["masked_messages"] == [
        {"role": "user", "content": "Call <PHONE_NUMBER_1>"}
    ]


# --- Tests with the real Presidio + spaCy models (run in the CI "masking-eval" job) ---------

spacy_models_installed = all(
    importlib.util.find_spec(m) for m in ("en_core_web_lg", "fr_core_news_md")
)


@pytest.fixture(scope="module")
def real_masker() -> Masker:
    if not spacy_models_installed:
        pytest.skip("spaCy models not installed")
    from app.masking import build_presidio_masker

    return build_presidio_masker(["en", "fr"], None, 0.35)


@pytest.mark.presidio
def test_real_presidio_masks_french_prompt(real_masker: Masker) -> None:
    text = (
        "Bonjour, je suis Marie Dupont, j'habite au 12 rue de la Paix, 75002 Paris. "
        "Mon numéro : 06 12 34 56 78, mon IBAN FR76 3000 6000 0112 3456 7890 189."
    )
    masked = real_masker.mask([text])
    for secret in ("Marie Dupont", "rue de la Paix", "06 12 34 56 78", "FR76 3000"):
        assert secret not in masked.texts[0]
    assert unmask(masked.texts[0], masked.mapping) == text


@pytest.mark.presidio
def test_real_presidio_does_not_mask_dates_or_urls(real_masker: Masker) -> None:
    text = "Explain what happened on 14 July 1789 and link to https://example.org."
    assert real_masker.mask([text]).texts[0] == text
