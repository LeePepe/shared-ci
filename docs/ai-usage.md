# AI usage: task entry map

Use this map with the shared-ci checkout actually selected by the caller's full
commit pin. These pages are task reference material, not agent-role instructions
or execution permission. Runtime and delivery limits in the API contracts remain
in force. The [machine registry](../ai/registry.json) and
[resolver Interface](registry-resolution-contract.md) provide same-commit
discovery only, not execution or instructions authority.

## Route by task

| Task | Read when needed | Checkable handoff |
| --- | --- | --- |
| Integrate | [Integration surfaces](integration-and-migration.md#fixed-checkout-surfaces), then the applicable API contract below | Identify the provider pin, caller root, exact entrypoint/function and unresolved adapter/trust requirements. Label conceptual wiring unexecuted. |
| Change | [Architecture](architecture.md), then the affected API contract and linked source/fixtures | Tie each changed behavior to its public interface and fixture; distinguish source inspection from executed verification. Caller business facts stay in caller context. |
| Upgrade | [Compatibility](integration-and-migration.md#compatibility) and [migration](integration-and-migration.md#migration-and-rollback) | Compare old/new pins, shapes, failure semantics and caller assumptions; record a compatible rollback target and unverified cases. |
| Diagnose failure | The applicable failure section below; [disaster recovery](disaster-recovery.md) for missing/corrupt assets | Identify the failing surface, candidate/policy binding and exact observed status or finding. Separate absent evidence from a successful result. |

## API sources of truth

Integrate with discovery: select `task.integrate` and read
[admission](registry-resolution-contract.md#tool-admission) and the
[offline example](registry-resolution-contract.md#offline-consumer-example).
Change a public surface: select `task.change` and compare source parity.
Upgrade a pin: select `task.upgrade` before changing caller references.
Diagnose resolver failure: select `task.diagnose`, or read
[fixed findings](registry-resolution-contract.md#errors) directly when resolution
itself is unavailable. One-contract work may select its `doc.*` or `cap.*` ID.

| Surface | Contract and source | Failure entry |
| --- | --- | --- |
| `audit`, `resolve`, `layers`, `field`, `contexts`, `run` | [Context CLI contract](context-cli-contract.md), [`_context.py`](../scripts/context/_context.py) | [Commands and outputs](context-cli-contract.md#commands-and-outputs) for exit/stream differences; [runner](context-cli-contract.md#runner-and-containment) for gate failures. |
| `evaluate_policy` | [Policy contract](policy-validation-contract.md), [`validate.py`](../scripts/policy/validate.py) | [Deterministic failure order](policy-validation-contract.md#deterministic-failure-order-and-kinds), then [caller trust](policy-validation-contract.md#caller-trust-assumptions-and-limits). |
| `aggregate_6dq` | [Quality contract](quality-aggregation-contract.md), [`aggregate.py`](../scripts/quality/aggregate.py) | [State machine and findings](quality-aggregation-contract.md#exact-state-machine-and-findings), then [interface and trust](quality-aggregation-contract.md#interface-and-trust). |
| Committed registry resolution | [Registry contract](registry-resolution-contract.md), [`resolve.py`](../scripts/contracts/resolve.py) | [Fixed findings and precedence](registry-resolution-contract.md#errors); a repair pointer is not permission to fetch/install. |

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

Registry tests and the consumer journey are authored but NOT RUN. Read
[isolation entry conditions](registry-resolution-contract.md#isolated-verification-source-and-admission)
when planning tests/dependency loading. Static parity is not a pure-function
importer, schema-engine pass, consumer installation or required-check proof.

Demo: a docs-only PR selects no layer; see the `candidate` jobs.
