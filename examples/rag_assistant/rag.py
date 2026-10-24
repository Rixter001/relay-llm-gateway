"""A small RAG (retrieval-augmented generation) assistant that answers HR questions over a few
markdown documents, calling Relay through the relay-client SDK.

    python examples/rag_assistant/rag.py "How long do I have to submit an expense?"

Retrieval is deliberately simple: the docs are split into sections (one per "## " heading)
and ranked with BM25, a classic keyword-scoring formula. No embedding model or vector database
is needed for a handful of documents, and every step can be explained line by line.
"""

import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from relay_client import ChatResult, Message, RelayClient

DOCS_DIR = Path(__file__).with_name("docs")

SYSTEM_PROMPT = (
    "You are an HR assistant. Answer the question using ONLY the context below. "
    "If the context does not contain the answer, say you don't know. "
    "Cite the source of each fact in square brackets, e.g. [expenses.md]."
)


@dataclass
class Chunk:
    source: str  # file name
    title: str  # section heading
    text: str


def load_chunks(docs_dir: Path = DOCS_DIR) -> list[Chunk]:
    """Split every markdown file into one chunk per '## ' section."""
    chunks = []
    for path in sorted(docs_dir.glob("*.md")):
        sections = re.split(r"^## ", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
        for section in sections[1:]:  # sections[0] is the document title
            title, _, body = section.partition("\n")
            chunks.append(Chunk(path.name, title.strip(), " ".join(body.split())))
    return chunks


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class BM25:
    """BM25 ranking: a word counts more if it is frequent in the chunk (tf) and rare across
    all chunks (idf); long chunks are normalised so they don't win just by being long."""

    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.docs = [tokenize(f"{c.title} {c.text}") for c in chunks]
        self.avg_len = sum(len(d) for d in self.docs) / len(self.docs)
        doc_freq = Counter(word for doc in self.docs for word in set(doc))
        n = len(self.docs)
        self.idf = {w: math.log(1 + (n - df + 0.5) / (df + 0.5)) for w, df in doc_freq.items()}

    def search(self, query: str, k: int = 3) -> list[Chunk]:
        scores = []
        for chunk, doc in zip(self.chunks, self.docs, strict=True):
            tf = Counter(doc)
            score = 0.0
            for word in set(tokenize(query)):
                if word not in tf:
                    continue
                f = tf[word]
                norm = self.k1 * (1 - self.b + self.b * len(doc) / self.avg_len)
                score += self.idf[word] * f * (self.k1 + 1) / (f + norm)
            scores.append((score, chunk))
        ranked = sorted(scores, key=lambda pair: pair[0], reverse=True)
        return [chunk for score, chunk in ranked[:k] if score > 0]


def build_messages(question: str, context: list[Chunk]) -> list[Message]:
    context_text = "\n\n".join(f"[{c.source}] {c.title}: {c.text}" for c in context)
    return [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nContext:\n{context_text}"},
        {"role": "user", "content": question},
    ]


def answer(question: str, client: RelayClient, index: BM25 | None = None) -> ChatResult:
    index = index or BM25(load_chunks())
    context = index.search(question)
    # Internal HR documents: route with data_policy so the local model is preferred.
    return client.chat(build_messages(question, context), policy="data_policy")


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit('usage: python rag.py "your question"')
    question = " ".join(sys.argv[1:])
    with RelayClient() as client:  # RELAY_BASE_URL / RELAY_API_KEY from the environment
        result = answer(question, client)
    print(result.content)
    print(f"\n(provider: {result.provider}, masked entities: {result.masked_entities})")


if __name__ == "__main__":
    main()
