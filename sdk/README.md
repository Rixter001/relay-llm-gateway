# relay-client

A small Python client for [Relay](../README.md). Relay speaks the OpenAI API, so any OpenAI
client works too; this package adds typed access to Relay's routing hints (`policy`,
`sensitivity`) and to what Relay reports back (provider used, fallback, masked entities, cost).

```bash
pip install -e ./sdk
```

```python
from relay_client import RelayClient

with RelayClient(base_url="http://localhost:8000", api_key="rk_...") as relay:
    result = relay.chat(
        "Summarise the complaint from Jean Dupont (jean.dupont@example.fr).",
        policy="data_policy",
        sensitivity="high",  # only the local provider (Ollama) may see this request
    )
    print(result.content)
    print(result.provider, result.fallback_used, result.masked_entities, result.cost_usd)
```

`RELAY_BASE_URL` and `RELAY_API_KEY` are read from the environment when not passed.
Errors returned by Relay (401 bad key, 402 budget reached, 429 rate limit, 502 all providers
failed) raise `RelayError` with the status code and Relay's message.
