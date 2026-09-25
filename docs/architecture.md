# Architecture

This page describes the source modules in this checkout. Their responsibilities
are conceptual boundaries, not installed layer metadata, canonical agent roles
or a new policy. The repository contains no product ownership table or root
`CONTEXT.md`; ownership and gate declarations are supplied by each caller.

## Modules and data flow

| Surface | Inputs and processing | Output and dependency |
| --- | --- | --- |
| [Context entrypoints](../scripts/context/) | Shell wrappers invoke `_context.py`; `repo_root` discovers the caller worktree through Git. `parse_context`, `resolve` and `audit` read its context graph, tracked paths and optional manifests. | Resolution/metadata on stdout and structured findings on stderr; stdlib, Git and shell. `command_run` can execute caller-declared argv. |
| [Policy evaluator](../scripts/policy/validate.py) | `evaluate_policy` validates native baseline/candidate/approval/observation data, compares rules and checks complete exception records. | Eligibility, first finding and applied IDs; only `datetime` and `re`. No I/O or issuer. |
| [Quality aggregator](../scripts/quality/aggregate.py) | `aggregate_6dq` validates expectation/evidence, calls the public policy evaluator, checks mappings and reconciles receipts. | Six dimension states, required acceptance, findings and fixed assurance; imports policy plus `datetime` and `re`. No workload execution. |
| [Layer selector](../scripts/select/layers.py) | PR diff (merge-base..head), event and caller force-full patterns; loads the context engine to resolve each path and read `depends_on`. | JSON selection (layers + dependents, or a fail-closed full run) and Actions outputs; stdlib and Git. See [changed-layer selection](changed-layer-selection.md). |
| [Registry resolver](../scripts/contracts/resolve.py) | One CLI takes admitted Git, full revision and entry ID; validates the provider's committed registry, resources and public interfaces. | Selected closure with blob/mode/digest identities; stdlib and Git; static AST inspection without context/policy/quality imports. |

The only cross-module runtime import is aggregation → policy. Context does not
invoke either pure function, and aggregation does not invoke the context runner.
A caller adapter connecting these surfaces is not supplied. JSON schemas describe
data, not runtime imports or a general schema-validation engine.

### Context: caller worktree to resolution or execution

[`_context.py`](../scripts/context/_context.py) starts at the caller's root
`CONTEXT.md`, follows index routes to the nearest leaf or a reasoned exclusion,
and checks path containment. `audit` also reconciles tracked-file ownership,
dependency relationships and the supported textual manifest forms. It does not
audit untracked files. The graph/schema and manifest limitations belong to the
[context contract](context-cli-contract.md#context-documents-and-ownership).

For `run`, declared gates are selected by layer, mode and optional gate ID.
All selected argv are preflighted before execution; expansion uses tracked,
owned Python paths. The child cwd is the caller root. This is a trusted-command
runner, not a process sandbox: environment, PATH, option-encoded paths and child
behavior remain caller responsibilities. Full containment, expansion and exit
semantics are in the [runner contract](context-cli-contract.md#runner-and-containment).

### Policy: supplied facts to eligibility

[`evaluate_policy`](../scripts/policy/validate.py) does not discover rules from
context documents. Its caller supplies the immutable baseline, exact subject,
candidate rules, external approval records and current observations. It checks
eligibility against those supplied records; it cannot authenticate them. Literal
policy paths are not context globs. See [path semantics](policy-validation-contract.md#literal-utf-8-path-semantics)
and [caller trust assumptions](policy-validation-contract.md#caller-trust-assumptions-and-limits)
before building an adapter.

### Quality: supplied receipts to finite reconciliation

[`aggregate_6dq`](../scripts/quality/aggregate.py) first validates inputs and
policy cases, then expected mappings and supported semantics, then observed
bindings and checks. Its `actions` phase is a data label, not an Actions workflow.
Hook phases are unsupported. D1 reconciles isolation observations, including
cross-run coverage; it neither creates isolation nor performs cleanup. D1 means
test isolation, not documentation.

`required_acceptable` is a reconciliation result, not authentication or shipping
permission. Assurance remains `authenticity: not_verified`,
`enforcement: not_verified`, `ship: not_assessed`, even if supplied receipts claim
remote enforcement. The [quality contract](quality-aggregation-contract.md#exact-state-machine-and-findings)
is authoritative for precedence, advisory results and fallback behavior.

## Assets and boundary ownership

- [Schemas](../schemas/) describe context, finding, policy, quality and registry
  v1 shapes. Registry also defines closed result/finding shapes. Semantic
  validation stays in the corresponding implementation; lexical integers,
  ordering, graph/resource and parity checks extend structural schema checks.
- [Context fixtures](../tests/context/fixture.py) construct disposable caller
  repositories; [policy tests](../tests/policy/test_validation.py) and
  [quality tests](../tests/quality/test_aggregation.py) supply synthetic records.
  Their loaders and boundaries are described in [integration](integration-and-migration.md#existing-fixtures-and-evidence).
- Callers retain business semantics, layer paths, gate commands, policy trust,
  evidence production and remote enforcement. Restoring this source alone cannot
  restore those assets; see [recovery boundaries](disaster-recovery.md#assets-and-recovery-boundaries).

No installed caller, reusable workflow, package release or full quality
certification follows from these modules or this descriptive architecture.

## Registry: provider commit to selected contracts

The resolver is a deep module with one small Interface: `--git`, `--revision`,
`--entry`. It hides literal Git-object traversal, containing-commit binding,
global consistency, resource identity and selection closure. Callers own
tool/source admission, pin selection and distribution materialization.
[Revision binding](registry-resolution-contract.md#revision-binding) explains
why caller decoys and dirty document files cannot select content.

This seam differs from context's caller-worktree resolution. Resolver isolation
does not change caller/index behavior, and no adapter imports or authenticates
policy/quality inputs. Test helpers are an internal seam with external envelope
admission. Read [verification entry conditions](registry-resolution-contract.md#isolated-verification-source-and-admission)
when reviewing setup, dependency loading or cleanup. Isolation-only execution
precedes separate behavior/schema stages. New tests are NOT RUN.
