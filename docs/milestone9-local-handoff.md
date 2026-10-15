# Milestone 9 — Local Handoff

Status: local handoff implementation complete; full provider-data research and
live-recommendation gates remain incomplete.

Production and cloud deployment remain out of scope and on hold for Milestone
10. This milestone establishes a reproducible local product handoff only; it
does not establish commercial, custody, trading, production, or independent-BFT
readiness.

## Outcome

Milestone 9 packages the completed ResFinance components behind one bounded
local lifecycle, exercises them in a continuous two-wallet Chromium journey,
and makes manual ingestion and reconciliation jobs observable through
append-only ResilientDB records. It also provides the full provider-data
research runner without weakening the existing forecast-promotion policy.

The local application path is implemented and verified. The research runner
was not executed because the approved 2020-04-10 through 2025-01-01 GDELT daily
aggregate CSV is not present in the checkout or current ResilientDB volumes.
The historical attestation proves its prior hash, but an attestation is not a
substitute for the provider rows. Consequently no provider-backed candidate,
promotion event, or current-cutoff live forecast was produced, and the normal
Crypto experience continues to fail closed with no recommendation.

## What was implemented

- `scripts.milestone9.local_handoff` supplies `preflight`, `start`, `status`,
  `restart`, `logs`, `stop`, and an exact-phrase-confirmed `reset` command.
- Preflight verifies Apple Silicon, the live Docker engine and Compose, Node
  22, Python 3.13, installed client/extension dependencies, and the pinned
  local-model hashes when weights are present or required.
- Startup builds ResVault and the React client, starts the four ResilientDB and
  four ResContract replicas plus proxies, tools, contract initialization, and
  FastAPI, then starts the locally owned Vite process. Compose health is bounded
  to 180 seconds and API/client health polling to 120 seconds.
- Shutdown preserves Compose volumes. Restart uses the existing containers and
  volumes. Reset removes volumes only after the literal confirmation phrase
  `DELETE_LOCAL_RESFINANCE_STATE` and also clears disposable local runtime logs.
- A stale or foreign process on port 5173 now fails startup instead of being
  mistaken for a lifecycle-owned client.
- `scripts.milestone9.run_local_workers` runs current market ingestion and
  group reconciliation explicitly. Running and terminal job records are
  append-only ResilientDB values; no local JSON database was introduced.
- `scripts.milestone9.run_full_research` accepts either an approved live
  ingestion input or an existing provider-backed dataset hash, enforces the
  fixed BTC/ETH/SOL period and adequate history, runs five chronological folds
  with the required baselines and ablations, encrypts artifacts with a
  runtime-supplied key, persists them in ResilientDB, and applies
  `forecast-promotion-v1` without overrides.
- The browser acceptance uses two isolated Chromium profiles and the built
  ResVault extension. It contains no route interception and exercises the real
  `/api/v1`, ResilientDB, and ResContract paths.

The live journey also exposed and fixed three integration defects:

1. JavaScript millisecond timestamps did not match Python's canonical signed
   representation. Signed intents now use whole-second UTC values.
2. React Strict Mode could issue two concurrent rotating refresh requests and
   let a racing 401 disconnect a valid session. Initial refresh is now
   single-flight.
3. A user could begin the next Group mutation before the prior projection
   refresh rendered. Contract-affecting controls now remain disabled across
   every in-flight Group write.

## Real-browser acceptance scope

`npm run test:e2e:local` performs one continuous, non-mocked journey:

1. create two extension-held wallets and prove the extension does not answer
   the unapproved `localhost` origin;
2. authenticate both wallets through extension-owned approvals;
3. record income, expense, category, and budget data;
4. create a group, add the second wallet, and create a signed shared expense;
5. approve the obligation, fund non-redeemable credits, reject tampered and
   replayed intents, and partially then fully settle;
6. confirm the zero outstanding contract projection and Finance propagation;
7. record the risk profile and confirm the no-eligible-forecast gate;
8. attempt Analyze Another Amount, confirm it fails closed without an eligible
   forecast, and confirm Finance savings remain unchanged;
9. ask Smart Insights a supported question and confirm evidence is rendered;
10. ask for a prohibited transfer/settlement action and confirm refusal;
11. restart the lifecycle with volumes intact, reload the browser session, and
    confirm the settled state rebuilds; and
12. log out and verify the backend session is revoked and ResVault is locked.

Wallet seeds and private keys are generated inside each extension profile and
are never fixtures. Playwright retains traces and screenshots only on failure;
these generated directories remain ignored by Git.

The pinned Qwen overlay passed artifact-hash verification and API startup, but
one browser run did not return its supported Insights answer within the
explicit 120-second wait. The definitive bounded browser acceptance therefore
uses the normal deterministic evidence-template fallback. This is the declared
optional-model behavior, not a claim that local-model latency passed the final
journey.

## Research and promotion status

The approved full research inputs remain exact:

- assets: `BTC | ETH | SOL`;
- inclusive period: `2020-04-10` through `2025-01-01`;
- providers: Coin Metrics, DefiLlama, and the bounded approved GDELT daily
  aggregate;
- five expanding walk-forward folds, a 15-day embargo, 60 validation dates,
  30 test dates per fold, deterministic CPU execution, and 20 epochs by
  default; and
- naive, linear, LSTM, market-only, fixed-fusion, adaptive-gating, and every
  one-source-removed comparison.

The earlier GDELT CSV had SHA-256
`5c6aa7f22c8e4595ab68944276b0abe4867ea71967bfb52c1469911bde2f541a`,
but the CSV bytes are not currently recoverable. The current ResilientDB lookup
for its Milestone 0 manifest returned no value. Re-querying or supplying that
approved export is an explicit provider-data provisioning step and is not
performed silently by startup.

Even if the adaptive model passes promotion, held-out evaluation predictions
are not a current live forecast. A separately reproducible current-cutoff
inference artifact must still be published before the normal application may
show a live recommendation. Until then, no recommendation is the required safe
state.

## Acceptance matrix

| Criterion | Result | Evidence |
|---|---|---|
| One-command bounded startup and lifecycle | Pass | Hash-verified model startup reached both health endpoints; lifecycle-owned status passed. |
| Continuous real ResVault/browser/full-stack journey | Pass | Two profiles exercised Finance, Groups, ResContract, Crypto gate, deterministic Insights fallback, tamper/replay defenses, restart, and logout without API interception. |
| Restart persistence and projection rebuild | Pass | The settled obligation remained at `$0.00 outstanding` after the controlled stack restart. |
| Observable ingestion and reconciliation jobs | Pass | A reconciliation of the settled acceptance group completed with zero duplicate events; running/terminal records read back from ResilientDB. |
| Full non-smoke provider research | Blocked | Approved GDELT CSV bytes are unavailable; the runner refuses to substitute synthetic data. |
| Eligible live recommendation | Fail safe | No provider-backed promotion/current-cutoff forecast exists; the UI keeps the forecast gate closed. |
| Complete repository suites | Pass for implemented scope | Ruff, mypy, 107 Python tests, 9 client tests, 5 ResVault tests, both builds, extension inspection, 5 dashboard browser tests, and the live journey passed. Full provider research remains separately blocked above. |
| Reproducible operator guide | Pass | See [Milestone 9 local operator guide](milestone9-local-operator-guide.md). |

Milestone 9 therefore remains incomplete by design on the research and live
recommendation criteria. The missing approved dataset is the only input needed
to attempt the full run; passing the immutable gate is not guaranteed and must
not be manufactured.

## Final verification

The implementation handoff passed:

```text
.venv/bin/ruff check .                              pass
.venv/bin/mypy                                      pass (95 files)
.venv/bin/pytest                                    pass (107 tests)
client: check, lint, format, unit tests, build       pass (9 tests)
resvault: check, lint, format, tests, build, inspect pass (5 tests)
client npm run test:e2e                             pass (5 Chromium tests)
client npm run test:e2e:local                       pass (1 live journey, 2.8m)
local reconciliation worker                         pass (0 duplicate events)
local lifecycle status                              pass (API/client and replicas healthy)
```

No full-research result or local attestation was fabricated because the
required provider input was absent.
