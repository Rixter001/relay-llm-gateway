"""`make demo`: send a prompt full of PII through Relay and show, side by side, what the
provider actually received (masked) and what the caller got back (restored).

Standard library only, so it runs with any Python 3 without installing anything.
Needs the stack from `make up` (the server must run with RELAY_DEBUG_SHOW_MASKED_PROMPT=true,
which docker-compose.yml sets, to return the masked prompt).
"""

import json
import os
import sys
import textwrap
import urllib.error
import urllib.request

BASE_URL = os.environ.get("RELAY_BASE_URL", "http://localhost:8000")
# Demo-only key, accepted by deploy/teams.demo.json. Never reuse it outside a local demo.
API_KEY = os.environ.get("RELAY_API_KEY", "relay-demo-key")

PROMPT = (
    "Write a short, polite reply to this customer message and address the customer by name.\n"
    "Message: 'Hello, I am Marie Dupont. My parcel was supposed to arrive at "
    "12 rue de la Paix, 75002 Paris last week. You can call me on 06 12 34 56 78 or write to "
    "marie.dupont@example.fr. Please refund me on FR76 3000 6000 0112 3456 7890 189.'"
)


def main() -> int:
    payload = {
        "model": "auto",
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": 300,
        # sensitivity=high: this request may only go to the local provider (Ollama).
        "metadata": {"policy": "data_policy", "sensitivity": "high"},
    }
    request = urllib.request.Request(  # noqa: S310 (the user's own local Relay URL)
        f"{BASE_URL}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310 (local URL)
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        print(f"Relay returned {exc.code}: {exc.read().decode()}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"Cannot reach Relay at {BASE_URL} ({exc.reason}). Did you run `make up`?")
        return 1

    relay = body["relay"]
    masked = relay.get("masked_messages") or [{"content": "(server debug flag is off)"}]
    answer = body["choices"][0]["message"]["content"]

    width = 58
    left = textwrap.wrap(masked[-1]["content"], width) or [""]
    right = textwrap.wrap(answer, width) or [""]
    print(f"\n{'SENT TO THE PROVIDER (masked)':<{width}} | RETURNED TO THE CALLER (restored)")
    print(f"{'-' * width}-+-{'-' * width}")
    for i in range(max(len(left), len(right))):
        a = left[i] if i < len(left) else ""
        b = right[i] if i < len(right) else ""
        print(f"{a:<{width}} | {b}")
    print(
        f"\nprovider={relay['provider']}  model={body['model']}  "
        f"masked_entities={relay['masked_entities']}  fallback_used={relay['fallback_used']}  "
        f"cost_usd={relay['cost_usd']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
