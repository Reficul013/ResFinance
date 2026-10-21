# ADR 0001: ResWallet Hardening Strategy

Status: Accepted

Date: 2026-10-12

Decision owner: ResFinance repository owner

## Context

ResFinance requires a wallet identity and explicit approval for contract-affecting actions. The security contract prohibits seeds and private keys from leaving the extension. Audit of the pinned official ResVault implementation found that decrypted private keys are returned to the content script and posted to the webpage, while password and encryption-key storage do not meet the required separation.

## Decision

Maintain a custom hardened wallet named ResWallet for ResFinance. Preserve the useful browser-wallet role and explicit approval behavior learned from ResVault, but do not claim drop-in interoperability or inherit its unsafe signing bridge and key-storage design. Reuse of safe pinned-upstream components is allowed only after review; the ResWallet implementation must maintain an auditable history and accept upstream ideas or changes only through explicit review.

The hardened implementation must:

- Sign canonical intents only inside the extension background context.
- Return no private material to content scripts or pages.
- Use a versioned Argon2id and AES-256-GCM encrypted-seed format.
- Keep passwords, derived keys, and decrypted seeds memory-only while unlocked.
- Enforce explicit origins, exact target origins, schemas, expiry, nonces, audience, network, and user approval.
- Pass the security tests listed in the pinned-source audit before wallet-dependent behavior is accepted.

## Consequences

- ResWallet becomes the ResFinance wallet product; the audit does not remove wallet-dependent scope.
- Milestone 2 is larger than a minimal patch and needs extension-specific security tests and upstream-diff review.
- The unmodified official extension is prohibited for ResFinance signing.
- The disposable Milestone 0 signing boundary may unblock feasibility and other wallet-dependent implementation while the persistent browser extension is completed; it cannot satisfy Milestone 2 acceptance or be shipped as the wallet.

## Rejected alternatives

- Use upstream unchanged: rejected because private key material crosses into the page.
- Apply only superficial message filtering: rejected because storage/unlock and origin boundaries also require changes.
- Remove the wallet boundary: rejected because it removes user-controlled identity and explicit approval from the approved product flow.
