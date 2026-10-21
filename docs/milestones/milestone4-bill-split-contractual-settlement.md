# Milestone 4: Bill Split — Friends, Groups & Contractual Settlement

Status: Complete for local development. Cloud and production deployment remain on hold.

## Delivered behavior

- Authenticated group creation, membership, exact integer-cent expense splits, participant notifications, and rebuilt projections.
- ResWallet-signed payer, approval/rejection, credit-funding, and settlement commands with origin, audience, network, expiry, parameter-hash, nonce, actor, and resource verification.
- `ResFinanceSettlement.sol` as the authoritative obligation and internal-credit state machine, including pending/open/partial/settled/rejected/cancelled states, replay protection, insufficient-credit checks, overpayment prevention, and receipts.
- Internal credits that are explicitly non-redeemable, non-monetary, and have no cash value. No fiat, native cryptocurrency, token, trade, or custody operation exists.
- Confirmed obligations and partial/full settlement propagation into both participants' encrypted Finance projections.
- A request/confirmation saga whose pending contract-confirmed settlements reconcile idempotently after a process or storage-cluster interruption.
- An accessible Groups dashboard using the generated `/api/v1` client only, with approval, credit, partial/full settlement, notification, loading/error/empty, and a Data Freshness and Provenance footer. It is the only user-facing location for the current projection version, encrypted source-event count, and update time while the same version remains authoritative for signed-command concurrency.

## Local ResContract topology

Compose runs four source-pinned contract replicas and one private client proxy on the internal `172.29.0.0/24` network. A one-shot job compiles with the digest-pinned Solidity 0.8.28 image, deploys the contract through the pinned Apache CLI, and stores only the public contract address and gateway caller in a Docker volume. The API receives the CLI, private client configuration, and read-only registry; no contract endpoint is published to the host or browser.

The pinned ResContract persistence compatibility layer does not retain a storage slot after it is written to literal zero. The credit ledger therefore stores `logical balance + 1`; this preserves a logical zero as a durable nonzero slot. The API also re-queries authoritative obligation and credit state before appending a recovered settlement confirmation.

## Verification evidence

The checked acceptance runner used real ResilientDB and ResContract instances. It created a signed two-user split, approved the debtor obligation, rejected insufficient credits, funded internal credits, settled partially, then injected a crash after the full settlement committed to ResContract but before its confirmation event. All four ResilientDB replicas, all four ResContract replicas, and both client proxies restarted. Reconciliation appended exactly one confirmation and rebuilt these exact results:

- obligation status: `settled`
- obligation settled: `6000` USD minor units
- debtor internal credits: `0`
- creditor internal credits: `6000`
- debtor Finance payable: `0`
- creditor Finance receivable: `0`
- private wallet material transmitted: `false`

The machine-readable summary is in [`config/milestone4-local-attestation.json`](../config/milestone4-local-attestation.json).

```bash
docker compose --profile tools up -d --build --wait \
  resdb-tools rescontract-tools
.venv/bin/python -m scripts.milestone4.run_groups_acceptance \
  --docker "$(command -v docker)" --restart

docker compose --profile app up -d --build --wait api
curl -fsS http://127.0.0.1:8000/api/v1/health

npm --prefix client run test:e2e -- --project=chromium
```

The Chromium suite covers exact Finance rebuilds and the Groups approval/funding/partial/full flow. Python contract/integration tests cover split tampering, nonce replay, overpayment, insufficient credits, receipt-bound Finance propagation, and crash reconciliation.
