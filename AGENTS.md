# ResFinance repository instructions

These instructions apply to the entire repository. Add a nested `AGENTS.md` only when a directory needs narrower rules; nested instructions may refine but must not weaken the constraints below.

## Sources of truth

- Use `docs/architecture-implementation-plan.md` for architecture, security, data boundaries, milestone order, and acceptance criteria relevant to the current task.
- Use `docs/project-spec.md` for product behavior and the end-to-end user journey.
- When implementing or debugging ResilientDB, ResVault, or ResContract, consult `docs/development-references.md`, pin the exact upstream revision used, and validate documented behavior against the local stack.
- Follow the dependency-ordered roadmap. Milestone 0 feasibility gates block dependent feature work when they fail; do not bypass a gate with a substitute technology.

## Product and architecture boundaries

- Apache ResilientDB is the only persistent application and research database. Do not introduce PostgreSQL, MongoDB, SQLite, DuckDB, Redis, Parquet persistence, an external object store, or a hidden test database.
- Crypto support is exactly `BTC | ETH | SOL` across domain types, APIs, providers, models, UI, fixtures, and tests.
- USD is the only fiat denomination in V1. Store money as integer USD cents and crypto quantities/prices as validated decimal strings; never use binary floating point for monetary calculations.
- Browser code communicates with application services only through generated REST clients under `/api/v1`. It must not contact ResilientDB, ResContract GraphQL, or contract CLI endpoints directly.
- ResVault seeds and private keys never leave the extension. Contract-affecting actions require an explicitly approved, backend-verified signed intent.
- ResContract is authoritative for obligations and settlement state. Finance changes only after confirmed contract state and receipts.
- Group settlement uses internal, non-redeemable, non-monetary credits. V1 does not transfer fiat or native cryptocurrency, execute trades, or provide exchange custody.
- Domain records are append-only, schema-versioned, idempotent, UTC-based, and reducer-rebuildable. Corrections append compensating events.
- Encrypt sensitive payloads before ResilientDB. Never log secrets, private keys, raw passwords, decrypted seeds, or PII.
- Scenario analysis must not mutate Finance or replace the default savings source. AI behavior is read-only, evidence-bound, and unable to invoke write, wallet, settlement, or trading operations.

## Code organization

- Keep directory boundaries aligned with `client/src/{app,features,components,lib}`, `server/app/{api,domain,application,infrastructure,workers}`, `blockchain/{contracts,adapter,tests}`, `ml/{data,features,models,evaluation,portfolio}`, and `tests/{contract,integration,e2e}`.
- Keep the backend a FastAPI modular monolith with explicit domain, application, and infrastructure boundaries. Pydantic transport models do not replace domain models, and infrastructure imports must not leak into domain code.
- Python code uses typed boundaries, Ruff, mypy, and Pytest. TypeScript uses strict mode, ESLint, Prettier, Vitest, and generated OpenAPI types.

## Research and ML

- Every ML run records data, code, configuration, environment, dependency, model, and artifact hashes; chronological splits; fixed seeds; and a complete manifest.
- Keep generated research data and model artifacts in ResilientDB. Git contains source code and deterministic synthetic test generators only.
- Treat MSPCIFormer as a documented three-asset adaptation. Do not copy source from its author repository until an applicable license or explicit permission is documented.

## Verification and completion

- Every behavioral change needs tests at the lowest appropriate layer plus an integration test for cross-module behavior.
- Run the relevant available tests, lint, type checks, and builds before handoff. Use real ResilientDB integration tests where persistence behavior matters.
- Add exact runnable verification commands here when the toolchain is established; until then, derive them from checked-in configuration rather than inventing commands.
- Architecture exceptions require an ADR and explicit review. A failing integration never justifies silently introducing another database or weakening security boundaries.

## Deployment hold

- Cloud and production deployment are on hold. Do not provision cloud infrastructure, add a production deployment pipeline, or claim production/BFT readiness unless the hold is explicitly lifted after the required cloud feasibility review and ADR.
- Local development, integration, research, security, browser, accessibility, load, and chaos testing remain in scope.

## Repository ownership and external contributions

- Keep all implementation changes in this ResFinance repository and push only to its configured `origin` (`https://github.com/haseebshaik00/ResFinance.git`).
- Do not open or submit pull requests, issues, patches, branches, tags, commits, or other changes to Apache, ExpoLab, or any other external repository or organization.
- Treat upstream repositories as read-only references. Prefer the approved links in `docs/development-references.md` for source inspection.
- Before forking, cloning for modification, adding a Git remote, vendoring code, creating a submodule, or otherwise introducing content from another repository, explain why it is needed and obtain the user's explicit approval.
- If an upstream change appears necessary, first determine whether a compatible adapter or local fix can live safely in this repository. Otherwise stop, report the exact dependency or blocker, and ask the user how to proceed.

## Commit and push substantial changes

- When a task produces substantial, complete repository changes, verify the work, review the diff, create a focused commit with a meaningful Conventional Commit message, and push the current branch to its configured upstream before handing off.
- Substantial changes include working application code, tests, API or data-model changes, build configuration, and documentation that materially changes project behavior or direction.
- Before committing and pushing, review `README.md` against the completed diff. Update it in the same commit when user-visible behavior, setup or verification commands, architecture, supported scope, project status, or repository layout changed.
- When the completed diff does not affect README content, confirm that the README remains accurate and do not edit it solely to create documentation churn.
- Do not commit trivial formatting, typo-only edits, temporary debugging, empty scaffolding by itself, or unfinished/broken work.
- Stage only changes belonging to the completed task. Preserve unrelated user changes and never commit secrets, local environment files, credentials, generated artifacts, or large data/model files.
- If verification, authentication, networking, or branch protection prevents a safe push, leave the changes intact and report the exact blocker.
- Use a concise outcome-focused message such as `feat: add group settlement workflow` or `docs: define ResFinance implementation plan`.
- Never amend, force-push, rewrite history, or bypass repository protections unless the user explicitly asks.
