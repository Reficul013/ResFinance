# Provider Coverage and Terms Review

Review date: 2026-10-12

Scope: Milestone 0 engineering review for the fixed UTC research period
2020-04-10 through 2025-01-01 and the exact asset set `BTC | ETH | SOL`.
This document is not legal advice. A provider marked conditional or blocked is
not approved for production ingestion until the stated condition is resolved.

## Coverage evidence

| Provider/channel | Observed evidence | Coverage result |
|---|---|---|
| Coin Metrics Community `PriceUSD` | One daily query returned 5,184 rows: 1,728 each for BTC, ETH, and SOL, no null prices, first timestamp 2020-04-10 and last timestamp 2025-01-01. Response SHA-256: `607777d12cce5104ea3e3570ff76f43844ecadd2212f6b3ede704e34836d4701`. | Full fixed-period price coverage passes. |
| CoinGecko current USD quotes | Current BTC, ETH, and SOL quote probe returned HTTP 200. | Availability passes for the planned live-quote fallback; it is not the historical research source. |
| DefiLlama Solana TVL | The public history returned 2,036 rows; its first timestamp is 2021-03-17, after the research start. | The early interval is explicitly missing and must remain masked. Production use is license-blocked below. |
| GDELT DOC | The historical query was rate-limited or returned HTTP 200 with a non-JSON body. GDELT raw GKG and BigQuery are the planned historical paths; the DOC endpoint is for live metadata. | Full-period sentiment acquisition is not yet proven. |

The probe retains source URL, retrieval time, HTTP status, bytes, and response
hash without committing provider payloads to Git. Once ingestion is implemented,
raw permitted data and provenance must be written directly to ResilientDB.

## Terms disposition

| Provider | Reviewed official terms | Engineering disposition |
|---|---|---|
| Coin Metrics Community | [Community Data](https://gitbook-docs.coinmetrics.io/packages/coin-metrics-community-data) states that the community offering is available under a Creative Commons license. | **Conditional.** Confirm the exact Creative Commons variant and attribution obligations in writing before production ingestion or redistribution. |
| CoinGecko | [API Terms](https://www.coingecko.com/en/api_terms) require attribution and prohibit selling, sublicensing, redistributing, or syndicating API access or part of it absent a separate agreement. | **Conditional.** Current-quote display may proceed only with required attribution and a reviewed plan; do not expose or redistribute raw data. |
| DefiLlama | [Terms of Use](https://enterprise.defillama.com/terms) grant ordinary access for personal, non-commercial purposes and require prior written consent for commercial harvesting or exploitation. | **Blocked for commercial production.** Obtain written permission or approve a compliant provider change through architecture review. Do not silently substitute a source. |
| GDELT | [Terms of Use](https://www.gdeltproject.org/about.html#termsofuse) allow unlimited academic, commercial, or governmental dataset use and redistribution with a GDELT citation and link. | **Pass with attribution.** Acquisition reliability and a bounded GKG/BigQuery query still need proof. |

## Required closure

1. Obtain the exact Coin Metrics Community license text or written confirmation.
2. Record the intended CoinGecko plan and attribution/derived-output treatment.
3. Obtain DefiLlama commercial permission or approve a replacement in an ADR.
4. Run and hash the bounded GDELT GKG/BigQuery extraction for the complete fixed period.
5. Persist permitted raw records and manifests in ResilientDB, never Git or a substitute database.
