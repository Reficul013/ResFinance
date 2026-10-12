# ResFinance Development References

Use these references when implementing or validating the ResilientDB, ResVault, and ResContract integrations.

## Apache source

- [Apache ResilientDB repository](https://github.com/apache/incubator-resilientdb)

## ExpoLab Beacon documentation

- [Beacon documentation portal](https://beacon.expolab.org/)
- [ResilientDB documentation](https://beacon.expolab.org/docs/resilientdb)
- [ResVault documentation](https://beacon.expolab.org/docs/resvault)
- [ResContract documentation](https://beacon.expolab.org/docs/rescontract)

## Usage rules

- Consult the Apache repository for source-level behavior and the Beacon pages for integration guidance.
- Record the exact upstream commit, release, image digest, or documentation version used by an implementation or feasibility test.
- Validate documented behavior against the project's pinned local stack before depending on it.
- Do not let an upstream example override the constraints in `AGENTS.md` or `docs/architecture-implementation-plan.md`.
- Capture any required compatibility patch or behavioral exception in an architecture decision record.

