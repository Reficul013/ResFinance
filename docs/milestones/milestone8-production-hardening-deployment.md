# Milestone 8: Future Scope — Production Hardening & Deployment (On Hold)

Status: On hold

Milestone 8 is the only current milestone that is not complete. No cloud
infrastructure, production deployment pipeline, production-readiness claim, or
independent-BFT claim is authorized while the deployment hold remains active.

## Resume conditions

Before implementation resumes, ResFinance must complete a separate,
evidence-backed feasibility review of the pinned ResilientDB and ResContract
stack in the proposed cloud environment. The review must cover:

- networking and private service boundaries;
- persistent storage and full restart recovery;
- replica loss and genuinely independent failure domains;
- operational support and upgrade behavior;
- production key custody and KMS integration;
- encrypted backups and verified restore procedures;
- observability, alerting, capacity, and incident response; and
- provider licensing and commercial-use constraints.

If the feasibility review passes, the selected architecture must be approved in
an ADR before provisioning infrastructure or adding deployment automation.

## Deferred implementation

The following work remains deferred until the hold is explicitly lifted:

- production TLS, reverse proxy, and public ingress;
- static frontend hosting and production API/worker deployment;
- private production ResContract and ResilientDB operations;
- production KMS, secret rotation, backup, and disaster recovery;
- production monitoring, alerting, audit retention, and runbooks;
- cloud deployment pipelines and environment promotion; and
- production-scale security, load, failure, and recovery acceptance.

## Work that remains in scope

Local development, integration, research, security, browser, accessibility,
load, and chaos testing may continue because they improve implementation
quality without claiming cloud or production readiness.

## Acceptance

Acceptance is deferred. When Milestone 8 resumes, its criteria must be
re-approved against evidence from the selected cloud environment. Completion
of Milestones 1–7 does not imply that Milestone 8 has started or that ResFinance
is production-ready.
