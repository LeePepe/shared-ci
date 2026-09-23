# Pure 6DQ receipt reconciliation, v1

This is an unpublished, bounded candidate: not 6DQ delivery, runtime clearance,
required-check enforcement or Ship approval. It adds one pure-data module and
does not change the context runner, policy evaluator or existing workflows.

## Interface and trust

```python
def aggregate_6dq(*, expectation: dict, evidence: dict) -> dict:
    ...
```

Callers and synthetic tests use this same interface. It returns new native
containers without mutating inputs. It has no CLI, callback, resolver, artifact
retrieval, clock/environment reads, filesystem/network access, execution, output
or per-call persistent state. Its only imports are `datetime`, `re` and the
existing public `scripts.policy.validate.evaluate_policy`. No private policy
helpers or alternative approval comparator are used.

Inputs are supplied claims. References and digests are not fetched, authenticated
or checked for existence. Repository IDs, SHAs, resource ownership, event times,
implementation and enforcement states are also supplied claims. SHA syntax is
not ancestry, existence or provenance. The function does not establish isolation
or execute any workload, including negative cases or preflight.

The caller must authenticate/materialize policy and expectation data, establish
trusted producers, reject duplicate JSON keys and nonstandard constants, and
prevent concurrent input mutation. A future normal importer must establish that
the namespace package `scripts` resolves exclusively to the reviewed pinned tree.
No launcher, installation, App choice or trust-root selection is provided here.

Every result retains exactly:

```json
{"authenticity":"not_verified","enforcement":"not_verified","ship":"not_assessed"}
```

`required_acceptable` only answers whether the supplied required receipts satisfy
this finite reconciliation contract. In particular, a reported
`remote_required_verified` enforcement value never upgrades assurance.

## Shapes, transport and ordering

[Input schema](../schemas/quality-input-v1.schema.json) describes the two keyword
arguments in a closed `{expectation,evidence}` envelope.
[Result schema](../schemas/quality-result-v1.schema.json) describes the result.
Both schemas are self-contained: every `$ref` is document-local. Their `$schema`
identifier is descriptive, not permission to fetch anything. No schema validator
or dependency is required by the module.

All declared keys are mandatory; nullable means a present key with `null`, not an
optional key. Dimension keys are exactly `L1,L2,L3,G1,G2,D1`. Empty target objects
are closed too. `preflight` has only `event` and `controls`; only each control row
has a `state`. There is no `preflight.state`.

Native inputs contain only exact `dict/list/str/int/None`, never bool, float,
subclasses or custom objects. Maximums across the two roots, in order:

- 100,000 node occurrences; depth 32, with each root at depth 1 and dictionary
  keys, values and list elements at parent depth + 1.
- 4,096 strict UTF-8 bytes per string, including keys; 8,388,608 aggregate string
  occurrence bytes. Lone surrogates fail UTF-8 validation. Shared acyclic
  subtrees count repeatedly; ancestor cycles are invalid.
- Every integer is in `0..9223372036854775807` before narrower checks. Positive
  counts exclude zero; basis points are integers in `0..10000`.

The resource walk visits expectation before evidence, dictionary keys in sorted
code-point order, and lists in supplied order. Numeric/string/node/depth bounds
produce `quality_limit_exceeded`; wrong native type, invalid UTF-8 or cycles
produce `quality_input_invalid`. These transport outcomes do not declare an
otherwise eligible approval invalid.

Quality `U` lists have 0–1024 entries, or 1–1024 where nonempty is required.
They are strictly increasing and unique: strings by code point, records by `id`,
exclusions by `path`, subjects by `(repository_id,revision,path,layer)`. Subjects
with the same identity tuple but different red lines still collide. Check IDs
and nonnull run IDs are globally unique, including observed check IDs. Commands
contain 1–1024 nonblank text tokens, preserve order and permit duplicates.
Subject red lines preserve order and permit duplicates. Embedded policy arrays
retain policy-v1 cardinality/ordering semantics, not the quality `U` bound.
Cardinality/order violations are shape errors, not transport-limit errors.

IDs use `[A-Za-z][A-Za-z0-9_.-]{0,127}`. Repository IDs are positive decimal
strings without leading zero. SHAs/digests are nonzero lowercase 40/64-hex.
Text is nonblank by Python whitespace semantics, strict UTF-8, and contains no
C0/C1 controls. Paths retain literal Git-relative spelling: no empty, `.` or
`..` segments, leading slash, backslash or controls; no trimming, URL decoding,
glob matching or normalization. Times are real Gregorian UTC seconds spelled
`YYYY-MM-DDTHH:MM:SSZ`, not ambient timestamps.

Structural null coupling is checked with shapes: measured entries have nonnull
numerator, denominator and report ID; unmeasured/unknown entries have all three
null. Receipt run and isolation are either both null or both nonnull. A pass
requires nonnull run and payload. Report completeness and local references are
evaluated later, after receipt status, so they produce a coverage finding.

JSON Schema cannot fully express exact Python types, byte/occurrence budgets,
identity-key order, Gregorian calendar validity, cross-record equality,
semantic mapping or policy eligibility. Those checks remain in the function.
Schemas describe structure, not a second policy engine. Policy-v1 semantic
validation (including approval uniqueness and expiry-or-review presence) remains
authoritative in `evaluate_policy`.

## Expected obligations and policy reuse

Each dimension has at least one baseline-required check. Every check's complete
Subjects and referenced policy cases form a bijection. Subject equality includes
repository, revision, literal path, layer and ordered red lines. Every subject
repository/head equals the outer candidate; every case's baseline/candidate pin
equals the outer policy pin. All policy cases must be referenced.

Each expected scope path appears in a Subject; every Subject covers an included
or excluded path. Included and excluded paths cannot overlap. Scope item IDs,
not merely paths, define complete evidence coverage.

Every baseline rule maps to exactly one semantic slot across referencing checks
within its case. Duplicate or unmapped slots are contract errors:

| Slot | Baseline meaning |
| --- | --- |
| Nonnull obligation | Exactly `required`; check level is required |
| Null obligation | Advisory only; no mapped presence rule |
| Scope | `required_set`, exactly all expected scope item IDs |
| Four L1 metric slots | `minimum_basis_points`, each baseline at least 9500 |
| G2 scanners | `required_set`, exactly expected scanner IDs |

Every policy case is passed to the actual public evaluator, in case-ID order,
before expected semantic mapping. Its first rejection becomes one fixed
`quality_policy_rejected` finding; raw policy detail is not copied out.
Existing complete-record matching, pin/scope/revision binding, before/after,
expiry, review/revocation observations and alternative verification remain
authoritative; see [policy contract](policy-validation-contract.md).

After eligibility, stage four validates only **baseline** semantic mappings,
scope, kinds, obligation levels, bijections and threshold floors. It does not
read a removed or weakened candidate set as though it were an invalid baseline.
Stage five then classifies eligible removals, nonnumeric changes, set weakening,
set expansion and candidate-only rules as unsupported. Thus an approved removal
is unsupported, a forged approval is policy-rejected, and a valid removal plus
invalid baseline mapping is contract-invalid. None cancels authentic approval
authority; they are limits of this partial module.

Only supported numeric L1 candidate values are used for evaluation. Use the
maximum effective minimum across the check's policy cases, including an exact
eligible reduction below 9500. An eligible exception adjusts only its metric;
it cannot make skipped, focused or unmeasured execution a measured pass.

## Identity and finite predicates

Outer evidence and every receipt binding must equal the expected binding in
full, including mapping evidence record/digest and source revisions. Receipt
subjects, argv, tools/versions and scope must also match exactly.

Direct mapping requires tested revision/tree equal the candidate revision/tree,
sources exactly `[candidate.revision]`, and null mapping evidence. Merge requires
at least two distinct sources including the candidate head and a nonnull mapping
report. This proves no ancestry or correspondence beyond supplied equality.
Only `actions` is supported. `pre_commit` and `pre_push` are unsupported, not
silently treated as Actions or as evidence for index/pushed-ref obligations.

Pass report IDs must equal exactly the expected IDs. Every payload reference
must resolve in that receipt's reports; refs/digests are never retrieved.

- **L1:** all four metrics measured, denominator exactly the expected positive
  candidate-specific denominator, numerator at most denominator, and
  `numerator * 10000 >= effective_BP * denominator`. No averaging or rounding.
  Skipped/focused counts must both be zero. Failure is `quality_measurement`.
- **L2/L3:** case IDs equal all scope item IDs and every case status passes.
  Failure is `quality_coverage`.
- **G1:** errors and warnings both zero. Failure is `quality_measurement`. This
  is the finite predicate attached to the required obligation, not an invented
  maximum comparator. Other product checks need separately represented rules.
- **G2:** expected scanner IDs reference declared tools and their item union is
  complete scope. Each observed ID/items matches its target, status passes and
  verdict passes. Failure is `quality_coverage`; scanner names are never defaulted.
- **Isolation:** parent/record run IDs agree, target equals expectation, control
  IDs equal target and all states pass; `state` is always required. Sequences
  strictly increase preflight/start/finish/cleanup, timestamps are nondecreasing.
  Cleanup passes; resource IDs exactly cover target, creator is the parent run,
  ownership and marker match, and every cleanup passes. Empty resource lists
  allow explicit no-I/O runs with successful no-op cleanup. Failure is
  `quality_isolation`.
- **D1:** cases exactly cover scope/target negatives, all pass, and `runs` equals
  every observed nonnull run ID including its own, failed and advisory runs.
  Coverage failures use `quality_coverage`. After its own predicate and isolation,
  validate each referenced isolation against that run's owning expected check.
  Cross-run failures use `quality_isolation`. Required negatives are abnormal
  exit, cleanup refusal, concurrent run and unsafe target (their underscore IDs
  in the schema), plus port collision if **any expected check** declares ports,
  even an advisory or unsuccessful check.

Preflight is an observation before workload execution, not another executable
workload requiring recursive preflight. Late preflight cannot authorize a run
retrospectively. D1's own workload has one ordinary preflight. Successful data
reconciliation does not perform or guarantee isolation.

## Exact state machine and findings

Precedence is fixed:

1. Native/resource walk of expectation, then evidence.
2. Closed shapes and lexical checks in sorted-key order, expectation then
   evidence, followed by global identity uniqueness. Unsupported schema integer
   yields unsupported; missing/extra dimension keys yield input-invalid.
3. Actual policy evaluations by case ID; first rejection aborts.
4. Expected binding invariants and baseline semantic mapping, canonical dimension
   order then check ID; first violation is contract-invalid.
5. Unsupported phase, additional candidate rules, removals/nonnumeric changes.
6. Evidence top binding and unexpected receipt IDs: binding-mismatch.
7. Every expected check: missing, binding equality, status, report coverage,
   dimension predicate, own isolation, then D1 cross-run isolation. First failure
   per check wins; other checks are still evaluated.

Stages 1–6 abort with null binding, false acceptance, no applied exceptions and
one global finding. All six fallback dimensions have null owner, unknown
implementation/enforcement, empty checks/gaps and unknown latest; only unsupported
uses latest unsupported. No partially trusted dimension data escapes a fallback.

Stage seven retains expected owner and reported implementation/enforcement.
Missing receipts produce result `not_run`, observed null. Nonpass statuses
`not_run`, `unavailable`, `unknown` retain that result; failure, cancelled,
skipped, manual, unmeasured and planned map to fail. All predicate failures fail.
Dimension latest uses `fail > unsupported > unknown > unavailable > not_run > pass`
across required and advisory checks. Required acceptance is true iff every
required check passes. Advisory failures remain visible findings/gaps and can
make dimension latest fail without independently blocking acceptance; unsafe
advisory execution can nevertheless fail required D1.

| Kind | Exact fixed detail |
| --- | --- |
| quality_input_invalid | Input structure is invalid. |
| quality_limit_exceeded | Input exceeds transport limits. |
| quality_unsupported | Evaluation requires unsupported semantics. |
| quality_policy_rejected | Existing policy evaluation rejected the case. |
| quality_contract_invalid | Expected obligation mapping is invalid. |
| quality_binding_mismatch | Observed identity or scope differs. |
| quality_missing | Expected receipt is missing. |
| quality_nonpass | Observed execution is not a pass. |
| quality_measurement | Required measurements do not satisfy the obligation. |
| quality_coverage | Required evidence coverage is incomplete or unsuccessful. |
| quality_isolation | Isolation evidence does not satisfy the obligation. |

Global findings use layer `quality`, empty path and empty red lines. Per-check
findings use the first validated expected Subject's layer/path/ordered red lines.
Finding details never contain commands, report references, reasons, logs or
arbitrary exception text. Output findings concatenate check findings in canonical
dimension/check order; gaps are sorted by check ID. Applied exception IDs are the
sorted union of successful policy evaluations only when required acceptance is
true; otherwise they are empty. They are eligibility IDs, not authenticity proof.

## Synthetic tests and execution hold

[Tests](../tests/quality/test_aggregation.py) expand the canonical fixture: one
required check per dimension, one complete policy case, four 95/100 metrics,
zero warnings/errors, complete scanner/case scope, six runs with state-only
no-I/O isolation and D1 including itself. Expected output is six passes and
unchanged assurance. Tests assert complete outputs, not just false acceptance.

The harness reads only the two actual reviewed sources and the two local
quality schemas. It compiles policy into a fresh namespace, then aggregation
into another namespace. A private copy of builtins resolves exactly the public
policy import to a module object exposing that actual function and allows only
the declared datetime/re imports. It never registers modules, edits `sys.path`
or `sys.modules`, changes global builtins, imports context fixtures or accepts a
candidate callback. Private side-effect builtins are denied as a regression aid,
not as a hostile-code sandbox. Source/import inspection is required before use.

After independent content review of all five files (including schemas and
loader), and **only after Main explicitly authorizes runtime**, the proposed
stdlib invocation from the verified task worktree is:

```text
python3 -I -S -B tests/quality/test_aggregation.py
```

Original authoring permitted only AST/JSON syntax parsing and whitespace checks,
not imports, test collection/execution, build/lint, SDKs, dependencies or network.
On 2026-09-23, a separately authorized bounded run using the installed Python
3.9.6 interpreter directly under read-only confinement passed all 32 tests once
(25 aggregation, 7 lexical), with no skips, extras, failures or detected drift
(0.966s unittest; 1.592068s wall). This is local development evidence, not full
6DQ, four-metric coverage, JSON Schema engine conformance, authentication,
R0/caller proof, required enforcement or Ship acceptance. No general runtime
permission follows; future execution still requires the entry conditions above,
and historical results do not transfer. The candidate remains unpublished under
delivery holds; no instructions, workflows or enforcement settings are changed.

Producer trust, root/caller verification, full four-metric instrumentation,
same-candidate proof, hook/index/pushed-ref support, genuine required enforcement
and Ship assessment remain later obligations. This Actions-data slice neither
waives them nor authorizes an App, release, infrastructure or service operation.
