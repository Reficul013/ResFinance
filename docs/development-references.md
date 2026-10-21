# ResFinance Development References

Use these references when implementing or validating the ResilientDB, ResWallet, upstream ResVault, and ResContract integrations.

## Apache source

- [Apache ResilientDB repository](https://github.com/apache/incubator-resilientdb)
- Milestone 0 pinned commit: [`4de5cb43686276ace4307f44839a1de920ab524a`](https://github.com/apache/incubator-resilientdb/commit/4de5cb43686276ace4307f44839a1de920ab524a)
- [Pinned ResContract source](https://github.com/apache/incubator-resilientdb/tree/4de5cb43686276ace4307f44839a1de920ab524a/ecosystem/smart-contract/rescontract)
- [Pinned upstream ResVault source](https://github.com/apache/incubator-resilientdb/tree/4de5cb43686276ace4307f44839a1de920ab524a/ecosystem/tools/resvault)
- Machine-readable revisions and dependency hashes: [`config/milestone0-lock.json`](../config/milestone0-lock.json)
- Hardened ResWallet dependency, policy, and upstream-reference lock: [`config/milestone2-lock.json`](../config/milestone2-lock.json)

## ExpoLab Beacon documentation

- [Beacon documentation portal](https://beacon.expolab.org/)
- [ResilientDB documentation](https://beacon.expolab.org/docs/resilientdb)
- [Upstream ResVault documentation](https://beacon.expolab.org/docs/resvault)
- [ResContract documentation](https://beacon.expolab.org/docs/rescontract)

## Usage rules

- Consult the Apache repository for source-level behavior and the Beacon pages for integration guidance.
- Record the exact upstream commit, release, image digest, or documentation version used by an implementation or feasibility test.
- Validate documented behavior against the project's pinned local stack before depending on it.
- Do not let an upstream example override the constraints in `AGENTS.md` or `docs/architecture-implementation-plan.md`.
- Capture any required compatibility patch or behavioral exception in an architecture decision record.
- Do not treat `expolab/resdb:arm64` as equivalent to the pinned source until its digest has a verifiable source-commit attestation or ResFinance builds an image reproducibly from the pinned commit.
- Use the checked Milestone 1 Compose topology for application repository work. It derives from the attested local image, adds only the pinned key-generator build target, generates development certificates into a Docker volume, and keeps all four replicas plus the client proxy on an internal network.
- The pinned CLI must use the minimal client-proxy configuration and `get_key_range_with_version` for decoded prefix scans. Its plain range command exposes serialized version-history bytes and is not an application repository boundary.
- The Milestone 2 ResWallet implementation uses pinned `@noble/hashes` 2.4.0 for Argon2id and `@noble/ed25519` 3.2.0 for signing. Package integrity values are checked in through both `reswallet/package-lock.json` and `config/milestone2-lock.json`; upgrades require explicit security review and cross-language signature tests.

