# shared-ci

Development-candidate tooling for caller-owned context resolution, policy
eligibility and finite 6DQ receipt reconciliation. Source and synthetic fixtures
are present; this is not a released or certified consumer integration.

| Task | Entry |
| --- | --- |
| Understand modules, dependencies and caller responsibilities | [Architecture](docs/architecture.md) |
| Locate the contract for integration, change, upgrade or failure | [AI usage](docs/ai-usage.md) |
| Connect a fixed checkout or migrate copied scripts | [Integration and migration](docs/integration-and-migration.md) |
| Plan recovery of source, configuration or evidence | [Disaster recovery](docs/disaster-recovery.md) |

API sources of truth:

- [Context CLI](docs/context-cli-contract.md): six [shell entrypoints](scripts/context/) backed by `_context.py`.
- [Policy eligibility](docs/policy-validation-contract.md): [`evaluate_policy`](scripts/policy/validate.py), a pure function.
- [Quality aggregation](docs/quality-aggregation-contract.md): [`aggregate_6dq`](scripts/quality/aggregate.py), a pure function using policy eligibility.

Read docs, schemas, fixtures and code from the same externally selected full
commit. Historical local verification in the API contracts is bounded evidence,
not a new combined-suite result or full 6DQ. This tree supplies no workflow/hook
installer, machine registry, trusted evidence producer or verified required
checks. Consumer installation, authentication, release and recovery validation
remain separate work.
