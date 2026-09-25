# Integration and migration

This development candidate exposes fixed-checkout source surfaces and, since
the repository-contract slice, reusable workflows (`quality.yml`,
`codex-review.yml`, `kimi-review.yml`, `workflow-lint.yml`) plus templates;
see the [README](../README.md#how-a-consumer-pins-it) for caller pinning. It
supplies no package installer, hook installer or verified consumer
installation. It includes a machine registry/resolver and an authored, unexecuted
consumer example. The following is integration guidance and proposed
acceptance work, not a record of installation or permission to execute it.

Selection/integrity status is recorded in the [candidate entry](../ai/README.md).
This page supplies their wiring and upgrade checklist; their own contracts
remain authoritative for API behavior and limits.

## Fixed-checkout surfaces

Keep code, schemas, API contracts and fixtures from the same full provider commit
selected outside the checkout. Consumer candidate and trusted policy revisions
are separate identities; neither is automatically the provider revision. There
is no embedded self-SHA or floating-version fallback.

### Committed registry discovery

Use [registry resolution](registry-resolution-contract.md#cli) to select a task,
document or capability from the admitted provider pin. It globally validates
consistency and returns selected committed text and identities, never caller
same-name files. Read [tool admission](registry-resolution-contract.md#tool-admission)
and the bounded [v1 distribution profile](registry-resolution-contract.md#distribution)
before execution. The [offline example](registry-resolution-contract.md#offline-consumer-example)
shows planned materialization/consumption/reference restoration; tests are NOT
RUN. Linked implementation worktrees must be separately materialized as
standalone consumer distributions for this resolver.

### Selection and integrity discovery gap

The unchanged [registry](../ai/registry.json) has 31 v1 entries. It supplies
neither a selection/integrity capability ID nor dedicated feature-contract or
failure-route IDs. Existing generic document entries may lead a reader here;
they do not provide typed discovery of these APIs. The
[resolver](../scripts/contracts/resolve.py) freezes the entry inventory and
supported interface shapes and requires `release_notes: null`, as does the
[schema](../schemas/ai-registry-v1.schema.json) for that field.

Use the same-commit Markdown routes in the [task map](ai-usage.md) for now.
A later separately reviewed provider-version/registry slice must define the
new discovery contract and update resolver/schema/fixtures consistently. Adding
JSON entries alone is not supported; the unchanged v1 contract is not evidence
that selection/integrity or release notes are machine-discoverable. Registry
execution/admission holds remain in its existing contract.

### Selection and integrity workflows

For a separately approved consumer integration:

1. Record one full provider SHA and separate caller base/head SHAs. Use the
   provider's code, docs and reusable workflows at that same SHA; retain caller
   history through the merge-base. The provider checkout is not the caller root.
2. Keep the repository's `quality` job calling the pinned `quality.yml` and
   its normal verification command. Review [selection inputs and outputs](changed-layer-selection.md#cli-and-workflow-interface)
   and [integrity inputs and outputs](test-integrity.md#workflow-integration).
   The default is full command work plus enabled integrity, not opt-in integrity.
3. If selecting layers, confirm ownership/dependencies and caller command
   handling of `CI_SELECTED_LAYERS` / `CI_SELECTION_FULL`. The
   [verify template](../templates/scripts/verify) supports `--selected`;
   shared-ci's own `scripts/verify` intentionally runs its full suite. For
   custom matrix lanes, use the [required-check-safe pattern](changed-layer-selection.md#2-required-check-safe-lanes)
   with `select.yml` at the same provider SHA. `select.yml` alone supplies no
   integrity lane or aggregate.
4. Preserve existing required-check names and trust/fork guards. Review the
   [repository contract](../ai/repo-contract.md) and [explanation requirements](test-integrity.md#comparison-and-declarations).
   Test changes alone need no Owner approval. The workflow fetches the live PR body; a standalone CLI run
   without a body does not cover that obligation. No credentials or branch
   settings changes are authorized by this checklist.
5. Verify positive and negative caller cases, then record provider SHA, caller
   head, local result, CI handles and independently observed required checks.
   Required checks must report even when command work is short-circuited.
   A synthetic fixture or provider self-test is not completed consumer rollout.

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
| Selection | Python 3.9+ stdlib and Git; optional changed-only mode, full-run fallback; workflow/CLI details in the [selection contract](changed-layer-selection.md) | Selector fixtures and provider CI are not caller matrix/required-check certification. |
| Test integrity | Python 3.9+ stdlib and Git; default-on candidate lane, loss JSON and CLI exit behavior in the [integrity contract](test-integrity.md) | Owner approval is not required merely for test changes; explanations and AI review remain. Lexical evidence does not prove semantic strength. |
| Policy | Python 3.9+, stdlib; policy input/exception v1 and finding-v1 output shape | The [bounded verification record](policy-validation-contract.md#authored-coverage-and-bounded-verification) covers 38 synthetic tests, not a packaged importer or authentic approvals. |
| Quality | Stdlib Python source, policy public-function dependency; quality input/result v1; Actions-data semantics only | The [bounded verification record](quality-aggregation-contract.md#synthetic-tests-and-execution-hold) reports Python 3.9.6 and 32 tests using a private loader, not general namespace import, CI or a runtime matrix. |
| Registry resolution | Python 3.9+ stdlib, admitted Git; standalone detached nonshallow SHA-1 Git-source distribution; registry/result/finding v1 | Isolated parity, negative and bundle-consumer test source authored; NOT RUN. No schema-engine/runtime matrix evidence. |
| Distribution and enforcement | Source checkout and reusable workflow source | No candidate release, wheel/sdist contract or installed consumer certification follows. Provider PR checks do not establish consumer rollout or required-check enforcement. |

Schema version 1 is not a library release number. No release/deprecation schedule
or broader platform support matrix is declared. Schema documents describe
structure; runtime checks include semantics a JSON Schema engine cannot express.
Compatibility therefore requires both schema and behavioral comparison, not
just matching a version integer.

Older pins keep their existing behavior. On this candidate, `changed-only:
false` preserves full command work but does not disable the new default-on
integrity gate. That combined behavior is an adoption change requiring the
Owner decision, not an assertion of backward policy compatibility.

## Existing fixtures and evidence

These are real test sources to inspect, not executions performed by this guide:

| Source | Useful scenario | Limit |
| --- | --- | --- |
| [Context fixture](../tests/context/fixture.py), [resolution tests](../tests/context/test_resolution.py), [CLI tests](../tests/context/test_cli_contract.py) | Disposable Git callers, nearest-owner routes, exclusions, manifest drift, exact output/exit behavior | Fixtures create synthetic metadata and sanitize child environments; the production CLI does not do that sanitization. |
| [Runner tests](../tests/context/test_runner.py) | Gate selection, empty expansions, containment, invalid UTF-8 and child failures | Fixture-owned probes/sentinels, not product commands or a hostile-code sandbox. |
| [Fixture-hook regression](../tests/context/test_fixture_hooks.py) | Git honors a fixture-local `post-index-change` hook without changing parent/source state | Not a consumer pre-commit/pre-push installer or required-gate demonstration. |
| [Selector tests](../tests/select/test_select.py), [gate tests](../tests/quality/test_gate.py) | Whole-PR selection, fallback and aggregate/short-circuit rules | Synthetic callers and supplied lane outcomes, not consumer matrix execution or remote enforcement. |
| [Integrity tests](../tests/quality/test_test_integrity.py) | Unexplained loss negatives; explanation-without-Owner positives; movement/reformatting, comment/literal context and quoted paths | Isolated Git fixtures, not semantic proof or real-consumer adoption. |
| [Policy tests](../tests/policy/test_validation.py) | Exact pins and literal paths, weaker rules, complete approvals, expiry and unknown observations | Explicit source read/compile loader; synthetic external records do not establish approval authenticity. |
| [Quality tests](../tests/quality/test_aggregation.py) | `fixture()` supplies six dimension receipts; tests cover mismatched binding, missing evidence, finite predicates and isolation observations | Private loader calls the actual policy evaluator; synthetic no-I/O records do not execute six workloads or prove isolation. |
| [Registry isolation](../tests/contracts/test_isolation.py), [behavior](../tests/contracts/test_resolution.py), [schema consistency](../tests/contracts/test_registry_consistency.py) | External-envelope refusal/concurrency/cleanup; all selections/negatives; wrapper/direct parity; bundle consumption/restoration; offline schema validation | Separate stages, NOT RUN. Independent source/D1 review precedes behavior; no ambient dependencies, real caller or pure-function importer. |

Historical local runs remain separate evidence for their stated scopes. They
are not a combined suite, four-metric coverage, a consumer migration or full 6DQ.
Any future execution needs its own authorization and isolation review; commands
and execution conditions remain in the API contracts.

The provider's normal `scripts/verify` includes selector/gate/integrity tests;
PR bodies and check runs bind their executed results to a tested head. This
does not include the separately admitted registry suites or supply a released
provider SHA, real-consumer positive/negative runs, adoption or release notes.

## Migration and rollback

### Selection and integrity upgrade

No actual candidate consumer upgrade or rollback is demonstrated here. For a
separately authorized adoption:

1. Record the old full provider pin, caller head, verification commands and
   required-check names. Resolve provider implementation review and merge/release
   sequencing before selecting an adoption target. A candidate SHA is not a
   fabricated release revision.
2. Compare the two feature contracts at old/new pins using the compatibility
   table above. Inventory expected explanation failures and the
   chosen selection mode. Completion means every behavioral difference is
   accepted by its owner or retained as a blocker.
3. Change workflow pins and repository metadata together in one reviewed PR.
   Route AGENTS to its guide; move details out of the index, preserve guide
   CODEOWNERS protection and set review callers' `rules-file` to that guide.
   Update verify bootstrap to read metadata (legacy fallback when absent). Follow the
   workflow checklist above, preserving check names. Do not retire a caller
   safeguard based only on the presence of the new lane.
4. On the actual old/new provider and caller revisions, verify unchanged-test
   and reformatting positives, undeclared assertion/test/skip negatives,
   explanations without Owner/ledger, Unicode-path skips, and selection fallback
   and docs-only required-check reporting. Retain exact-head local/CI evidence;
   ordinary AI review still evaluates intended test behavior changes.
5. Record the compatible rollback pin and configuration. Roll back by a
   reviewed revert of caller references/configuration together, then reverify;
   do not rewrite provider tags or silently disable integrity. Returning to an
   older gate is not equivalent policy enforcement and needs Owner review.

Release notes, real-consumer evidence and the provider-version/registry update
remain separate obligations. This checklist neither publishes nor adopts them.

### Existing context and registry migration

The registry slice's narrower planned journey restores a run-owned synthetic
caller provider/revision tuple, retaining separate old/new distributions. It
does not replace actual caller migration below, prove full recovery or undo
gate effects. Schema 1 is not a release; `release_notes: null` leaves release
obligations outstanding.

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
