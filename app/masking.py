"""PII masking and unmasking with Microsoft Presidio.

Flow for one request:
  mask()   "Call Jean Dupont at 06 12 34 56 78"  ->  "Call <PERSON_1> at <PHONE_NUMBER_1>"
           and a mapping {"<PERSON_1>": "Jean Dupont", "<PHONE_NUMBER_1>": "06 12 34 56 78"}
  (the masked text is what the provider sees)
  unmask() puts the original values back into the provider's answer.

The mapping is a plain Python object that lives only for the duration of the request. It is
never written to Redis, Postgres, logs or traces (see docs/DECISIONS.md).

Detection (Presidio Analyzer) combines regex recognizers with checksums (email, IBAN, phone)
and spaCy named-entity recognition (person names). The replacement (Presidio Anonymizer)
resolves overlapping detections for us, then calls our operator to build each placeholder.
"""

import re
from dataclasses import dataclass, field
from typing import Protocol

from presidio_analyzer import Pattern, PatternRecognizer, RecognizerResult
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

# "<PERSON_1>", "<EMAIL_ADDRESS_2>": short, unlikely to appear in normal text, and LLMs tend
# to copy angle-bracket tokens verbatim into their answer.
PLACEHOLDER_RE = re.compile(r"<([A-Z_]+)_(\d+)>")

DEFAULT_ENTITIES = ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE", "FR_ADDRESS"]

# French street types, used by the address recognizer below.
_STREET_TYPES = (
    r"rue|avenue|av\.|boulevard|bd|place|chemin|allée|allee|impasse|quai|route|cours|"
    r"square|passage|voie|faubourg|promenade"
)


def french_address_recognizer(language: str) -> PatternRecognizer:
    """Regex recognizer for French postal addresses ("12 bis rue de la Paix, 75002 Paris").

    Presidio has no French address recognizer, and spaCy only tags pieces of an address as
    LOCATION, so the whole address is matched with a pattern instead.
    """
    number = r"\b\d{1,4}(?:\s?(?:bis|ter))?,?\s+"
    street = rf"(?:{_STREET_TYPES})\s+[A-Za-zÀ-ÿ'’\- ]{{2,60}}?"
    # Street name without postcode: whole words (up to 6) until punctuation or end of text.
    street_words = rf"(?:{_STREET_TYPES})\s+[A-Za-zÀ-ÿ'’\-]+(?: [A-Za-zÀ-ÿ'’\-]+){{0,5}}"
    postcode_city = r",?\s+\d{5}\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ'’\-]+(?:[ \-][A-ZÀ-Ý][A-Za-zÀ-ÿ'’\-]+)*"
    patterns = [
        # Full address with postcode and city: very reliable.
        Pattern("fr_address_full", number + street + postcode_city, 0.85),
        # Street only ("au 5 impasse des Lilas"): still personal data, slightly less sure.
        Pattern("fr_address_street", number + street_words + r"(?=\s*[,.;!?)]|\s*$)", 0.6),
    ]
    return PatternRecognizer(
        supported_entity="FR_ADDRESS",
        patterns=patterns,
        supported_language=language,
        global_regex_flags=re.IGNORECASE | re.UNICODE,
        name=f"FrenchAddressRecognizer_{language}",
    )


# Very common function words, used to guess the language of a prompt. Deliberately tiny:
# it only has to separate the languages we support, not identify any language in the world.
_STOPWORDS = {
    "en": set(
        "the and is are to of in for with you your my this that please can what on at from "
        "about write".split()
    ),
    "fr": set(
        "le la les et est un une des du de pour avec vous je mon ma au aux sur dans qui que "
        "son sa".split()
    ),
}


def guess_languages(text: str, languages: list[str]) -> list[str]:
    """Return the language(s) to analyse `text` with.

    Running a spaCy model on text in another language produces false positives (the French
    model tags English verbs like "Write" as person names) and over-wide spans. So we analyse
    each text in its own language only, and fall back to ALL languages when the guess is not
    clear: missing PII is worse than masking a word too many.
    """
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    scores = {lang: sum(w in _STOPWORDS.get(lang, set()) for w in words) for lang in languages}
    ranked = sorted(scores.values(), reverse=True)
    if len(ranked) < 2 or ranked[0] == 0 or ranked[0] < 2 * ranked[1]:
        return languages
    return [max(scores, key=lambda lang: scores[lang])]


class Analyzer(Protocol):
    """The part of presidio_analyzer.AnalyzerEngine we use (lets tests plug in a fake)."""

    def analyze(
        self,
        *,
        text: str,
        language: str,
        entities: list[str] | None = None,
        score_threshold: float | None = None,
    ) -> list[RecognizerResult]: ...


@dataclass
class Mapping:
    """Placeholder <-> original value for ONE request. Never persisted."""

    to_original: dict[str, str] = field(default_factory=dict)
    _to_placeholder: dict[tuple[str, str], str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    def placeholder_for(self, entity_type: str, value: str) -> str:
        # The same value always gets the same placeholder, across all messages of the request,
        # so the model can still tell that two mentions refer to the same person.
        key = (entity_type, value)
        if key not in self._to_placeholder:
            self._counters[entity_type] = self._counters.get(entity_type, 0) + 1
            placeholder = f"<{entity_type}_{self._counters[entity_type]}>"
            self._to_placeholder[key] = placeholder
            self.to_original[placeholder] = value
        return self._to_placeholder[key]


@dataclass
class MaskResult:
    texts: list[str]
    mapping: Mapping
    count: int  # number of PII occurrences replaced


class Masker:
    def __init__(
        self,
        analyzer: Analyzer,
        languages: list[str],
        entities: list[str] | None = None,
        score_threshold: float = 0.35,
    ) -> None:
        self.analyzer = analyzer
        self.languages = languages
        self.entities = entities or DEFAULT_ENTITIES
        self.score_threshold = score_threshold
        self.anonymizer = AnonymizerEngine()  # type: ignore[no-untyped-call]

    def detect(self, text: str) -> list[RecognizerResult]:
        """Run detection in the text's language (or all languages if unsure) and merge.

        Exact duplicates are dropped; overlapping spans are resolved later by the anonymizer.
        """
        seen: dict[tuple[str, int, int], RecognizerResult] = {}
        for language in guess_languages(text, self.languages):
            for r in self.analyzer.analyze(
                text=text,
                language=language,
                entities=self.entities,
                score_threshold=self.score_threshold,
            ):
                key = (r.entity_type, r.start, r.end)
                if key not in seen or r.score > seen[key].score:
                    seen[key] = r
        return list(seen.values())

    def mask(self, texts: list[str]) -> MaskResult:
        """Mask every text with ONE shared mapping. CPU-bound: call it from a worker thread."""
        mapping = Mapping()
        masked: list[str] = []
        count = 0
        for text in texts:
            results = self.detect(text)
            if not results:
                masked.append(text)
                continue
            operators = {
                entity: OperatorConfig("custom", {"lambda": self._operator(mapping, entity)})
                for entity in {r.entity_type for r in results}
            }
            output = self.anonymizer.anonymize(
                text=text,
                analyzer_results=results,  # type: ignore[arg-type]
                operators=operators,
            )
            masked.append(output.text)
            count += len(output.items)
        return MaskResult(texts=masked, mapping=mapping, count=count)

    @staticmethod
    def _operator(mapping: Mapping, entity_type: str):  # type: ignore[no-untyped-def]
        return lambda value: mapping.placeholder_for(entity_type, value)


def unmask(text: str, mapping: Mapping) -> str:
    """Replace every known placeholder in `text` by its original value.

    One regex pass over the text (rather than one str.replace per placeholder) so that an
    original value that happens to look like a placeholder is never replaced a second time.
    Unknown placeholders are left as they are.
    """
    return PLACEHOLDER_RE.sub(lambda m: mapping.to_original.get(m.group(0), m.group(0)), text)


def build_presidio_masker(
    languages: list[str], entities: list[str] | None, score_threshold: float
) -> Masker:
    """Create the real Presidio analyzer. Loads the spaCy models: slow, done once at startup."""
    from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    from presidio_analyzer.predefined_recognizers import PhoneRecognizer

    spacy_models = {"en": "en_core_web_lg", "fr": "fr_core_news_md"}
    nlp_engine = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": lang, "model_name": spacy_models[lang]} for lang in languages],
        }
    ).create_engine()

    registry = RecognizerRegistry(supported_languages=languages)
    registry.load_predefined_recognizers(languages=languages, nlp_engine=nlp_engine)
    # The default phone recognizer does not know French numbering ("06 12 34 56 78").
    registry.remove_recognizer("PhoneRecognizer")
    for language in languages:
        registry.add_recognizer(
            PhoneRecognizer(
                supported_language=language,
                supported_regions=["FR", "BE", "CH", "DE", "ES", "IT", "GB", "US"],
            )
        )
        registry.add_recognizer(french_address_recognizer(language))

    analyzer = AnalyzerEngine(
        nlp_engine=nlp_engine, registry=registry, supported_languages=languages
    )
    return Masker(analyzer, languages, entities, score_threshold)
