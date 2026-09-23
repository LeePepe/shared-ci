# Integration and migration

This development candidate exposes fixed-checkout source surfaces. It supplies
no package installer, reusable workflow, hook installer, machine registry or
verified consumer launcher. The following is integration guidance and proposed
acceptance work, not a record of installation or permission to execute it.

## Fixed-checkout surfaces

Keep code, schemas, API contracts and fixtures from the same full provider commit
selected outside the checkout. Consumer candidate and trusted policy revisions
are separate identities; neither is automatically the provider revision. There
is no embedded self-SHA or floating-version fallback.

### Context CLI

The six [shell wrappers](../scripts/context/) invoke `python3` from PATH. Python
3.9+, Git, POSIX shell and UTF-8 stdio are the declared prerequisites in the
[context contract](context-cli-contract.md#provenance-and-scope). The working
directory selects the caller's Git worktree, while the wrapper path selects the
provider implementation. Root-relative file arguments refer to the caller.

Illustrative, unexecuted shell wiring; paths are placeholders, and the caller
must already contain valid context documents and a mapped path:

```sh
cd /path/to/consumer-checkout
/path/to/pinned-shared-ci/scripts/context/resolve src/example.py --format json
/path/to/pinned-shared-ci/scripts/context/audit
```

A uniquely mapped `resolve` emits a resolution and exits 0. A clean `audit`
emits its JSON summary and exits 0; findings produce status 1. General context
errors and argument parsing have distinct behavior; use the
[complete command table](context-cli-contract.md#commands-and-outputs).

The engine preserves caller Git environment, including intentional index
selection. This does not implement staged/index or pushed-ref hooks. Its
`git ls-files --cached` enumeration is not proof that executed file contents
match the index. Before any proposed `run` wiring, review caller gate argv,
environment and the [trusted-runner limits](context-cli-contract.md#runner-and-containment).

### Pure functions

[`evaluate_policy`](../scripts/policy/validate.py) takes four required native-data
keyword arguments. [`aggregate_6dq`](../scripts/quality/aggregate.py) takes two
and imports `scripts.policy.validate.evaluate_policy`. Neither file provides a
CLI or JSON decoder. An importer must establish that the `scripts` namespace
resolves exclusively to the reviewed provider tree; ordinary namespace-import
integration has not been verified by the private source-loading test harnesses.

Illustrative, unexecuted Python call shape, not a standalone recipe. Function
objects are assumed to have been loaded by a separately reviewed importer;
variables stand for complete caller-supplied data conforming to the contracts:

```python
eligibility = evaluate_policy(
    baseline=baseline, candidate=candidate,
    approvals=approvals, observation=observation,
)
quality = aggregate_6dq(expectation=expectation, evidence=evidence)
```

Successful eligibility has `eligible=true`; quality uses `required_acceptable`
with unchanged assurance, not an exit code or authorization. Decoding, authentic
baseline/approval selection, fresh observations and trusted receipt production
belong to the caller. Exact shapes, strict decoding requirements and unsupported
cases are defined only in the [policy](policy-validation-contract.md) and
[quality](quality-aggregation-contract.md) contracts. A valid policy exception
can still require semantics unsupported by aggregation.

## Compatibility

| Surface | Declared/source scope | Evidence boundary |
| --- | --- | --- |
| Context CLI | Python 3.9+, stdlib, Git, POSIX shell; context/finding v1 | Synthetic worktree, routing and subprocess fixtures exist. No cross-platform consumer certification is established here. |
| Policy | Python 3.9+, stdlib; policy input/exception v1 and finding-v1 output shape | The [bounded verification record](policy-validation-contract.md#authored-coverage-and-bounded-verification) covers 38 synthetic tests, not a packaged importer or authentic approvals. |
| Quality | Stdlib Python source, policy public-function dependency; quality input/result v1; Actions-data semantics only | The [bounded verification record](quality-aggregation-contract.md#synthetic-tests-and-execution-hold) reports Python 3.9.6 and 32 tests using a private loader, not general namespace import, CI or a runtime matrix. |
| Distribution and enforcement | Source checkout only in this tree | No wheel/sdist contract, released version, installed workflow/hook or verified remote required check. |

Schema version 1 is not a library release number. No release/deprecation schedule
or broader platform support matrix is declared. Schema documents describe
structure; runtime checks include semantics a JSON Schema engine cannot express.
Compatibility therefore requires both schema and behavioral comparison, not
just matching a version integer.

## Existing fixtures and evidence

These are real test sources to inspect, not executions performed by this guide:

| Source | Useful scenario | Limit |
| --- | --- | --- |
| [Context fixture](../tests/context/fixture.py), [resolution tests](../tests/context/test_resolution.py), [CLI tests](../tests/context/test_cli_contract.py) | Disposable Git callers, nearest-owner routes, exclusions, manifest drift, exact output/exit behavior | Fixtures create synthetic metadata and sanitize child environments; the production CLI does not do that sanitization. |
| [Runner tests](../tests/context/test_runner.py) | Gate selection, empty expansions, containment, invalid UTF-8 and child failures | Fixture-owned probes/sentinels, not product commands or a hostile-code sandbox. |
| [Fixture-hook regression](../tests/context/test_fixture_hooks.py) | Git honors a fixture-local `post-index-change` hook without changing parent/source state | Not a consumer pre-commit/pre-push installer or required-gate demonstration. |
| [Policy tests](../tests/policy/test_validation.py) | Exact pins and literal paths, weaker rules, complete approvals, expiry and unknown observations | Explicit source read/compile loader; synthetic external records do not establish approval authenticity. |
| [Quality tests](../tests/quality/test_aggregation.py) | `fixture()` supplies six dimension receipts; tests cover mismatched binding, missing evidence, finite predicates and isolation observations | Private loader calls the actual policy evaluator; synthetic no-I/O records do not execute six workloads or prove isolation. |

Historical local runs remain separate evidence for their stated scopes. They
are not a combined suite, four-metric coverage, a consumer migration or full 6DQ.
Any future execution needs its own authorization and isolation review; commands
and execution conditions remain in the API contracts.

## Migration and rollback

The first migration direction is caller-local copied context scripts → an
explicitly pinned shared checkout. [Provenance](context-cli-contract.md#provenance-and-scope)
identifies the extracted engine; this is not proof that an arbitrary caller copy
is compatible. No actual consumer migration or rollback has been demonstrated
by this document.

Proposed sequence for a separately authorized migration:

1. Inventory the old caller scripts, invocation paths, context graph, gate argv,
   Git environment, tool versions and any local changes. Completion: a fixed old
   baseline and a list of behavior differences, including local policy exceptions.
2. Compare that baseline with all applicable contracts at the selected provider
   pin. Keep product facts in the caller; explicitly represent existing external
   dependencies using the supported [manifest metadata](context-cli-contract.md#caller-owned-manifests-and-dependency-policy).
   Completion: each old behavior maps to a supported interface or an explicit gap.
3. Propose a thin caller reference to the pinned wrappers; for policy/quality,
   separately design the importer, decoding and trusted-data adapter. Completion:
   every source/document reference is pinned and every trust input has an owner.
4. In an authorized isolated consumer, verify positive and negative behavior
   against its actual acceptance inventory, including missing docs, wrong pin,
   rule weakening, expired approvals and failure propagation. Completion: results
   bind to the selected provider and consumer candidates; unsupported integration
   remains a gap rather than a fabricated passing fixture.
5. Compare the proposed required/advisory wiring with independently observed
   enforcement. Completion: local behavior, CI execution and remote enforcement
   have separate evidence before copied implementation is retired.

Rollback means reverting caller references and compatible caller configuration
to the recorded old baseline as one reviewed change, including any importer.
Uninstalling a source reference has no supplied uninstall command. Caller hook
or remote settings, if added separately, require their own reversal and review.
Source rollback cannot undo child-command side effects, restore lost artifacts,
renew expired approvals or make old receipts valid for a new candidate. A prior
version lacking policy/quality semantics is not an equivalent enforcement
fallback. Where compatibility or prior state is missing, recovery is incomplete;
use the [recovery plan](disaster-recovery.md), not a silent floating ref.
