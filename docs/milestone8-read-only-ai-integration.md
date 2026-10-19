# Milestone 8 — Read-only AI and Cross-Dashboard Integration

Status: complete for local development and real-stack acceptance. Cloud,
production, trading, custody, autonomous actions, and investment-advice claims
remain out of scope.

## Purpose

Milestone 8 connects the local user journey at the application-feature level
with wallet-scoped Smart Savings Insights, cross-dashboard navigation, and
in-app notifications. It explains Finance, Groups, and Crypto state without
giving a model access to private keys, write commands, ResContract, trading
systems, direct ResilientDB operations, or the public internet. The continuous
real-browser/full-stack handoff is intentionally assigned to Milestone 9.

## Evidence-bound design

The authenticated application service assembles a content-addressed fact bundle
from the existing Finance, Groups, and Portfolio read models. Facts contain a
stable fact ID, topic, human-readable statement, source kind, immutable source
IDs, and an as-of timestamp. Group facts include only groups for which the
wallet is an active member and obligations involving that wallet.

The local instruction model does not author the final response. It may select
one through four relevant fact IDs and report a confidence value. The server:

- rejects unknown, duplicate, off-topic, or low-confidence selections;
- renders the final summary directly from the validated fact statements;
- returns the exact evidence objects used;
- adds deterministic caveats and allowlisted follow-up questions; and
- falls back to a deterministic selector when the model or weights are
  unavailable.

This makes the factual output closed over the authorized bundle: generated text
cannot introduce a financial claim that lacks a supplied fact ID.

## Refusal and isolation controls

- Prompt-control phrases are treated as untrusted text and refused before model
  inference.
- Requests to buy, sell, transfer, settle, sign, approve, edit, delete, or
  otherwise act are refused before model inference.
- Unsupported topics return a bounded explanation and suggested supported
  questions.
- The question is limited to 500 characters.
- Runtime model loading is offline-only with `local_files_only=True` and
  `trust_remote_code=False`.
- The insights service has only read interfaces. Real-stack acceptance observed
  zero ResilientDB writes across overview, query, injection, prohibited-action,
  unsupported-topic, and cross-wallet checks.

## Pinned local model and benchmark

The selected model is `Qwen/Qwen2.5-1.5B-Instruct` at revision
`989aa7980e4cf806f80c7fef2b1adb7bc71aa306`, licensed Apache-2.0. Runtime and
generation policy pins plus SHA-256 hashes for the weights, configuration, and
tokenizer configuration are recorded in
[`config/milestone8-model-lock.json`](../config/milestone8-model-lock.json).

On the local ARM64 acceptance machine with Python 3.13.2, PyTorch 2.14.1, and
Transformers 4.57.6, two deterministic selections returned only the permitted
budget fact with confidence 1.0. Cold selection took 10.04 seconds, the repeated
selection took 4.46 seconds, and measured resident-memory growth was about 3.12
GB. These figures are local feasibility evidence, not a production latency or
capacity claim. Full evidence is in
[`config/milestone8-model-benchmark.json`](../config/milestone8-model-benchmark.json).

## API and interface

- `GET /api/v1/insights/overview?month=YYYY-MM` returns the fact-bundle ID,
  initial insight, evidence, caveats, follow-ups, and notifications.
- `POST /api/v1/insights/query` computes a read-only answer and appends no event.
- The generated `/api/v1` TypeScript client is the browser's only data path.
- Smart Savings Insights is embedded below the Personal Finance dashboard and displays the answer,
  generation mode, evidence cards, caveats, follow-up questions, and a Data
  Freshness and Provenance panel. Fact-bundle and model-revision values are
  presented only in that panel as inspectable provenance tags; evidence cards
  use plain-language verified-record counts.
- The shared notification center surfaces budget alerts, wallet-scoped Group
  updates, and the current Crypto forecast gate with links to the relevant
  dashboard.

## Acceptance evidence

The real four-replica ResilientDB acceptance is recorded in
[`config/milestone8-local-attestation.json`](../config/milestone8-local-attestation.json).
It verified:

- all returned citations belonged to the authenticated fact bundle;
- prompt injection, prohibited actions, and unsupported questions were refused;
- another wallet could not see the seeded wallet's savings;
- budget and Crypto gate notifications were produced;
- the actual pinned local model completed evidence selection; and
- the AI path performed zero ResilientDB writes.

The Chromium journey also exercised the embedded Smart Savings Insights section, evidence display,
plain-language verified-record counts, notification count, refusal state,
responsive layout, and the Data Freshness and Provenance panel. The rendered
screenshot was visually inspected.

## Verification

```bash
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/pytest

cd client
npm run generate:api
npm run check
npm run lint
npm run format:check
npm test
npm run build
npm run test:e2e
```

The exact model and real-stack commands are listed in the root README. Model
weights stay outside Git and are mounted read-only for local runtime.

## Remaining boundary

At Milestone 8 acceptance, no forecasting model was promoted, so Insights
correctly explained the Crypto gate rather than inventing a recommendation.
Milestone 9 later completed the local lifecycle and promoted a distinct
predeclared forward candidate; that later evidence does not change Milestone
8's read-only AI boundary. Milestone 10 remains explicitly on hold. Milestone 8
does not establish cloud, production, commercial, BFT, or
investment-performance readiness.
