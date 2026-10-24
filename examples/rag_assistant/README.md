# RAG assistant example

An HR assistant that answers questions over the four markdown files in [`docs/`](docs/),
calling Relay through the [`relay-client`](../../sdk) SDK.

1. **Retrieve**: the docs are split into sections (one per `## ` heading) and ranked against
   the question with BM25 keyword scoring (pure Python, no embedding model).
2. **Augment**: the top 3 sections go into the system prompt with their file name, and the
   model is told to answer only from that context and to cite sources.
3. **Generate**: the request goes to Relay with `policy="data_policy"`, so the local model is
   preferred for internal documents. Any PII in the question is masked by Relay on the way.

```bash
pip install -e ./sdk
export RELAY_BASE_URL=http://localhost:8000 RELAY_API_KEY=<your team key>
python examples/rag_assistant/rag.py "My laptop was stolen, what should I do?"
```

Why BM25 instead of embeddings: with a dozen sections, keyword ranking finds the right one
(see `tests/test_rag.py`), needs no extra model or vector database, and is easy to explain.
For thousands of documents or questions phrased very differently from the docs, switch to
embeddings plus a vector store.
