# ResFinance Milestone Convention

Effective: 2026-10-21

This is the canonical milestone naming convention for ResFinance. New planning,
status updates, issues, commits, and handoffs must use these eight milestones.

1. **Milestone 1: ResFinance Foundation — Architecture, Feasibility Gate & Platform Foundation**
2. **Milestone 2: ResWallet — Custom Hardened ResVault & Wallet Authentication**
3. **Milestone 3: Personal Finance — Dashboard & Smart Insights (Read-only AI)**
4. **Milestone 4: Bill Split — Friends, Groups & Contractual Settlement**
5. **Milestone 5: Crypto Intelligence — Crypto Ingestion, Feature Store & Reproducible ML Research**
6. **Milestone 6: Crypto Intelligence — Risk, Portfolio & Crypto Dashboard**
7. **Milestone 7: Deliverables — Cross-dashboard Integration & Local Handoff**
8. **Milestone 8: Future Scope — Production Hardening & Deployment (On Hold)**

## Consolidation map

| Current milestone | Earlier roadmap material now included |
|---|---|
| Milestone 1 | Earlier Milestones 0 and 1: architecture, feasibility gates, pinned dependencies, and platform foundation |
| Milestone 2 | Earlier Milestone 2: ResWallet hardening and wallet authentication |
| Milestone 3 | Earlier Milestone 3 plus the Smart Insights/read-only AI portion of earlier Milestone 8 |
| Milestone 4 | Earlier Milestone 4: Friends, Groups, bill splitting, and contractual settlement |
| Milestone 5 | Earlier Milestones 5 and 6: ingestion, feature store, and reproducible ML research |
| Milestone 6 | Earlier Milestone 7: risk, portfolio optimization, and Crypto dashboard |
| Milestone 7 | Cross-dashboard integration from earlier Milestone 8 plus earlier Milestone 9 Local Handoff |
| Milestone 8 | Earlier Milestone 10: production hardening and deployment, still on hold |

## Legacy artifact names

Historical script modules, configuration files, attestations, image tags, run
IDs, and evidence filenames keep the milestone number they had when the
evidence was produced. Renaming those identifiers would break reproducibility,
commands, links, or immutable provenance.

For example, `scripts.milestone9.local_handoff` is the implementation command
for current Milestone 7, and `config/milestone6-local-attestation.json` records
the reproducible ML research now grouped under current Milestone 5. These are
compatibility identifiers, not additional current milestones.

Do not create new product milestones outside 1–8. When adding new evidence to
an existing legacy implementation path, describe the work using the current
milestone name and identify the legacy path only as the executable or artifact
location.
