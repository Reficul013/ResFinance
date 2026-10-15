# Milestone 9 — Local Handoff

Status: planned; implementation has not started.

Production and cloud deployment remain out of scope and on hold for Milestone
10. This document defines the final local delivery milestone only.

## Purpose

Milestone 9 turns the separately verified ResFinance components into a
repeatable local product handoff. A new developer or evaluator should be able
to start the stack predictably, use the actual ResVault extension in a real
browser, complete the cross-product journey against real local services, and
inspect trustworthy acceptance evidence.

This milestone also owns the remaining attempt to produce a live BTC/ETH/SOL
recommendation. A forecast may reach the normal application only through the
existing immutable promotion policy. Research failure is reported honestly;
the promotion gate must never be reduced, bypassed, or replaced by a fixture.

## Non-negotiable boundaries

- Apache ResilientDB remains the only persistent application and research
  database.
- Crypto remains exactly `BTC | ETH | SOL`, and USD monetary values remain
  integer cents.
- ResVault private keys and seeds remain extension-only and must not appear in
  browser pages, network requests, server data, test artifacts, or logs.
- ResContract remains authoritative for obligations and settlement state.
- Internal settlement credits remain non-redeemable and non-monetary.
- The browser uses generated `/api/v1` clients and never contacts ResilientDB,
  ResContract GraphQL, or contract CLI endpoints directly.
- Smart Insights remains read-only and evidence-bound.
- No candidate is promoted unless it passes the existing evaluation criteria.
- This milestone does not provision cloud infrastructure or claim production,
  commercial, investment-performance, or independent-BFT readiness.

## Workstream 1 — One-command local developer experience

Package the existing local components into a documented lifecycle that:

1. validates pinned Docker, Python, Node, browser, extension, model, and local
   resource prerequisites before changing state;
2. starts the four ResilientDB replicas, proxy, ResContract replicas and proxy,
   contract initialization, FastAPI, React client, required local workers, and
   optional pinned AI-model overlay;
3. uses bounded health checks and reports the exact failing component instead
   of relying on fixed sleeps;
4. verifies the local model revision and hashes before mounting its weights
   read-only from outside Git;
5. provides concise status and logs for every component;
6. provides clean shutdown without deleting persisted local evidence; and
7. provides a separate, explicitly confirmed reset path for disposable local
   state.

The primary startup path must not silently download dependencies, model
weights, or provider data. Any networked provisioning step must be explicit,
documented, pinned, and independently repeatable.

## Workstream 2 — Local fixtures and browser identities

Provide deterministic, non-secret application fixtures and isolated browser
profiles sufficient to exercise the complete product journey. Wallet keys must
be generated and held inside the hardened extension boundary; no seed or
private key may be committed as a fixture.

The local handoff must support at least two wallet identities so that a real
group expense can be created, approved, partially settled, and fully settled.
The fixture and cleanup design must remain idempotent and must not introduce a
hidden database.

## Workstream 3 — One continuous real-browser/full-stack proof

Add a browser acceptance journey that does not intercept or mock application
API calls. It must use the built React client, real FastAPI service, real
four-replica ResilientDB topology, deployed ResContract, and hardened ResVault
extension.

The journey must prove, in order:

1. create or unlock an extension-held wallet and authenticate;
2. record income, an expense, a budget, and any required recurring data;
3. create a group and shared expense with a second isolated wallet;
4. approve the obligation through explicit extension-owned signing;
5. partially and fully settle with non-redeemable internal credits;
6. confirm the matching Group and Finance projections and immutable receipt;
7. confirm calculated savings reaches the Crypto experience by immutable source
   reference;
8. record a risk profile and inspect the current forecast gate or an eligible
   promoted recommendation;
9. run Analyze Another Amount without mutating Finance;
10. ask Smart Insights a supported question and verify every citation belongs
    to the authenticated wallet's fact bundle;
11. verify cross-dashboard notifications and navigation; and
12. restart the local stack and confirm the accepted state rebuilds without
    duplicate events or settlement effects.

The journey must also demonstrate locked-wallet, wrong-origin, tampered-intent,
replay, cross-wallet isolation, and prohibited AI-action defenses without
exposing secret material in screenshots, traces, videos, or logs.

## Workstream 4 — Local ingestion and worker lifecycle

Package the existing ingestion and reconciliation capabilities as explicit
local jobs or workers with visible health and run status. The handoff must
document which processes are continuous, scheduled, or manually triggered.

Provider requests must retain provenance, availability timestamps, checksums,
missing-source masks, and the approved local non-commercial terms boundary.
Failed provider calls must not damage accepted observations or features.

## Workstream 5 — Full research run and promotion decision

Run the declared non-smoke research protocol on approved BTC/ETH/SOL data:

- preserve chronological splits, embargoes, fixed seeds, masks, and complete
  manifests;
- evaluate the adaptive model against every required baseline and ablation;
- persist data, configuration, environment, dependency, code, model, and
  artifact hashes in ResilientDB;
- record statistical and portfolio-relevant results without guaranteed-return
  or investment-performance language; and
- append an immutable promotion event only when every existing promotion rule
  passes.

If no candidate passes, the correct result is no promotion. The normal Crypto
dashboard and Smart Insights must continue to display the evidence-safe gate.
The live-recommendation objective, and therefore full completion of this
milestone, remains incomplete until an eligible candidate exists; fixtures and
manual database edits cannot satisfy it.

When a candidate does pass, the normal authenticated application must display
its freshness, uncertainty, model/run identity, promotion event, Finance source
event, risk-policy version, solver path, constrained BTC/ETH/SOL weights, and
exact-cent allocations. No trade is executed.

## Workstream 6 — Operator handoff and evidence

Document and verify:

- exact prerequisites and supported local architecture;
- expected CPU, memory, disk, and cold-start requirements;
- extension build, loading, locking, unlocking, and multi-profile setup;
- explicit model and provider-data provisioning;
- startup, status, restart, shutdown, and confirmed reset behavior;
- first-run setup and a deterministic demonstration path;
- common failures and component-specific troubleshooting;
- known limitations, including local-only and non-commercial boundaries; and
- a content-addressed acceptance attestation covering the complete handoff.

Generated data, model weights, browser profiles, private material, and large
test artifacts remain outside Git. Checked-in evidence contains hashes,
manifests, bounded logs, and sanitized results only.

## Acceptance criteria

Milestone 9 is complete only when all of the following hold:

1. After documented prerequisites and explicit provisioning, one documented
   command starts the entire local application and reaches bounded healthy
   state; status, shutdown, restart, and confirmed reset paths also pass.
2. A continuous Chromium journey with the real ResVault extension completes
   the Finance → Groups → settlement → Finance → Crypto → Insights flow without
   API interception, a substitute database, leaked secret material, or manual
   state edits.
3. The journey survives a controlled full-stack restart and rebuilds the same
   accepted projections without replay or duplication.
4. Local ingestion and reconciliation execution is documented, observable,
   idempotent, and failure-safe.
5. A full non-smoke research run produces complete reproducibility evidence and
   an honest promotion decision.
6. A live Crypto recommendation appears only from a non-stale eligible
   promotion event and reconciles exactly to Finance-derived integer cents. If
   no candidate qualifies, this criterion fails safely and the milestone stays
   incomplete rather than weakening the gate.
7. The complete backend, frontend, extension, contract, ML, portfolio, AI,
   accessibility, browser, restart, security, and local load suites pass.
8. The final operator guide and sanitized attestation allow another developer
   to reproduce the local handoff from a clean checkout.

## Explicitly not started

This planning update does not add or change startup scripts, Compose services,
fixtures, browser automation, wallet behavior, provider jobs, research runs,
model promotions, application code, or runtime state. Implementation begins
only after this milestone plan is reviewed and approved.
