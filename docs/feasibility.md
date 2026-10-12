# Milestone 0 Feasibility Gate

Status: In progress — mandatory gates are not yet satisfied

Last evidence review: 2026-10-12

## Purpose

Milestone 0 proves that the required Apache ResilientDB ecosystem can support ResFinance without substituting another database, weakening key isolation, or bypassing signed settlement. A gate is `pass`, `fail`, `partial`, or `blocked`. Only `pass` satisfies acceptance.

The machine-readable pins are in [`config/milestone0-lock.json`](../config/milestone0-lock.json). Generated JSON evidence is local-only and must not be committed because it can contain host paths and volatile provider responses.

## Current gate status

| Gate | Status | Current evidence | Required next evidence |
|---|---|---|---|
| 1. KV, range/history, durability, replica loss | Blocked | Pinned source exposes the required KV commands. This host has no Docker runtime. | Run commit/get/range/history against four replicas, restart the stack, then stop one replica and repeat reads/writes. |
| 2. 100 MB artifact round trip | Partial | Deterministic 100 MiB local split/reconstruction passes with 400 × 256 KiB chunks and an identical SHA-256. | Persist every chunk and the manifest in real ResilientDB, reconstruct after restart, and verify the digest. |
| 3. ResContract lifecycle | Blocked | ResContract 1.2.5 is pinned; its CLI invokes the compiled contract service and `solc`. Docker and `solc` are absent. | Compile, deploy, execute, query, restart, and query again on the pinned stack. |
| 4. Signed settlement saga | Blocked | Required signed-intent contract is documented. No FastAPI/contract/event integration exists yet. | Send an approved Ed25519 intent through REST, verify it, change contract state, and append the confirmed finance event. |
| 5. ResVault key isolation | Failed upstream | The pinned official implementation returns decrypted private keys through extension messaging and posts them to the webpage. See the audit. | Complete the substantial hardening work, then pass browser, network, server, storage, and log non-disclosure tests. |
| 6. Provider availability and provenance | Partial | Coin Metrics `PriceUSD` returned BTC/ETH/SOL rows at both research-period boundaries; CoinGecko current quotes and DefiLlama Solana history responded. GDELT rate-limited the probe. | Prove the complete 2020-04-10 through 2025-01-01 dataset per channel, complete terms review, and define missingness for channels whose history begins later. |
| 7. Failure enforcement | Pass | Repository scan finds no forbidden persistence implementation. The harness exits nonzero while any mandatory gate is incomplete. | Keep this control active in CI as application code is added. |

Overall status: **blocked**. Milestone 1 feature work must not claim the dependent integrations are feasible until gates 1–6 pass.

## Reproduce the available checks

Prerequisites for the currently available checks are Git, Node 22.14.0, and Python 3.13.2. The harness also reports missing Docker and `solc` rather than silently skipping them.

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m scripts.milestone0.run \
  --upstream /private/tmp/resfinance-resilientdb-upstream \
  --output /tmp/resfinance-milestone0-evidence.json \
  --network \
  --allow-incomplete
```

Omit `--allow-incomplete` in CI. The command must remain nonzero until all seven gates pass.

## Real-stack execution requirements

The final run needs:

- A Docker runtime capable of running Linux ARM64 images on this host.
- A ResilientDB image built from or attestably matching commit `4de5cb43686276ace4307f44839a1de920ab524a`. The public `expolab/resdb:arm64` digest is recorded but is not approved because no source-commit attestation was found and the tag predates the pinned commit.
- Solidity compiler 0.8.28.
- Four observable replica processes, durable volumes, and the ability to stop and restart individual replicas.
- Private ResContract access from the test backend only.
- A hardened ResVault build for the signed-settlement and non-disclosure gates.

## Upstream integration findings

- The pinned KV CLI implements `set`, `get`, `set_with_version`, `get_with_version`, `get_key_range`, `get_key_range_with_version`, `get_top`, and `get_history`. This supports the planned deterministic-key adapter, subject to real-stack validation.
- ResContract 1.2.5 compiles Solidity with `--evm-version homestead` and delegates account/deploy/execute operations to `contract_service_tools`. Its convenience CLI also writes a deployment registry to `~/.rescontract_deployed_contracts.json`; ResFinance must not treat that file as persistent or authoritative state.
- The public ARM64 image index digest was pushed before the pinned source commit and exposes no verified commit attestation in the inspected metadata. It is recorded for provenance but cannot be the final gate artifact.
- The official ResVault implementation crosses private material into the webpage and needs the substantial hardening described by ADR 0001.

## Evidence rules

Every final gate record must include the lock-file hash, upstream commit, image digest, tool versions, UTC start/end, exact command, exit status, sanitized output hash, and operator. Secrets, private keys, passwords, seeds, decrypted payloads, and PII are prohibited from evidence and logs.
