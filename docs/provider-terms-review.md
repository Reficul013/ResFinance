# Provider Coverage and Terms Review

Review date: 2026-10-13

Scope: Milestone 0 engineering review for the fixed UTC research period
2020-04-10 through 2025-01-01 and the exact asset set `BTC | ETH | SOL`.
This document is not legal advice. A provider marked conditional or blocked is
not approved for production ingestion until the stated condition is resolved.
The current declared use is a university, non-commercial research project. That
scope does not authorize later commercial use under research-only terms.

## Coverage evidence

| Provider/channel | Observed evidence | Coverage result |
|---|---|---|
| Coin Metrics Community `PriceUSD` | One daily query returned 5,184 rows: 1,728 each for BTC, ETH, and SOL, no null prices, first timestamp 2020-04-10 and last timestamp 2025-01-01. Response SHA-256: `607777d12cce5104ea3e3570ff76f43844ecadd2212f6b3ede704e34836d4701`. | Full fixed-period price coverage passes. |
| CoinGecko current USD quotes | Current BTC, ETH, and SOL quote probe returned HTTP 200. | Availability passes for the planned live-quote fallback; it is not the historical research source. |
| DefiLlama Solana TVL | The public history returned 2,037 rows; its first timestamp is 2021-03-17, after the research start. | The early interval is explicitly missing and must remain masked. Use passes only for the declared personal, non-commercial research scope below. |
| GDELT DOC / GKG | The DOC historical query was rate-limited, so the partitioned public GKG table was queried in billing-disabled BigQuery Sandbox. The bounded query processed 276.48 GB in 35.724 seconds and returned exactly 5,184 daily asset rows: 1,728 each for BTC, ETH, and SOL. It matched 277,883 documents; 47 day/asset rows had zero documents. CSV SHA-256: `5c6aa7f22c8e4595ab68944276b0abe4867ea71967bfb52c1469911bde2f541a`. | Full fixed-period aggregate coverage passes. The 260,315-byte aggregate was stored and hash-verified through the real ResilientDB stack under manifest key `resfinance.m0.gdelt.gkg.daily.5c6aa7f22c8e4595.manifest`. |

The probe retains source URL, retrieval time, HTTP status, bytes, and response
hash without committing provider payloads to Git. Once ingestion is implemented,
raw permitted data and provenance must be written directly to ResilientDB.

## Terms disposition

| Provider | Reviewed official terms | Engineering disposition |
|---|---|---|
| Coin Metrics Community | The official [Coin Metrics data repository](https://github.com/coinmetrics/data) identifies Community data as [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). | **Pass for the declared non-commercial university research scope, with attribution.** Commercial use or redistribution outside that license requires a separate review. |
| CoinGecko | [API Terms](https://www.coingecko.com/en/api_terms) require attribution and prohibit selling, sublicensing, redistributing, or syndicating API access or part of it absent a separate agreement. | **Pass for planned current-quote display with attribution.** Do not expose, sell, or redistribute the raw API data. |
| DefiLlama | [Terms of Use](https://enterprise.defillama.com/terms) grant ordinary access for personal, non-commercial purposes and require prior written consent for commercial harvesting or exploitation. | **Pass only for the declared personal, non-commercial university research project.** Institutional deployment, commercial use, or redistribution requires written clarification or a replacement approved by ADR. |
| GDELT | [Terms of Use](https://www.gdeltproject.org/about.html#termsofuse) allow unlimited academic, commercial, or governmental dataset use and redistribution with a GDELT citation and link. | **Pass with attribution.** The bounded aggregate extraction and ResilientDB readback passed. |

## Ongoing obligations

1. Record Coin Metrics CC BY-NC 4.0 attribution in research outputs and keep the current use non-commercial.
2. Show CoinGecko attribution with current quotes; do not expose or redistribute raw data.
3. Keep DefiLlama use personal and non-commercial. Re-review or replace it through an ADR before institutional deployment, commercial use, or redistribution.
4. Keep GDELT attribution with research outputs and retain the query, attestation, and ResilientDB manifest hashes.
5. Persist permitted provider records and manifests in ResilientDB, never Git or a substitute database.

## Zero-cost BigQuery procedure

BigQuery Sandbox does not require a credit card and includes a monthly free query
allowance. The public GKG table is large, so a date bound alone does not guarantee
that the full query fits the remaining allowance. The completed query was
estimated and processed at 276.48 GB, below the 1 TiB monthly Sandbox allowance.
Future reruns must check the estimate again. If it exceeds the remaining free
allowance, do not run it and do not enable billing.

The checked query:

- hard-bounds both `_PARTITIONTIME` and the GKG timestamp to the research period;
- matches full names `bitcoin`, `ethereum`, and `solana`, not ambiguous ticker symbols;
- emits exactly one row per UTC day and asset, including zero-coverage days;
- returns document/source counts and aggregate tone only; and
- creates no BigQuery table and stores no full article text.
