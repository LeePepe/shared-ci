# Orphan test reachability contract (v1)

This contract defines the shared, fail-closed check that makes every adopting
repository account for every test file in pull-request CI. It is the feature
specification for MY-1608. The contract-document pull request is reviewed and
merged before any implementation task below starts.

The check proves declared file-level reachability from committed repository
facts. It does not prove that an individual test case ran, that a test did not
self-skip, or that a server ruleset actually requires a named check. Those
separate evidence boundaries remain explicit below.

## Actors and outcome

- A repository maintainer declares test inventory, discovery and justified
  exceptions in the repository's protected context map.
- The Context audit classifies every tracked candidate test file as reached,
  deliberately excluded or a non-test false positive.
- The reusable quality workflow runs the audit on the pull-request head and the
  required aggregate accepts it only with an explicit current-head pass.
- A reviewer can identify an orphan from one finding containing its literal
  repository-relative path and a stable reason.

After adoption, adding a test-shaped file without a qualifying pull-request
gate makes CI fail instead of silently leaving the file unexecuted.

## Stable requirements and acceptance criteria

| ID | Requirement / acceptance criterion |
| --- | --- |
| FR-001 | The contract-document PR containing this specification and its repository-guide link receives exact-revision review and merges before implementation begins. |
| FR-002 | An adopting repository declares one versioned test-reachability policy in its root context index or root `tech-context.md`, while layer-owned `test_paths` and test gates remain the authority for per-layer discovery. |
| FR-003 | The audit inventories Git-tracked regular files using the closed `default-v1` patterns plus explicit includes; repository names are never hard-coded. |
| FR-004 | Every candidate file has exactly one terminal classification: reached by at least one qualifying gate, explicitly excluded with a reason, or explicitly classified as a non-test with a reason. Missing or contradictory classification fails closed. |
| FR-005 | A gate qualifies only when a selected, non-`continue-on-error` pull-request command lane invokes the pinned provider's canonical required-gate executor for that lane, the executor runs every declared gate mapped to it, and `quality / aggregate` reconciles the lane's success, `ran: true` and expected head SHA. Manual, release-only, local-only, build-only, advisory, unrelated-command or nonaggregate lanes do not count. |
| FR-006 | Static, versioned discovery adapters cover SwiftPM test targets, XcodeGen/Xcode test schemes, pytest, unittest, `node --test`, Vitest, Ruby and shell suites. Unknown, dynamic or ambiguous discovery fails closed unless represented by the explicit reviewed-literal adapter. |
| FR-007 | An orphan produces a deterministic finding containing the literal file path and reason; the command exits nonzero. A tree in which all candidates are reached or explicitly excepted exits zero. |
| FR-008 | Default helper names do not become candidates. Other false positives, including a test-shaped tool such as `scripts/quality/test_integrity.py`, require a visible reasoned non-test entry. Deliberately non-PR suites require a distinct visible exclusion. |
| FR-009 | Unit and integration tests cover an orphan, a `workflow_dispatch`-only mapping, honoured discovery globs, a reasoned exclusion, helper/non-test handling, malformed declarations, exact and false gate-to-lane bindings, and stale/current-head aggregate results. |
| FR-010 | The reachability check is separate from test-integrity: reachability covers the head tree's file-to-required-gate graph; test-integrity continues to cover assertion/test loss and PR-body rationale across a diff. Both may block the aggregate. |
| FR-011 | Shared-ci adopts the released provider on itself, changes brittle per-file native discovery to suite discovery, declares `tests/contracts/**` as deliberately outside native PR verification, and passes the required current-head checks. |
| FR-012 | The reviewed implementation is released at an immutable tag/full SHA. Follow-up adoption issues are filed or linked for VoxPocket, agent-skills, shared-design-tokens, shared-design-system, shared-telemetry, VitalStride and AIDash. |
| FR-013 | Every feature PR is non-Draft, uses the repository's declared work unit, preserves required approvals, and has green required checks on its exact head SHA. |
| FR-014 | Engines remain stdlib-only Python 3.9+, Git and POSIX shell. The audit does not execute tests, manifests, package code or PR-head scripts and does not read the network. |

## Existing behaviour

At the baseline revision `9a66e2d16d07703ea84ffd01dd60704422b7cde0`:

- Context audit checks tracked-path ownership, layer dependencies, context
  declarations and the repository contract. It does not evaluate test
  reachability.
- Legacy context-v1 `test_paths` provides test ownership and `{test_paths}`
  command expansion. The simplified `tech-context.md` adapter currently emits
  no `test_paths`, and neither format treats a path declaration as execution
  evidence.
- `quality / aggregate` reconciles its selected workflow lanes and current-head
  SHA. No lane supplies a file-level test-reachability result.
- Test-integrity detects recognized test/assertion losses in a pull-request
  range. Its contract explicitly does not claim reachability analysis.
- Shared-ci's `scripts/verify` hand-lists suite directories, then names Quality
  and Policy tests per file. `tests/contracts/**` is deliberately not part of
  native verification. A new matching file can therefore be silently omitted.
- Repositories that do not call the reusable quality workflow have no shared
  aggregate route for this check.

## Decision and rejected alternatives

The selected design combines a small root policy with existing layer facts:

1. The root policy selects the closed default inventory, explicit includes,
   required aggregate lanes, non-tests and deliberate exclusions.
2. Each layer's existing `test_paths` owns its candidate test files.
3. Each qualifying `kind: test` gate adds versioned `reaches` metadata that
   describes its static discovery adapter. Its `aggregate_lane` is an executable
   binding to the pinned provider's canonical Context dispatcher, not a claim
   inferred from an arbitrary workflow command.
4. The Context module normalizes legacy `CONTEXT.md` and simplified
   `tech-context.md` inputs and hides framework-specific parsing behind one
   audit interface.

This seam keeps the public declaration smaller than a second, independent test
manifest while avoiding inference from arbitrary shell strings.

The following alternatives are rejected for v1:

- Defaults plus current gate commands only: arbitrary wrappers and dynamic
  framework configuration cannot be inferred reliably, and source presence is
  not proof of a pull-request aggregate route.
- A standalone root manifest duplicating all layer paths and commands: it is
  expressive but creates a second ownership graph that can drift from Context.
- Running gates in collect-only mode: the named frameworks have no common
  side-effect-free collector; Swift/Xcode manifests and custom runners can
  execute code, require unavailable toolchains or diverge from the real gate.

Collect-only evidence may be proposed later under a separate reviewed contract.

## Declaration interface

The normalized shape below is illustrative YAML. The context-v1 JSON schema
defines the exact closed shapes and bounds; the simplified adapter accepts the
same facts in YAML frontmatter.

```yaml
# root CONTEXT.md index or docs/architecture/tech-context.md
test_reachability:
  version: 1
  inventory:
    defaults: default-v1
    include: []
  required_gates:
    - layer: Quality
      gate: unit
      aggregate_lane: verify
  non_tests:
    - patterns: [scripts/quality/test_integrity.py]
      reason: "Quality engine whose filename describes its subject; not a test file."
  exclusions:
    - patterns: [tests/contracts/**]
      reason: "Registry fixtures use the separately admitted verification process."

# scripts/quality/tech-context.md
test_paths: [tests/quality/**]
gate:
  unit:
    kind: test
    mode: ci
    command:
      - python3
      - -I
      - -B
      - -m
      - unittest
      - discover
      - -s
      - tests/quality
      - -p
      - test_*.py
    reaches:
      - adapter: python-unittest-v1
```

### Root policy

- `version` is integer `1`; unknown versions fail closed.
- `inventory.defaults` is exactly `default-v1`. The default set cannot be
  weakened or replaced by caller patterns.
- `inventory.include` adds nonstandard test globs. It does not establish reach.
- `required_gates` contains unique `(layer, gate, aggregate_lane)` records. A
  referenced layer, gate and reusable Quality command lane must exist. For each
  named lane, the caller's corresponding `<lane>-command` is exactly
  `.shared-ci/scripts/context/run-required --lane <lane> --mode ci`, using the
  same full-SHA provider checkout as the reusable workflow.
- `aggregate_lane` is executable, not descriptive. Dynamic expressions,
  prefixes or suffixes, shell operators, aliases, local wrappers, caller-supplied
  alternate gate lists and asserted receipts fail source admission. An unrelated
  successful command never establishes the binding.
- `non_tests` classifies default/include matches that are not tests. Every entry
  has nonempty patterns and a substantive reason. It cannot overlap an
  `exclusions` entry or a reached file, and a stale entry matching no candidate
  is a finding.
- `exclusions` is only for real tests deliberately outside PR CI. Every entry
  has nonempty patterns and a substantive reason. It remains visible in the
  audit summary; exclusion is never reported as reach.
- The root policy lives in the CODEOWNERS-protected context map. Moving either
  exception class to an unprotected side file is not supported.

### Layer policy

- `test_paths` retains its current ownership/search-scope meaning. A default or
  included candidate outside the owning layer's `test_paths` is a finding; a
  caller cannot hide it by omitting it from the declaration.
- Simplified gate string/list syntax and existing context-v1 gates remain valid
  but prove no reachability by themselves.
- An object-form gate that claims reach has `kind: test`, `mode: ci|both`, a
  nonempty argv command and one or more `reaches` records.
- `reaches.adapter` is a known, versioned adapter. Its extra keys are closed by
  adapter kind. Unknown fields, adapter versions or dynamic inputs fail closed.
- A reach selector may return only tracked files within that layer's
  `test_paths`. Cross-layer or outside-root results fail before set comparison.

### Default-v1 candidate patterns

Matching uses Git-relative POSIX paths and the Context glob rules. The contract
uses extension families below; the schema/runtime owns their exact expansion.

| Ecosystem | Default-v1 candidates |
| --- | --- |
| Python | `**/test_*.py`, `**/*_test.py` |
| Swift / XCTest / Swift Testing | `**/*Test.swift`, `**/*Tests.swift` |
| JavaScript / TypeScript | `**/*.test.{js,jsx,mjs,cjs,ts,tsx,mts,cts}`, `**/*.spec.{js,jsx,mjs,cjs,ts,tsx,mts,cts}`, supported source files below `**/__tests__/**` |
| Ruby | `**/test_*.rb`, `**/*_test.rb`, `**/*_spec.rb` |
| Shell | `**/test_*.{sh,bash,zsh}`, `**/*_test.{sh,bash,zsh}`, `**/*.bats` |
| Go | `**/*_test.go` |
| JVM | `**/*Test.java`, `**/*Tests.java`, `**/*Test.kt`, `**/*Tests.kt` |

Exact helper basenames `__init__.py`, `conftest.py`, `fixture.py`,
`fixtures.py`, `helper.py`, `helpers.py`, `helper.sh`, `helpers.sh`,
`helper.bash`, `helpers.bash`, `helper.zsh` and `helpers.zsh` are not candidates
unless an explicit include names them. Repository-specific tools whose names
still match the defaults use a reasoned `non_tests` entry rather than a hidden
repository-name exception.

## Discovery adapters

All adapters are internal seams of the Context module. They read only admitted,
tracked local files and literal configuration; they do not run a collector.

| Adapter | Static mapping |
| --- | --- |
| `swiftpm-v1` | `swift test --package-path <root>` reaches tracked sources of literal SwiftPM `testTarget` declarations below that package. Dynamic manifest expressions fail closed. |
| `xcodegen-v1` | `xcodebuild test -scheme <name>` reaches source globs of test targets named by the scheme's test action in the supported `project.yml` subset. `xcodebuild build` never qualifies. |
| `python-unittest-v1` | Parses literal `unittest discover` start directory and pattern using Python discovery semantics. |
| `pytest-v1` | Parses literal roots and supported literal `python_files`/test path configuration. Plugin-provided or dynamic discovery fails closed. |
| `node-test-v1` | Applies supported `node --test` literal paths/globs and documented default naming. |
| `vitest-v1` | Applies supported literal include/exclude arrays. Dynamic JavaScript configuration fails closed. |
| `ruby-v1` | Applies literal runner paths/globs declared by the test gate. Opaque runtime-generated lists fail closed. |
| `shell-v1` | Reaches only literal executable test paths/globs declared by the gate; merely invoking an opaque wrapper is insufficient. |
| `declared-glob-v1` | Escape hatch for a protected custom runner manifest containing literal globs, a source path and a substantive reason. It cannot point at generated/untracked data or assert an opaque command's behaviour. |

Adding a framework means adding one reviewed adapter and fixtures behind the
same interface; callers do not receive a new execution mechanism.

## Reachability and gate qualification

For each candidate path, the audit evaluates in this order:

1. Validate declaration shapes, UTF-8, paths, unique IDs and adapter versions.
2. Enumerate the sorted Git-tracked regular-file inventory.
3. Apply defaults and explicit includes, then helper/non-test classification.
4. Resolve each remaining candidate to exactly one layer and `test_paths` set.
5. Admit required gates and their exact canonical lane bindings from source
   configuration.
6. Expand each static discovery adapter and reject scope escapes.
7. Apply reasoned deliberate exclusions as an alternate terminal state.
8. Report every unclassified or contradictory path in literal path order.

A gate is qualifying only when all of these facts hold:

- the referenced context gate is `kind: test` and `mode: ci|both`;
- a caller workflow triggered by `pull_request` selects the referenced command
  lane and its exact command invokes `run-required` for that same lane;
- `run-required` loads the audited root policy, preflights the whole mapped set,
  and delegates every normalized `(layer, gate)` argv to the existing Context
  runner in declaration order; empty, extra, duplicate, wrong-lane or
  mode-incompatible mappings fail before any gate executes;
- the lane is not `continue-on-error`, release/manual-only or job-level skipped;
- the lane's result and tested SHA are reconciled by `quality / aggregate`;
- runtime evidence for the pull request reports that the lane actually ran.

`workflow_dispatch`, scheduled, release and TestFlight workflows never establish
reachability. A test built or compiled by an Xcode build action is not reached;
the scheme must be used by `xcodebuild test`.

Source inspection establishes the committed route into the aggregate. It does
not prove that GitHub currently requires `quality / aggregate`; adoption evidence
must include fresh server ruleset/check readback and exact-head CI evidence.

## Findings and command behaviour

The check extends Context audit's finding-v1 envelope. Stable kinds are:

- `invalid_test_declaration`
- `unowned_test`
- `unqualified_test_gate`
- `unsupported_test_discovery`
- `reach_outside_test_paths`
- `invalid_test_exception`
- `orphan_test`

An orphan finding names the literal file and one stable reason, for example
`no matching test gate`, `gate is workflow_dispatch only`, `gate is not in the
required aggregate`, `lane command is not the canonical dispatcher`, or
`discovery does not include this file`. Findings and summaries never claim that
excluded tests ran.

The test-specific audit returns 0 only when every candidate has one valid
terminal classification, 1 for findings and 2 for CLI usage errors, consistent
with the Context CLI. Invalid declarations are findings and fail CI. Missing,
malformed, skipped, stale-SHA or nonpass workflow results are never accepted as
a pass.

## Workflow placement and relationship to existing checks

The Context module owns inventory, normalization, adapter expansion, findings and
the canonical `run-required` dispatcher. The dispatcher is a deep module over the
existing Context runner seam: it accepts only a lane and mode, reads the same
root policy, preflights the full mapped set, and executes no caller-supplied gate
list. The read-only reachability audit never executes caller code.

The reusable quality workflow owns orchestration and aggregate admission; Quality
does not import Context Python code, so the declared `Quality -> Policy`
dependency is unchanged.

The first provider release adds an `orphan-test-check` boolean workflow input
with default `false` for pin-compatible rollout. When `true`:

- a dedicated hosted lane checks out the caller head and pinned provider;
- it runs the test-specific Context audit without executing caller code;
- it reports the tested head SHA, `ran: true` and the sorted set of admitted
  required command lanes;
- every admitted command lane checks out that same pinned provider, is forced to
  run despite changed-layer short-circuiting, and uses the exact `run-required`
  invocation admitted above;
- aggregate depends on the audit and admitted command lanes and requires each to
  report explicit success, `ran: true` and the expected SHA.

There is no advisory pass state. Disabled means not adopted; enabled means
blocking. A future default-on change requires a separate reviewed contract after
supported callers migrate.

Test-integrity remains independently selected and blocking. Reachability answers
"which required PR gate discovers this file at the head?" Test-integrity answers
"did this PR remove/weaken recognized test evidence without a per-file reason?"
Passing either one cannot substitute for the other.

Repositories without `quality.yml` are not covered by a manual side job. They
must first adopt the reusable quality aggregate (or a separately reviewed
equivalent that preserves the same lane/current-SHA contract) and make that
aggregate required before claiming orphan-test adoption.

## Compatibility

- Existing consumers remain on their full-SHA provider and do not acquire this
  behaviour retroactively.
- The first release preserves legacy gate string/list syntax and existing
  context-v1 meanings. Simplified `test_paths`, gate objects and the root policy
  are additive declarations.
- `orphan-test-check` defaults false. Enabling it without a complete declaration
  fails closed; it never silently infers a partial policy.
- Existing free-form command inputs remain valid while the check is disabled.
  Once enabled, every lane named by `required_gates` must use the exact canonical
  pinned-provider dispatcher invocation; an arbitrary successful command is not
  backward-compatible reachability evidence.
- Rollback restores the previous exact provider pin and caller declaration. It
  does not rewrite a tag, waive test coverage or turn old evidence into evidence
  for a new head.
- Finding-v1 output remains the envelope; new finding kinds are additive.

## Removed behaviour

Enabling the check deliberately removes acceptance of:

- a test-shaped tracked file with no declared qualifying gate;
- a file reached only by `workflow_dispatch`, schedule, release or TestFlight;
- an Xcode test bundle that is built but never tested;
- an advisory, `continue-on-error`, skipped or nonaggregate lane as evidence;
- a passing command lane that does not invoke the admitted pinned-provider
  dispatcher for its declared lane;
- a reasonless, stale or overlapping non-test/exclusion entry;
- an opaque or dynamic discovery claim that no supported adapter can verify.

This plan removes or weakens no existing test, assertion, gate or policy.
`tests/contracts/**` remains deliberately outside native shared-ci verification
under its existing separate-admission contract and becomes visible as an
exclusion; it is not reclassified as reached. Test-level skips, quarantined
cases and environment-gated cases inside a reached file remain unchanged and
out of scope.

## Architecture, paths and prohibitions

| Area | Planned paths | Interface / responsibility | Prohibitions |
| --- | --- | --- | --- |
| Docs/spec support | `docs/orphan-test-contract.md`, `docs/repository-guide.md`, later `docs/context-cli-contract.md` and `docs/architecture.md` | Normative feature and Context interface documentation | No implementation in the contract-document PR |
| Schemas | `schemas/context-v1.schema.json` | Closed declaration shapes for legacy and normalized inputs | No runtime policy engine or new dependency |
| Context | `scripts/context/_context.py`, `scripts/context/_techcontext.py`, `scripts/context/_test_reachability.py`, `scripts/context/run-required`, `tests/context/**`, `tests/repo/**` | Deep read-only reachability module, legacy/simplified adapters, and canonical required-gate dispatch through the existing runner seam | Audit has no network, test execution, PR-head import or Quality import; dispatcher accepts no alternate gate list |
| Quality | `scripts/quality/gate.py`, `scripts/quality/gate_actions.py`, `tests/quality/test_gate.py` | Reconcile selected lane status, `ran` and exact SHA | No Context import and no alternative aggregate |
| CI/self-adoption support | `.github/workflows/quality.yml`, later `.github/workflows/ci.yml`, `scripts/verify`, root/leaf `tech-context.md` files | Invoke the Context CLI, publish lane outputs, declare shared-ci's own suites | Candidate workflow cannot self-approve; published provider pin required |
| Registry | `scripts/contracts/tech-context.md`, `tests/contracts/**` | Own contract-test inventory that remains a deliberate visible exclusion from native PR verification | Exclusion is not reach and adds no Registry test execution |
| Release/tracker integration | immutable tag/full SHA and linked adoption issues | Make the reviewed provider selectable and adoption traceable | No floating pin; no claim of adoption without required-check readback |

No new architecture dependency edge is planned. Any implementation that needs
one returns to planning before changing a `tech-context.md` dependency.

## Delivery slices and task graph

`G0` is a hard external dependency for every implementation task: T001 has an
exact-revision AI Reviewer PASS and its non-Draft contract-document PR is merged.
Review may happen in parallel, but no implementation branch starts before both
facts hold.

Tasks identify layer-owned work or an explicitly named repository integration
work unit; an **atomic delivery group** identifies the independently mergeable PR
boundary when implementation and its companion tests belong to different layers.
Tasks in an atomic group share one final reviewed head, tests are committed with
or before the behaviour they cover, and no member may merge alone.

### US1 — Approve the contract before code

Observable outcome: reviewers can accept one normative contract and a complete
layer/path graph independently of implementation.

- [ ] T001 [US1] Publish and merge `docs/orphan-test-contract.md` plus its `docs/repository-guide.md` link after exact-revision spec review.

### US2 — Declare and audit test reachability

Observable outcome: a local, read-only Context command deterministically reports
orphaned and valid fixture repositories across both context formats.

- [ ] T101 [US2] Add the version-1 declaration shapes to `schemas/context-v1.schema.json` as the Schemas member of atomic group US2-A.
- [ ] T102 [US2] Add legacy/new-shape normalization and compatibility regressions in `scripts/context/_context.py`, `scripts/context/_techcontext.py`, `tests/context/fixture.py` and `tests/context/test_reachability_declarations.py` as the Context member of atomic group US2-A.
- [ ] T103 [US2] Implement the read-only reachability module, exact lane-binding admission, canonical `scripts/context/run-required` dispatcher, discovery adapters and findings in Context, with interface regressions in `tests/context/test_reachability.py` and `tests/context/test_runner.py`.
- [ ] T104 [US2] Document the implemented CLI and data contract in `docs/context-cli-contract.md` and `docs/architecture.md`.

T101 and T102 are one independently verified PR. The Context compatibility tests
land first or in the same commit as the schema/parser behaviour; neither task is
an independently mergeable slice.

### US3 — Make the audit and bound command lanes fail closed in the aggregate

Observable outcome: the enabled orphan-test audit and every command lane it
admits block `quality / aggregate` and cannot pass with a missing, unbound,
skipped, failed, malformed or stale result.

- [ ] T201 [US3] Reconcile the audit-emitted required-lane set in `scripts/quality/gate.py`, `scripts/quality/gate_actions.py` and `tests/quality/test_gate.py`.
- [ ] T202 [US3] Add canonical executor wiring, the opt-in audit lane and aggregate outputs to `.github/workflows/quality.yml` as the root-support member of atomic group US3-B.
- [ ] T203 [US3] Add workflow/source-admission and current-head integration regressions in `tests/repo/test_orphan_test_workflow.py` and `tests/repo/fixture.py` as the Context member of atomic group US3-B.

T202 and T203 are one independently verified PR. The repo regression commit
precedes or accompanies workflow behaviour, and neither task may merge alone.

### US4 — Release and self-adopt

Observable outcome: the provider is immutable, shared-ci uses it on itself, and
its native verification cannot silently omit a newly added matching test file.

- [ ] T308 [US4] Publish the reviewed US2/US3 implementation at an immutable version/full SHA.
- [ ] T300 [US4] Repin every selected-provider parity surface to T308 in one compatible, pin-only CI/self-adoption migration; do not enable reachability or add layer declarations.
- [ ] T301 [P] [US4] Add Context-owned `test_paths` and test-gate metadata in `scripts/context/tech-context.md`.
- [ ] T302 [P] [US4] Add Lint-owned `test_paths` and test-gate metadata in `scripts/lint/tech-context.md`.
- [ ] T303 [P] [US4] Add Quality-owned `test_paths` and test-gate metadata in `scripts/quality/tech-context.md`.
- [ ] T304 [P] [US4] Add Select-owned `test_paths` and test-gate metadata in `scripts/select/tech-context.md`.
- [ ] T305 [P] [US4] Add Policy-owned `test_paths` and test-gate metadata in `scripts/policy/tech-context.md`.
- [ ] T306 [P] [US4] Add Review-owned `test_paths` and test-gate metadata in `scripts/review/tech-context.md`.
- [ ] T307 [P] [US4] Add Ruleset-owned `test_paths` and test-gate metadata in `scripts/ruleset/tech-context.md`.
- [ ] T310 [P] [US4] Add Registry-owned `test_paths: [tests/contracts/**]` in `scripts/contracts/tech-context.md` without claiming native reachability or changing separate admission.
- [ ] T309 [US4] Enable self-adoption across the root policy, suite discovery, every provider-pin parity surface and its focused parity regressions; classify `scripts/quality/test_integrity.py` as a non-test and exclude `tests/contracts/**` with reason.

T300 is a safe expand step: the newly published parser accepts the still-legacy
tree while reachability remains disabled. Only after T300 may T301–T307 and T310
land independently. T309 is the final enablement step. This avoids every merge
boundary at which the older selected provider would reject object-form gates.

### US5 — Make rollout traceable

Observable outcome: each named repository has a linked adoption path and no
repository claims coverage from a manual/advisory job.

- [ ] T401 [US5] File or link adoption issues in order: VoxPocket after MY-1607; agent-skills; shared-design-tokens, shared-design-system and shared-telemetry; then VitalStride and AIDash after their orphan run/exclusion decisions.
- [ ] T402 [US5] Record the released full SHA/tag, self-adoption PR head/check evidence and the follow-up issue links on MY-1608.

### Task metadata and dependencies

| Task | Owner area / context | Paths in scope | Explicitly out of scope | Contract impact | Task-local acceptance and verification | Blocks on |
| --- | --- | --- | --- | --- | --- | --- |
| T001 | Docs/spec support; root support declaration | `docs/orphan-test-contract.md`, `docs/repository-guide.md` | All scripts, schemas, workflows and tests | Establishes this contract only | All FR IDs mapped; `scripts/verify`; `git diff --check`; exact-revision reviewer PASS; PR merged | none |
| T101 | Schemas; `schemas/tech-context.md` | `schemas/context-v1.schema.json` | Runtime parsing and workflow wiring | Adds closed v1 root/object shapes without changing legacy meanings | Atomic US2-A final head: JSON/schema checks, consuming Context compatibility fixtures and suite, Context audit, `scripts/verify` | G0; atomic with T102 |
| T102 | Context; `scripts/context/tech-context.md` | `scripts/context/_context.py`, `scripts/context/_techcontext.py`, `tests/context/fixture.py`, `tests/context/test_reachability_declarations.py` | Discovery implementation, Quality and workflow YAML | Normalizes legacy and new declarations while retaining old behaviour | Old string/list gates unchanged; valid new shapes normalize; malformed/unknown fields fail closed; Context suite and `scripts/verify` on atomic US2-A head | G0; atomic with T101, tests first |
| T103 | Context; `scripts/context/tech-context.md` | `scripts/context/_test_reachability.py`, `scripts/context/run-required`, required `scripts/context/_context.py` integration, `tests/context/test_reachability.py`, `tests/context/test_runner.py` | Quality reconciliation, workflow YAML and consumer declarations | Implements the read-only module and canonical dispatcher interface | FR-003–FR-009 fixtures; exact invocation accepted; unrelated/wrong/dynamic/composed bindings rejected; multi-gate preflight/order/failure cases; Context suite, audit, `scripts/verify` | US2-A |
| T104 | Docs support | `docs/context-cli-contract.md`, `docs/architecture.md` | New policy or runtime behaviour | Describes implemented interface, canonical binding and evidence limits | Link/topic review; `scripts/verify`; `git diff --check` | T103 |
| T201 | Quality; `scripts/quality/tech-context.md` | `scripts/quality/gate.py`, `gate_actions.py`, `tests/quality/test_gate.py` | Context imports and workflow YAML | Reconciles the audit-emitted required-lane set only | Missing/malformed/unselected lanes, `ran: false`, status and stale/current SHA regressions; Quality suite; `scripts/verify` | T103 |
| T202 | CI/self-adoption root support | `.github/workflows/quality.yml` | Context implementation and consumer pin changes | Adds default-false audit input, pinned-provider canonical execution and aggregate needs | Atomic US3-B final head: workflow-lint; same-pin checkout/source inspection; lane/audit outputs; `scripts/verify` | T103, T201; atomic with T203 |
| T203 | Context integration tests; `scripts/context/tech-context.md` | `tests/repo/test_orphan_test_workflow.py`, `tests/repo/fixture.py` | Engine algorithms and release operations | Proves workflow/source admission at the public seam | Exact executor route plus unrelated command, wrong lane, expression, shell composition, PR/manual/continue-on-error and current-head aggregate cases; repo suite; `scripts/verify` on atomic US3-B head | T103, T201; atomic with T202, tests first |
| T308 | Release integration; no source layer | reviewed US2/US3 exact commit and immutable tag | Consumer adoption and self-adoption pin | Makes the compatible provider selectable | exact local/remote/tag SHA equality; merged implementation evidence; published immutable reference | T104, US3-B |
| T300 | CI/self-adoption integration work unit | `.github/workflows/ci.yml`, `.github/workflows/review.yml`, `AGENTS.md`, `.github/repo-contract.json`, `docs/repository-guide.md`, `tests/repo/test_self_adoption.py`, `tests/review/test_completion_gate.py` | Root reachability policy, leaf declarations, `scripts/verify`, provider engine | Repins every parity surface without enabling the feature | Every literal pin and embedded protocol/guide route equals T308; legacy declarations pass selected-provider contract; feature absent/false; focused parity tests, Context audit, workflow-lint, `scripts/verify` | T308 |
| T301 | Context | `scripts/context/tech-context.md` | Other leaf contexts | Declares Context-owned test scope/gates | Newly pinned provider accepts the declaration; Context audit and suite; `scripts/verify` | T300 |
| T302 | Lint; `scripts/lint/tech-context.md` | `scripts/lint/tech-context.md` | Other leaf contexts | Declares Lint-owned test scope/gates | Newly pinned provider accepts the declaration; Context audit and Lint suite; `scripts/verify` | T300 |
| T303 | Quality | `scripts/quality/tech-context.md` | Other leaf contexts | Declares Quality-owned test scope/gates | Newly pinned provider accepts the declaration; Context audit and Quality suite; `scripts/verify` | T300 |
| T304 | Select; `scripts/select/tech-context.md` | `scripts/select/tech-context.md` | Other leaf contexts | Declares Select-owned test scope/gates | Newly pinned provider accepts the declaration; Context audit and Select suite; `scripts/verify` | T300 |
| T305 | Policy; `scripts/policy/tech-context.md` | `scripts/policy/tech-context.md` | Other leaf contexts | Declares Policy-owned test scope/gates | Newly pinned provider accepts the declaration; Context audit and Policy suite; `scripts/verify` | T300 |
| T306 | Review; `scripts/review/tech-context.md` | `scripts/review/tech-context.md` | Other leaf contexts | Declares Review-owned test scope/gates | Newly pinned provider accepts the declaration; Context audit and Review suite; `scripts/verify` | T300 |
| T307 | Ruleset; `scripts/ruleset/tech-context.md` | `scripts/ruleset/tech-context.md` | Other leaf contexts | Declares Ruleset-owned test scope/gates | Newly pinned provider accepts the declaration; Context audit and Ruleset suite; `scripts/verify` | T300 |
| T310 | Registry; `scripts/contracts/tech-context.md` | `scripts/contracts/tech-context.md` | Registry test contents/execution, root exclusion, other leaf contexts | Adds `test_paths: [tests/contracts/**]` with no qualifying native gate | Every Registry candidate resolves within Registry before exclusion; separate admission unchanged; no native discovery; Context audit and `scripts/verify` | T300 |
| T309 | CI/self-adoption integration work unit | `docs/architecture/tech-context.md`, `scripts/verify`, `.github/workflows/ci.yml`, `.github/workflows/review.yml`, `AGENTS.md`, `.github/repo-contract.json`, `docs/repository-guide.md`, `tests/repo/test_self_adoption.py`, `tests/review/test_completion_gate.py` | Provider engine, leaf declarations, Registry test execution and downstream consumers | Enables shared-ci, preserves pin parity and replaces brittle native discovery | All surfaces retain T308; focused drift regressions; root policy/non-test/exclusion semantics; Registry resolves before exclusion; full `scripts/verify`; workflow-lint; exact-head lane/aggregate evidence and server required-check readback | T301–T307, T310 |
| T401 | Tracker integration; no repository layer | named adoption issue records | Fixing downstream orphan tests | Records rollout dependencies | every named repository has a linked issue with provider pin and remediation/exclusion prerequisite | T309 |
| T402 | Integration evidence; no source layer | MY-1608 evidence record | Merge, scheduling or downstream implementation | Closes traceability only | exact tag/SHA, self-adoption PR/check evidence and T401 links agree | T401 |

The dependency graph is acyclic:

```text
T001 review PASS + merge (G0)
  -> [T101 Schemas + T102 Context tests/normalization] atomic US2-A
       -> T103 Context reachability/dispatcher
            -> T104 docs
            -> T201 Quality
                 -> [T203 Context tests first + T202 workflow] atomic US3-B
  -> (T104 + US3-B) -> T308 release -> T300 compatible pin-only migration
       -> T301 || T302 || T303 || T304 || T305 || T306 || T307 || T310
       -> T309 self-adoption enablement
       -> T401 adoption issues -> T402 evidence record
```

The `[P]` tasks touch different layer-owned files and may proceed independently
only after T300 selects the compatible published provider. T300 and T309 are the
repository's declared CI/self-adoption integration work unit; their cross-context
parity tests are necessary companions, not hidden provider-engine work.

## Acceptance coverage

| Acceptance | Slice / tasks | Evidence surface |
| --- | --- | --- |
| FR-001 | US1 / T001 | Exact contract commit, reviewer verdict and merged PR |
| FR-002–FR-004 | US2 / T101–T103 | Closed schema, legacy/new normalization, inventory/classification fixtures and findings |
| FR-005 | US2–US3 / T101–T103, T201–T203 | Closed declaration-to-lane binding, exact declared command execution, and selected/nonadvisory/current-head aggregate reconciliation |
| FR-006 | US2 / T103–T104 | Static adapter fixtures and documented unsupported/dynamic failure modes |
| FR-007–FR-009 | US2–US3 / T102–T103, T201–T203 | Context findings, binding negatives and aggregate/workflow regressions delivered with behaviour |
| FR-010 | US1–US3 / T001, T103–T104, T201–T203 | Separate Context reachability and test-integrity interfaces, distinct blocking lanes, aggregate reconciliation and workflow/repo regressions |
| FR-011 | US4 / T300–T310 | Safe immutable repin, every layer inventory including Registry, root enablement, suite discovery, parity and current-head aggregate evidence |
| FR-012 | US4–US5 / T308, T401–T402 | Immutable release reference and linked adoption records |
| FR-013 | Every slice | Non-Draft PR metadata and exact-head required-check evidence |
| FR-014 | US2–US3 / T102–T103, T202–T203 | Static fixtures, source inspection, no audit execution/network and full native verification |

## Verification and evidence limits

Every source PR runs its focused commands from the task table and the native
full entry:

```sh
scripts/verify
git diff --check
```

Before a commit, also run `git diff --cached --check`. Planning-document local
verification is development evidence only. Implementation completion requires
the repository's normal exact-head checks and reviews; self-adoption additionally
requires effective server readback for `quality / aggregate`.

No UI or end-user visual surface changes, so no manual UI evidence applies.
Manual review must instead confirm the contract's file/reason diagnostics and
the named workflow source routes on the exact revision.

## Rollout order

1. Review and merge T001 as a Docs/spec PR.
2. Deliver the additive Schema and Context interface, documentation and fixtures.
3. Deliver the default-false Quality lane and aggregate reconciliation.
4. Publish the reviewed implementation under an immutable tag/full SHA.
5. Repin every shared-ci provider-parity surface to that compatible provider
   while the feature remains disabled and declarations remain legacy-shaped.
6. Add each leaf declaration independently under the new parser, including
   Registry `test_paths` without a native Registry gate.
7. Enable self-adoption with the root policy, corrected suite discovery,
   explicit `tests/contracts/**` exclusion and required-check readback.
8. Adopt VoxPocket after MY-1607, then agent-skills, then the three repositories
   with no known orphans, then VitalStride and AIDash after their explicit run or
   exclusion decisions. A repository without `quality.yml` first establishes the
   required aggregate route.
9. Consider a separate default-on proposal only after supported callers have
   migrated. This contract grants no such default change.

Fixing downstream orphan tests is outside MY-1608. Test-level skip analysis is a
possible later extension, not an implicit part of this contract.
