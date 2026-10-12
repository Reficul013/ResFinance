# ADR 0001: ResVault Hardening Strategy

Status: Accepted

Date: 2026-10-12

Decision owner: ResFinance repository owner

## Context

ResFinance requires ResVault identity and explicit approval for contract-affecting actions. The security contract prohibits seeds and private keys from leaving the extension. Audit of the pinned official implementation found that decrypted private keys are returned to the content script and posted to the webpage, while password and encryption-key storage do not meet the required separation.

## Decision

Maintain a substantial hardened ResVault implementation based on the pinned Apache source. Preserve recognizable ResVault behavior and ecosystem compatibility, but replace the unsafe signing bridge and key-storage/unlock design. The implementation will remain separate from application code, maintain an auditable patch history, and rebase only through explicit upstream review.

The hardened implementation must:

- Sign canonical intents only inside the extension background context.
- Return no private material to content scripts or pages.
- Use a versioned Argon2id and AES-256-GCM encrypted-seed format.
- Keep passwords, derived keys, and decrypted seeds memory-only while unlocked.
- Enforce explicit origins, exact target origins, schemas, expiry, nonces, audience, network, and user approval.
- Pass the security tests listed in the pinned-source audit before wallet-dependent behavior is accepted.

## Consequences

- ResVault remains part of the product; the audit does not remove wallet-dependent scope.
- Milestone 2 is larger than a minimal patch and needs extension-specific security tests and upstream-diff review.
- The unmodified official extension is prohibited for ResFinance signing.
- Until hardening passes, the signed-settlement and key-isolation feasibility gates remain unsatisfied.

## Rejected alternatives

- Use upstream unchanged: rejected because private key material crosses into the page.
- Apply only superficial message filtering: rejected because storage/unlock and origin boundaries also require changes.
- Replace ResVault with an unrelated wallet: rejected because it changes an approved product requirement and ecosystem boundary.
