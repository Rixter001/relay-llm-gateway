# Design decisions

Short records of the main choices, the alternatives, and what each choice costs.

## 1. Why an OpenAI-compatible API instead of a custom one

The OpenAI chat-completions format is the de facto standard: almost every LLM library and
tool can talk to it by changing a base URL. Adopting it means existing apps move to Relay
without code changes, and switching from Claude to Gemini to a local model becomes a gateway
decision instead of an application rewrite. Relay-specific inputs go into OpenAI's existing
`metadata` field, and Relay-specific outputs into one extra `relay` object that OpenAI clients
simply ignore.
*Cost:* we inherit OpenAI's shape even where a provider offers more (e.g. Claude's separate
system prompt), and only the subset Relay needs is implemented (text, non-streaming).

## 2. Why Presidio instead of a hosted PII API or an LLM-based detector

Sending prompts to a third-party PII-detection service would defeat the purpose: the PII would
leave before being masked. An LLM-based detector would be slower, costly and non-deterministic.
Presidio runs in-process, is open source and auditable, combines regex recognizers with
checksums (IBAN mod-97, phone number libraries) for structured PII and spaCy NER for names, and
lets us add recognizers (we added French addresses and French phone regions).
*Cost:* it is probabilistic (see decision 10), and the spaCy models make the image large
(~600 MB) and startup slow.

## 3. Why the placeholder mapping is never stored

The mapping (`<PERSON_1>` → "Jean Dupont") is the PII itself. Storing it anywhere (Redis, a
database, logs) would recreate in one place exactly the data we are trying not to spread, and
would need its own encryption, retention and access controls. Because Relay is synchronous
(non-streaming), the mapping only needs to live between masking and unmasking of the same
request, so it is a local variable that disappears with the request.
*Cost:* a conversation's placeholders are renumbered on every request. That is fine because
the client always sends the full original history, which is re-masked consistently.

## 4. Why prompt and completion content is not logged

Logs and traces are copied widely (log pipelines, SaaS backends, backups) and kept for a long
time; prompts contain customer data and confidential business information. Logging them would
turn the observability stack into the biggest PII store of the company. The usage log answers
the operational questions (who, which provider, how many tokens, how much, how fast, did it
fail) without content, and the `usage_log` table simply has no column for text, so content
cannot be logged by mistake. Error messages are built without the request body for the same
reason.
*Cost:* debugging a bad answer needs the client to reproduce the request; there is no replay.

## 5. Why Redis for rate limits and budgets instead of in-process counters or PostgreSQL

Relay runs as several replicas. In-process counters would give each replica its own limit
(N replicas = N times the limit). Redis is shared by every replica, and `INCR` / `INCRBY` are
atomic, so two concurrent requests can never both read "59" and both pass. Keys expire on
their own (2 minutes for rate windows, ~40 days for monthly spend). PostgreSQL could do it too,
but a hot counter updated on every request is what Redis is built for.
If Redis is down, Relay refuses requests (503): failing open would silently disable budget
enforcement. Spend is stored as integer micro-dollars to stay exact.
*Cost:* one more component to run, and the budget is checked before the call, so in-flight
requests can overshoot it slightly. A reservation scheme (reserve an estimate, settle after)
would close that gap.

## 6. How fallback avoids double billing

Fallback is sequential, never parallel: providers are tried one at a time, each at most once,
and Relay never sends "hedged" requests to two providers at the same time. Relay never retries
the same provider either. A provider is only charged to the team when it returns an answer
with token usage, and only that one call is added to the budget and the usage log.
The remaining risk is honest to state: a provider that times out may still have processed (and
billed) the request on its side. To limit this, the connection timeout is short (3 s: if no
connection was made, the request was never sent) while the overall timeout is long (60 s), so
a slow-but-working provider is not abandoned too early.

## 7. Why routing is a hard data rule plus a soft policy

Two different questions are mixed in "routing": *may* this provider see this data (a
compliance rule), and *which* allowed provider is best (an optimisation). Relay keeps them
separate: `sensitivity: high` removes every non-local provider before any policy runs, and no
fallback can bring them back. The policy (`cost`, `latency`, `data_policy`) only orders what is
left. A bug or a misconfiguration in the policy can make Relay slower or more expensive, never
leak sensitive data to the cloud.

## 8. Why hashed team keys in a file instead of a database table

Keys are verified on every request; a file loaded at startup makes that a dictionary lookup,
with no database dependency on the hot path. Only SHA-256 hashes are stored, so leaking the
file (or the Kubernetes Secret it comes from) does not leak usable keys. A fast hash is enough
because the keys are 256-bit random tokens, not human passwords: there is nothing to
brute-force, so bcrypt/argon2 would only add latency.
*Cost:* adding a team means editing the file and restarting (or rolling) the pods. A database
plus an admin API would be the next step for self-service.

## 9. Why httpx calls instead of the vendors' SDKs

Calling the HTTP APIs directly keeps each adapter to one readable file that shows exactly what
is sent and received, one HTTP client and one error model for all providers, one shared
connection pool, and tests that mock HTTP with respx in the same way for every provider.
*Cost:* we follow API changes ourselves (for example, the Messages API now rejects
`temperature` on current Claude models, so the adapter does not forward it), and we lose SDK
conveniences such as automatic retries, which would conflict with our own fallback anyway.

## 10. The limits of regex- and NER-based PII detection

Masking with Presidio reduces what leaves the company; it does not guarantee anonymisation.
- **Recall is never 100% in practice.** Our 40-prompt evaluation reaches 100% recall, but it
  was written by us, in two languages, with well-formed PII. Unusual names, misspellings,
  PII inside code or tables, or other languages will be missed sometimes.
- **NER has false positives.** Capitalised words at the start of a sentence ("Rédige") are
  sometimes tagged as names (95% precision in our evaluation). Over-masking degrades answers
  slightly but leaks nothing, so the threshold favours recall.
- **Indirect identifiers are invisible to it.** "The only female engineer in our Lyon team"
  identifies a person without any name, email or number.
- **Context can leak through the answer.** The model sees placeholders but can still infer
  facts from the rest of the prompt.
This is why masking is combined with the data rule (`sensitivity: high` stays local), why the
evaluation runs in CI with a recall threshold, and why the README lists it as a limitation.
