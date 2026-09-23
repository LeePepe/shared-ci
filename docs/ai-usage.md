# AI usage: task entry map

Use this map with the shared-ci checkout actually selected by the caller's full
commit pin. These pages are task reference material, not agent-role instructions
or execution permission. Runtime and delivery limits in the API contracts remain
in force. There is no machine registry or automatic document resolver here.

## Route by task

| Task | Read when needed | Checkable handoff |
| --- | --- | --- |
| Integrate | [Integration surfaces](integration-and-migration.md#fixed-checkout-surfaces), then the applicable API contract below | Identify the provider pin, caller root, exact entrypoint/function and unresolved adapter/trust requirements. Label conceptual wiring unexecuted. |
| Change | [Architecture](architecture.md), then the affected API contract and linked source/fixtures | Tie each changed behavior to its public interface and fixture; distinguish source inspection from executed verification. Caller business facts stay in caller context. |
| Upgrade | [Compatibility](integration-and-migration.md#compatibility) and [migration](integration-and-migration.md#migration-and-rollback) | Compare old/new pins, shapes, failure semantics and caller assumptions; record a compatible rollback target and unverified cases. |
| Diagnose failure | The applicable failure section below; [disaster recovery](disaster-recovery.md) for missing/corrupt assets | Identify the failing surface, candidate/policy binding and exact observed status or finding. Separate absent evidence from a successful result. |

## API sources of truth

| Surface | Contract and source | Failure entry |
| --- | --- | --- |
| `audit`, `resolve`, `layers`, `field`, `contexts`, `run` | [Context CLI contract](context-cli-contract.md), [`_context.py`](../scripts/context/_context.py) | [Commands and outputs](context-cli-contract.md#commands-and-outputs) for exit/stream differences; [runner](context-cli-contract.md#runner-and-containment) for gate failures. |
| `evaluate_policy` | [Policy contract](policy-validation-contract.md), [`validate.py`](../scripts/policy/validate.py) | [Deterministic failure order](policy-validation-contract.md#deterministic-failure-order-and-kinds), then [caller trust](policy-validation-contract.md#caller-trust-assumptions-and-limits). |
| `aggregate_6dq` | [Quality contract](quality-aggregation-contract.md), [`aggregate.py`](../scripts/quality/aggregate.py) | [State machine and findings](quality-aggregation-contract.md#exact-state-machine-and-findings), then [interface and trust](quality-aggregation-contract.md#interface-and-trust). |

Schemas and fixture pointers live in those contracts and the integration page;
this map does not redefine fields, thresholds or exception eligibility. Internal
helpers are implementation details, not additional public integration surfaces.

## Interpreting evidence

Context output describes the selected caller worktree. Policy eligibility
describes supplied facts. Quality acceptance describes supplied receipts. None
substitutes for authentic policy selection, independently trusted producers or
verified required-check configuration. The [architecture boundaries](architecture.md#modules-and-data-flow)
explain why a result cannot fill those gaps.

Existing test sources are examples of bounded synthetic verification, not
installed consumer recipes. Historical results stay attached to the scope stated
in their API contracts; separate runs are not a combined suite, full 6DQ or a
recovery drill. A useful handoff names the inspected code/contract and separates
implemented, tested, enforced and still-missing capabilities, without embedding
credentials, private operational records or product data.
