# Milestone 0 Feasibility Gate

Status: In progress — local ecosystem gates pass; provider gate remains open

Last evidence review: 2026-10-12

## Purpose

Milestone 0 proves that the required Apache ResilientDB ecosystem can support ResFinance without substituting another database, weakening key isolation, or bypassing signed settlement. A gate is `pass`, `fail`, `partial`, or `blocked`. Only `pass` satisfies acceptance.

The machine-readable pins are in [`config/milestone0-lock.json`](../config/milestone0-lock.json). Generated JSON evidence is local-only and must not be committed because it can contain host paths and volatile provider responses.

Milestone 0 code is a narrow feasibility spike unless a later milestone explicitly adopts it. A spike must use the real pinned integration and meet the same security and storage invariants, but it is not the complete maintainable product implementation assigned to later milestones.

## Current gate status

| Gate | Status | Current evidence | Required next evidence |
|---|---|---|---|
| 1. KV, range/history, durability, replica loss | Pass | Four local replicas passed set/get, OCC version history, versioned prefix range, full restart durability, and read/write with one replica stopped. | Convert the operator sequence into CI orchestration in Milestone 1; this local result is not a production/BFT claim. |
| 2. 100 MB artifact round trip | Pass | Real ResilientDB stored 104,857,600 bytes as 400 logical 256 KiB chunks over 1,600 CLI-safe 64 KiB transport records, then reconstructed the checked manifest after a verified full replica restart. Source/restored SHA-256: `d7de409992e7bb161af1d7c0fb5e4621a962f9f8e41976c8f670c5d0a71af89a`. | Preserve the logical manifest in the production blob adapter and segment only the CLI transport until a binary transport is proven. |
| 3. ResContract lifecycle | Pass | Solidity 0.8.28 compiled and deployed token and settlement contracts. Account, selector, runtime bytecode, and token balances remained queryable after all contract processes restarted. | Upstream or maintain the documented persistence patch before production adoption. |
| 4. Signed settlement saga | Pass | An explicitly approved Ed25519 intent traversed `/api/v1`, passed origin/audience/network/hash/signature/replay checks, changed real ResContract state, and appended/read back the confirmed ResilientDB event. | Replace the disposable adapters with maintainable Milestone 1/2 implementations. |
| 5. ResVault key isolation | Pass for M0 boundary; upstream failed | The official implementation failed audit. The isolated M0 signer returns only public identity/signature, requires exact origin and explicit approval, and non-disclosure tests cover page/request, server response, contract call, ResilientDB record, and logs. | Complete the persistent hardened extension/compatible redesign in Milestone 2; do not ship the M0 in-memory signer as the wallet. |
| 6. Provider availability and provenance | Partial | Coin Metrics returned all 5,184 expected fixed-period daily price rows with no nulls. CoinGecko current quotes responded. DefiLlama begins 2021-03-17 and its current terms block unapproved commercial harvesting. GDELT DOC was rate-limited or returned non-JSON; GKG/BigQuery extraction is not yet proven. | Resolve the license conditions and run/store the complete bounded GDELT historical extraction. See the provider terms review. |
| 7. Failure enforcement | Pass | Repository scan finds no forbidden persistence implementation. The harness exits nonzero while any mandatory gate is incomplete. | Keep this control active in CI as application code is added. |

Overall status: **blocked on gate 6**. The local ResilientDB, ResContract, signed-settlement, artifact, and M0 key-isolation boundaries are feasible. Historical sentiment acquisition and provider permission are not yet approved, so provider-dependent research work must not proceed as if the full dataset were available.

## Reproduce the available checks

Prerequisites are Git, Node 22.14.0, Python 3.13.2, Docker Desktop, and the pinned Solidity compiler. Local tool paths may be supplied explicitly because neither Docker Desktop nor `solc` has to be installed globally.

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
RESFINANCE_DOCKER_BIN=/path/to/docker \
RESFINANCE_DOCKER_HOST=unix:///path/to/docker.sock \
scripts/milestone0/build_resilientdb.sh /path/to/pinned/resilientdb
python3 -m scripts.milestone0.run \
  --upstream /private/tmp/resfinance-resilientdb-upstream \
  --output /tmp/resfinance-milestone0-evidence.json \
  --network \
  --allow-incomplete
```

Omit `--allow-incomplete` in CI. The command remains nonzero until all seven gates pass.

## Real-stack execution requirements

The local run used:

- Docker Desktop 4.94.0 with Linux ARM64 engine 29.8.2.
- Image `resfinance/resilientdb:4de5cb4-m0`, digest `sha256:5a639ec02a654aa4fec3e2ecba7a151f93c8acdd6319e187696b0c3417f206f8`, built from pinned commit `4de5cb43686276ace4307f44839a1de920ab524a` plus patch SHA-256 `d1be8733736b0bc0dc3d8df525e16a29e4b7bb18345071d52ba5e9e9b20594b2`.
- Solidity compiler 0.8.28, binary SHA-256 `81515b0e53deaa266d549545ccaac0a5a96e6d4e8201c77f673b2c710976d9ea`.
- Four observable replica processes, durable volumes, and the ability to stop and restart individual replicas.
- Private ResContract access from the test backend only.
- The isolated M0 signing boundary; it does not replace the Milestone 2 persistent extension.

## Upstream integration findings

- The pinned KV CLI implements `set`, `get`, `set_with_version`, `get_with_version`, `get_key_range`, `get_key_range_with_version`, `get_top`, and `get_history`. This supports the planned deterministic-key adapter, subject to real-stack validation.
- OCC writes require the caller to submit the current version (`0` for a new key); the CLI return code reflects consensus acceptance and does not expose a storage-level version rejection. Adapters must query and verify resulting versions.
- The KV target's unconditional unused DuckDB dependency exhausted the 8 GiB Docker build allocation. The checked compatibility patch removes that edge while retaining LevelDB as the persistent backend.
- ResContract 1.2.5 defaults to in-memory service storage and also keeps account membership, selector mappings, and eEVM runtime code in process memory. The compatibility patch moves service storage to LevelDB and persists/reloads those indexes. Its convenience npm CLI targets the KV-wrapped service and writes a deployment registry to `~/.rescontract_deployed_contracts.json`; ResFinance uses the matching direct contract CLI and never treats that file as authoritative state.
- The public ARM64 image index digest was pushed before the pinned source commit and exposes no verified commit attestation in the inspected metadata. It is recorded for provenance but cannot be the final gate artifact.
- The official ResVault implementation crosses private material into the webpage and needs the substantial hardening described by ADR 0001. M0 proves the replacement message contract only; encrypted persistent storage, lock lifecycle, and extension UI remain Milestone 2 work.
- Coin Metrics proves complete daily price coverage for the fixed period. Provider gate closure is blocked by GDELT extraction reliability and unresolved provider permissions documented in [`provider-terms-review.md`](provider-terms-review.md).

## Evidence rules

Every final gate record must include the lock-file hash, upstream commit, image digest, tool versions, UTC start/end, exact command, exit status, sanitized output hash, and operator. Secrets, private keys, passwords, seeds, decrypted payloads, and PII are prohibited from evidence and logs.
