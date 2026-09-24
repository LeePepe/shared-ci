# Disaster recovery

This is a proposed recovery plan grounded in the current source, not an executed
drill, backup service or automatic repair facility. No RPO/RTO is established.
Reconstructing provider files and restoring a usable consumer or workflow are
different completion conditions.

## Assets and recovery boundaries

| Asset | Source or owner | What reconstruction does not recover |
| --- | --- | --- |
| Provider implementation, schemas, contracts and fixtures at one full commit | [Context](../scripts/context/), [policy](../scripts/policy/validate.py), [quality](../scripts/quality/aggregate.py), [schemas](../schemas/), [tests](../tests/), [API entry map](ai-usage.md#api-sources-of-truth) | Caller wiring, trusted baseline selection, authentic receipts or remote settings. |
| Caller contexts, manifests, gate argv and reference to provider | Caller repository; read by [`repo_root`, `parse_context`, `audit`, `command_run`](../scripts/context/_context.py) | These are not centrally stored product facts or a provider-managed backup. |
| Baseline, approvals, current observations and expected obligations | Caller/trusted producer; consumed by [`evaluate_policy`](../scripts/policy/validate.py) and [`aggregate_6dq`](../scripts/quality/aggregate.py) | Syntax or matching records cannot recreate authority, freshness or missing observations. |
| Reports, tested candidate/tree mapping and isolation observations | Evidence producer/store outside these pure modules | The aggregator does not fetch references, verify digest contents, rerun workloads or restore artifacts. |
| Any consumer hooks, workflow and required-check settings | Separately managed caller/remote configuration | No installer or recovery implementation for these assets is present in this tree. |

Tests are reconstructible examples, not backups of real results. Provider Git
objects alone cannot recover uncommitted caller state or unavailable evidence.

## Failure scenarios

| Scenario | Observable boundary | Proposed recovery and completion evidence |
| --- | --- | --- |
| Missing/corrupt provider source or mixed-revision docs/schema | A caller cannot load its selected files; no pure function can validate its own missing implementation | Reconstruct the complete externally selected revision in a separate location from a verified available source. Compare paths, bytes and modes with that revision, including executable wrappers. Source reconstruction ends only when the set matches. |
| Missing/malformed caller context, escaped path or graph drift | Context CLI errors/findings follow the [context contract](context-cli-contract.md#commands-and-outputs) | Restore caller-owned context/manifests from a known compatible baseline, preserving current work. In later authorized verification, require complete tracked-file classification, correct owner resolution and the expected negative cases. |
| Wrong policy pin, expired approval or unknown observation | Policy returns ineligible under its [failure order](policy-validation-contract.md#deterministic-failure-order-and-kinds) | Recover authentic pinned policy and approval records plus fresh observations through their actual owner. Completion requires provenance and current eligibility; editing a timestamp or copying a claimed approval is not recovery. |
| Wrong binding, missing receipt, missing declared report or isolation mismatch | Quality produces the contract's [binding, missing, coverage or isolation finding](quality-aggregation-contract.md#exact-state-machine-and-findings) | Recover genuine evidence matching the expected candidate/scope or obtain a separately authorized rerun. Check artifact existence and digest contents outside aggregation, then reconcile. Lost evidence stays unavailable until recovered. |
| Referenced external artifact lost or corrupt | Aggregation cannot detect this from a well-formed reference/digest; it retrieves neither | Recover from the evidence owner's verified store and independently compare contents with the bound digest. A matching reference in a passing reconciliation is insufficient. |
| Tool unavailable or gate exits nonzero after earlier work | `command_run` reports failure and stops; it has no compensating transaction | Preserve failure evidence and assess caller-command side effects. Restore compatible tools/configuration and separately authorize further work; a provider rollback does not reverse executed commands. |
| Source restored but consumer hook/workflow or required setting absent | Pure result assurance still does not verify enforcement | Reconstruct the separately recorded caller wiring and independently verify its actual execution and enforcement. This cannot be completed from provider files alone. |

## Proposed restore sequence

1. Identify the last known provider pin, caller revision/configuration, policy
   revision and tested-candidate mapping without changing the damaged state.
   Completion: an asset-by-asset available/missing inventory and preserved evidence.
2. Reconstruct provider assets separately and compare the complete file set,
   content and modes against the selected immutable source. Completion: exact
   source identity and same-revision document links, not merely parsable files.
3. Assess compatible caller restoration or the
   [migration rollback limits](integration-and-migration.md#migration-and-rollback).
   Completion: each caller input and wiring reference has a recoverable baseline;
   unsupported rollback and irreversible side effects are explicitly identified.
4. Obtain genuine policy/evidence assets from their owners. Completion: fresh
   observations, accessible reports and independently checked candidate binding
   exist; synthetic fixtures have not been substituted for lost operational data.
5. Under separate authorization, validate the isolated consumer's actual success,
   failure and recovery journeys and separately observe required enforcement.
   Completion: recorded candidate-bound results, isolation/cleanup evidence and
   verified caller wiring. Source reconstruction alone does not satisfy this step.

These steps are not execution authorization. There is no supplied consumer
recovery fixture, proven artifact-retention policy, workflow restore procedure or
verified drill duration. Evidence collection, producer trust, distribution,
consumer acceptance and enforcement remain explicit gaps; the pure aggregator's
fixed assurance cannot close them.
