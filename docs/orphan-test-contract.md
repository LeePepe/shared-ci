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
| FR-005 | A gate qualifies only when it runs for `pull_request`, is selected and non-`continue-on-error`, reports the same head SHA, and feeds `quality / aggregate`. Manual, release-only, local-only, build-only, advisory or nonaggregate lanes do not count. |
| FR-006 | Static, versioned discovery adapters cover SwiftPM test targets, XcodeGen/Xcode test schemes, pytest, unittest, `node --test`, Vitest, Ruby and shell suites. Unknown, dynamic or ambiguous discovery fails closed unless represented by the explicit reviewed-literal adapter. |
| FR-007 | An orphan produces a deterministic finding containing the literal file path and reason; the command exits nonzero. A tree in which all candidates are reached or explicitly excepted exits zero. |
| FR-008 | Default helper names do not become candidates. Other false positives, including a test-shaped tool such as `scripts/quality/test_integrity.py`, require a visible reasoned non-test entry. Deliberately non-PR suites require a distinct visible exclusion. |
| FR-009 | Unit and integration tests cover an orphan, a `workflow_dispatch`-only mapping, honoured discovery globs, a reasoned exclusion, helper/non-test handling, malformed declarations and stale/current-head aggregate results. |
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
   describes its static discovery adapter.
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
  referenced layer/gate/lane must exist and pass source admission.
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
5. Admit required gates from source configuration.
6. Expand each static discovery adapter and reject scope escapes.
7. Apply reasoned deliberate exclusions as an alternate terminal state.
8. Report every unclassified or contradictory path in literal path order.

A gate is qualifying only when all of these facts hold:

- the referenced context gate is `kind: test` and `mode: ci|both`;
- a caller workflow triggered by `pull_request` selects the referenced lane;
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
required aggregate`, or `discovery does not include this file`. Findings and
summaries never claim that excluded tests ran.

The test-specific audit returns 0 only when every candidate has one valid
terminal classification, 1 for findings and 2 for CLI usage errors, consistent
with the Context CLI. Invalid declarations are findings and fail CI. Missing,
malformed, skipped, stale-SHA or nonpass workflow results are never accepted as
a pass.

## Workflow placement and relationship to existing checks

The Context module owns inventory, normalization, adapter expansion and findings.
The reusable quality workflow owns orchestration and aggregate admission; Quality
does not import Context Python code, so the declared `Quality -> Policy`
dependency is unchanged.

The first provider release adds an `orphan-test-check` boolean workflow input
with default `false` for pin-compatible rollout. When `true`:

- a dedicated hosted lane checks out the caller head and pinned provider;
- it runs the test-specific Context audit without executing caller code;
- it reports the tested head SHA and `ran: true`;
- aggregate depends on the lane and requires explicit success at the expected
  SHA even when changed-layer selection chooses no implementation layer.

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
| Context | `scripts/context/_context.py`, `scripts/context/_techcontext.py`, a narrow `scripts/context/_test_reachability.py`, `tests/context/**`, `tests/repo/**` | Deep read-only reachability module and legacy/simplified adapters | No network, test execution, PR-head import or Quality import |
| Quality | `scripts/quality/gate.py`, `scripts/quality/gate_actions.py`, `tests/quality/test_gate.py` | Reconcile selected lane status, `ran` and exact SHA | No Context import and no alternative aggregate |
| CI/self-adoption support | `.github/workflows/quality.yml`, later `.github/workflows/ci.yml`, `scripts/verify`, root/leaf `tech-context.md` files | Invoke the Context CLI, publish lane outputs, declare shared-ci's own suites | Candidate workflow cannot self-approve; published provider pin required |
| Release/tracker integration | immutable tag/full SHA and linked adoption issues | Make the reviewed provider selectable and adoption traceable | No floating pin; no claim of adoption without required-check readback |

No new architecture dependency edge is planned. Any implementation that needs
one returns to planning before changing a `tech-context.md` dependency.

## Delivery slices and task graph

`G0` is a hard external dependency for every implementation task: T001 has an
exact-revision AI Reviewer PASS and its non-Draft contract-document PR is merged.
Review may happen in parallel, but no implementation branch starts before both
facts hold.

### US1 — Approve the contract before code

Observable outcome: reviewers can accept one normative contract and a complete
layer/path graph independently of implementation.

- [ ] T001 [US1] Publish and merge `docs/orphan-test-contract.md` plus its `docs/repository-guide.md` link after exact-revision spec review.

### US2 — Declare and audit test reachability

Observable outcome: a local, read-only Context command deterministically reports
orphaned and valid fixture repositories across both context formats.

- [ ] T101 [US2] Add the version-1 declaration shapes to `schemas/context-v1.schema.json`.
- [ ] T102 [US2] Implement normalization, gate admission, discovery adapters and findings in `scripts/context/_context.py`, `scripts/context/_techcontext.py` and `scripts/context/_test_reachability.py`, with `tests/context/**` regressions.
- [ ] T103 [US2] Document the implemented CLI and data contract in `docs/context-cli-contract.md` and `docs/architecture.md`.

### US3 — Make the selected lane fail closed in the aggregate

Observable outcome: an enabled orphan-test lane can block `quality / aggregate`
and cannot pass with a skipped, failed, malformed or stale result.

- [ ] T201 [US3] Reconcile the selected lane in `scripts/quality/gate.py`, `scripts/quality/gate_actions.py` and `tests/quality/test_gate.py`.
- [ ] T202 [US3] Add the opt-in lane and outputs to `.github/workflows/quality.yml`.
- [ ] T203 [US3] Add workflow/source-admission and current-head integration regressions under `tests/repo/**`.

### US4 — Release and self-adopt

Observable outcome: the provider is immutable, shared-ci uses it on itself, and
its native verification cannot silently omit a newly added matching test file.

- [ ] T301 [P] [US4] Add Context-owned `test_paths` and test-gate metadata in `scripts/context/tech-context.md`.
- [ ] T302 [P] [US4] Add Lint-owned `test_paths` and test-gate metadata in `scripts/lint/tech-context.md`.
- [ ] T303 [P] [US4] Add Quality-owned `test_paths` and test-gate metadata in `scripts/quality/tech-context.md`.
- [ ] T304 [P] [US4] Add Select-owned `test_paths` and test-gate metadata in `scripts/select/tech-context.md`.
- [ ] T305 [P] [US4] Add Policy-owned `test_paths` and test-gate metadata in `scripts/policy/tech-context.md`.
- [ ] T306 [P] [US4] Add Review-owned `test_paths` and test-gate metadata in `scripts/review/tech-context.md`.
- [ ] T307 [P] [US4] Add Ruleset-owned `test_paths` and test-gate metadata in `scripts/ruleset/tech-context.md`.
- [ ] T308 [US4] Publish the reviewed implementation at an immutable version/full SHA.
- [ ] T309 [US4] Coordinate `docs/architecture/tech-context.md`, `scripts/verify`, `.github/workflows/ci.yml` and provider-pin metadata to enable self-adoption, use suite discovery, classify `scripts/quality/test_integrity.py` as a non-test and exclude `tests/contracts/**` with reason.

### US5 — Make rollout traceable

Observable outcome: each named repository has a linked adoption path and no
repository claims coverage from a manual/advisory job.

- [ ] T401 [US5] File or link adoption issues in order: VoxPocket after MY-1607; agent-skills; shared-design-tokens, shared-design-system and shared-telemetry; then VitalStride and AIDash after their orphan run/exclusion decisions.
- [ ] T402 [US5] Record the released full SHA/tag, self-adoption PR head/check evidence and the follow-up issue links on MY-1608.

### Task metadata and dependencies

| Task | Owner area / context | Paths in scope | Explicitly out of scope | Contract impact | Task-local acceptance and verification | Blocks on |
| --- | --- | --- | --- | --- | --- | --- |
| T001 | Docs/spec support; root support declaration | `docs/orphan-test-contract.md`, `docs/repository-guide.md` | All scripts, schemas, workflows and tests | Establishes this contract only | All FR IDs mapped; `scripts/verify`; `git diff --check`; exact-revision reviewer PASS; PR merged | none |
| T101 | Schemas; `schemas/tech-context.md` | `schemas/context-v1.schema.json` | Runtime parsing and workflow wiring | Adds v1 structural shapes without changing old fields | JSON parse; context schema/fixture checks; `scripts/verify` | G0 |
| T102 | Context; `scripts/context/tech-context.md` | named Context engine files and `tests/context/**` | Quality aggregation, workflow YAML, consumer declarations | Implements the read-only module/interface | Context suite covers FR-003–FR-009 and adapter failures; `_context.py audit`; `scripts/verify` | T101 |
| T103 | Docs support | `docs/context-cli-contract.md`, `docs/architecture.md` | New policy or runtime behaviour | Describes the implemented interface and evidence limits | Link/topic review; `scripts/verify`; `git diff --check` | T102 |
| T201 | Quality; `scripts/quality/tech-context.md` | `scripts/quality/gate.py`, `gate_actions.py`, `tests/quality/test_gate.py` | Context imports and workflow YAML | Extends aggregate lane reconciliation only | Selected/unselected, `ran`, status and SHA regressions; Quality suite; `scripts/verify` | T102 |
| T202 | CI support / self-adoption work unit | `.github/workflows/quality.yml` | Context implementation and consumer pin changes | Adds default-false input and hosted lane | workflow-lint; lane output/source inspection; `scripts/verify` | T102, T201 |
| T203 | Context integration tests; `scripts/context/tech-context.md` | `tests/repo/**` | Engine algorithms and release operations | Proves workflow/source admission at the public seam | Repo suite covers PR/manual/continue-on-error/aggregate cases; `scripts/verify` | T201, T202 |
| T301 | Context | `scripts/context/tech-context.md` | Other leaf contexts | Declares Context-owned test scope/gates | Context audit and Context suite; `scripts/verify` | T308 |
| T302 | Lint; `scripts/lint/tech-context.md` | `scripts/lint/tech-context.md` | Other leaf contexts | Declares Lint-owned test scope/gates | Context audit and Lint suite; `scripts/verify` | T308 |
| T303 | Quality | `scripts/quality/tech-context.md` | Other leaf contexts | Declares Quality-owned test scope/gates | Context audit and Quality suite; `scripts/verify` | T308 |
| T304 | Select; `scripts/select/tech-context.md` | `scripts/select/tech-context.md` | Other leaf contexts | Declares Select-owned test scope/gates | Context audit and Select suite; `scripts/verify` | T308 |
| T305 | Policy; `scripts/policy/tech-context.md` | `scripts/policy/tech-context.md` | Other leaf contexts | Declares Policy-owned test scope/gates | Context audit and Policy suite; `scripts/verify` | T308 |
| T306 | Review; `scripts/review/tech-context.md` | `scripts/review/tech-context.md` | Other leaf contexts | Declares Review-owned test scope/gates | Context audit and Review suite; `scripts/verify` | T308 |
| T307 | Ruleset; `scripts/ruleset/tech-context.md` | `scripts/ruleset/tech-context.md` | Other leaf contexts | Declares Ruleset-owned test scope/gates | Context audit and Ruleset suite; `scripts/verify` | T308 |
| T308 | Release integration; no source layer | reviewed US2/US3 exact commit and immutable tag | Consumer adoption and self-adoption pin | Makes the provider selectable | exact local/remote/tag SHA equality; merged implementation evidence; published immutable reference | T103, T203 |
| T309 | CI/self-adoption support | root tech-context, `scripts/verify`, `.github/workflows/ci.yml`, coordinated pin/index metadata | Provider engine changes and consumer repositories | Enables shared-ci and replaces brittle native discovery | full `scripts/verify`; workflow-lint; reachability lane/aggregate/current-head evidence; server required-check readback | T301–T308 |
| T401 | Tracker integration; no repository layer | named adoption issue records | Fixing downstream orphan tests | Records rollout dependencies | every named repository has a linked issue with provider pin and remediation/exclusion prerequisite | T309 |
| T402 | Integration evidence; no source layer | MY-1608 evidence record | Merge, scheduling or downstream implementation | Closes traceability only | exact tag/SHA, self-adoption PR/check evidence and T401 links agree | T401 |

The dependency graph is acyclic:

```text
T001 review PASS + merge (G0)
  -> T101 -> T102 -> T103
                 -> T201 -> T202 -> T203
  -> (T103 + T203) -> T308 release
       -> T301 || T302 || T303 || T304 || T305 || T306 || T307
       -> T309 self-adoption
       -> T401 adoption issues -> T402 evidence record
```

The `[P]` tasks touch different layer-owned files and may proceed in parallel
only after the published provider exists. T309 is the integration proof; it does
not hide implementation for any layer.

## Acceptance coverage

| Acceptance | Slice / tasks | Evidence surface |
| --- | --- | --- |
| FR-001 | US1 / T001 | Exact contract commit, reviewer verdict and merged PR |
| FR-002–FR-006 | US2 / T101–T103 | Schema, normalized fixtures, adapter and declaration tests |
| FR-007–FR-009 | US2–US3 / T102, T201–T203 | Context findings plus aggregate/workflow regressions |
| FR-010 | US1–US3 / T001, T103, T201 | Separate documented interfaces and independently selected lanes |
| FR-011 | US4 / T301–T309 | Self-adoption declaration, discovery entry and current-head aggregate |
| FR-012 | US4–US5 / T308, T401–T402 | Immutable release reference and linked adoption records |
| FR-013 | Every slice | Non-Draft PR metadata and exact-head required-check evidence |
| FR-014 | US2–US3 / T102, T202–T203 | Static fixtures, source inspection and full native verification |

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
5. Self-adopt in shared-ci with the published provider, declarations, corrected
   suite discovery, explicit `tests/contracts/**` exclusion and required-check
   readback.
6. Adopt VoxPocket after MY-1607, then agent-skills, then the three repositories
   with no known orphans, then VitalStride and AIDash after their explicit run or
   exclusion decisions. A repository without `quality.yml` first establishes the
   required aggregate route.
7. Consider a separate default-on proposal only after supported callers have
   migrated. This contract grants no such default change.

Fixing downstream orphan tests is outside MY-1608. Test-level skip analysis is a
possible later extension, not an implicit part of this contract.
