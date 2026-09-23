# Policy eligibility v1

## Scope and public interface

`scripts/policy/validate.py` is a pure, stdlib-only Python 3.9+ module implementing
the accepted policy eligibility r2 contract (SHA-256
`2a78673466bdb9d84fec0e02a934d2cb05dbb10c4fa85977f3624fc1407a18c4`).
The codebase-design skill informs a deep module: one small public interface,
explicit caller-supplied facts, and returned results. Helpers are private; no
decoder, CLI, resolver integration or approval issuer is provided.

```python
def evaluate_policy(
    *, baseline: dict, candidate: dict, approvals: list, observation: dict
) -> dict:
    ...
```

All four arguments are required. They are already-decoded native data, not
filenames. The core performs no I/O, output, subprocess, Git, network, clock or
environment access. It does not mutate inputs or retain evaluation state.
Only `datetime` (Gregorian calendar validation) and `re` are imported.

The returned object has exactly these fields:

```text
eligible: bool
findings: list[Finding]
applied_exceptions: list[approval_id]
```

Success returns `eligible=true`, no findings and approval IDs sorted by Python
string/code-point ordering. Failure returns `eligible=false`, one deterministic
first finding and no applied exceptions, including when an earlier claim was
eligible. Mutable result lists do not alias input lists.

Each finding has exactly the existing finding-v1 fields: `layer`, `path`, `kind`,
`detail`, `red_lines`. A separately validated complete baseline subject supplies
attribution, even if a different field is invalid. Otherwise attribution is
`"policy"`, `""`, `[]`. Details are fixed field/rule explanations, never interpolated
approval evidence, reasons, conditions, arbitrary input bodies or caught exception
messages. Baseline attribution is intentionally returned and must itself be
suitable for the caller's output channel.

## Closed input structures

Every displayed key is required. Additional keys, including `approved`, fail.
There are no implicit defaults. `null` is allowed only for `after`, `expires_at`
and `review_event` in a waiver.

```text
Pin = {repository_id: RepoID, revision: SHA}
Subject = {repository_id: RepoID, revision: SHA, path: Path,
           layer: Text, red_lines: [Text, ...]}
Requirement = {kind: "required"}
            | {kind: "minimum_basis_points", value: Integer}
            | {kind: "required_set", values: [ID, ...]}
EventCondition = {event: ID, condition: Text}

baseline = {schema: 1, policy: Pin, subject: Subject,
            rules: {RuleID: Requirement, ...}}
candidate = {schema: 1, policy: Pin, rules: {RuleID: Requirement, ...},
             exceptions: [Approval, ...]}
approvals = [Approval, ...]
observation = {schema: 1, now: Timestamp,
               events: {ID: "occurred" | "not_occurred" | "unknown", ...}}

Approval = {
  schema: 1, approval_id: ID, evidence_ref: Text,
  waiver: {
    policy: Pin, repository_id: RepoID,
    paths: [Path, ...], revisions: [SHA, ...], rule_id: RuleID,
    before: Requirement, after: Requirement | null, reason: Text,
    expires_at: Timestamp | null, review_event: EventCondition | null,
    alternative_verification: EventCondition,
    revocation_events: [EventCondition, ...]
  }
}
```

The two Draft 2020-12 schemas are self-contained, with document-local `$ref`s:
`policy-input-v1.schema.json` describes the object containing the four keyword
arguments; `policy-exception-v1.schema.json` describes one Approval. Shared
definitions are identical. Neither the evaluator nor test harness fetches schema
references. These are structural descriptions, not a general-purpose validator
implementation or authenticity proof.

Primitive validation:

- Schema is an exact native Python `int` equal to 1. Other integers are unsupported
  schemas; booleans, floats, strings and null are invalid inputs.
- RepoID is a positive decimal string without a leading zero, not a repository
  name or URL. SHA is 40 lowercase hexadecimal characters and not all zero.
- ID and RuleID match `[A-Za-z][A-Za-z0-9_.-]{0,127}` exactly.
- Integer is an exact native `int` from 0 through 10000 inclusive.
- Text encodes as strict UTF-8, has no C0/C1 controls, and is nonblank according to
  Python `str.strip()` whitespace inspection. Text is not trimmed for comparison.
- Timestamp is a valid Gregorian UTC `YYYY-MM-DDTHH:MM:SSZ`, years 0001–9999.
  Offsets, fractions, leap seconds, invalid calendar dates and alternate digits
  are rejected. Valid fixed-width timestamps can be compared lexically.
- Only exact native `dict`, `list`, `str`, `int` and explicitly permitted `None`
  are accepted. No booleans, floats (including NaN/Infinity), subclasses, custom
  mappings, bytes, tuples, sets or other custom objects are accepted. Keys must
  be exact native strings. Custom equality/repr methods are not used to validate
  the input's native types.

Scope lists are nonempty and strictly sorted/unique. Required-set values are
strictly sorted/unique but may be empty. Ordering is Python code-point ordering,
not locale-aware or normalized ordering. Revocation conditions are nonempty,
strictly sorted by unique event ID. Baseline rules are nonempty; candidate rules,
approval lists, observation events and subject red lines may be empty.

The native-data walk rejects ancestor cycles, depth greater than 32 and more than
100,000 node occurrences across the four arguments. Each argument root has depth
1; each dictionary key and value or list element is one node at parent depth + 1.
An input-bundle wrapper is not counted. Reused acyclic subtrees are valid and
count on each occurrence. Separate safe-subject attribution uses its own bounded
walk, not the combined evaluation budget. Dictionary traversal uses sorted keys;
list traversal retains list order. These limits do not impose a string-byte cap.
Callers remain responsible for safe decoding and their own raw-input resource
limits, and must not mutate inputs concurrently with evaluation.

Runtime validation is deliberately stricter than JSON Schema: mathematical
`integer` can admit `1.0`, while the runtime cannot. Runtime additionally checks
strict UTF-8/lone surrogates, actual calendar dates, sorted lists, unique event
and approval IDs, graph/resource limits and eligibility. A caller's JSON decoder
must reject duplicate object keys and nonstandard constants; decoding that has
already discarded duplicate keys cannot be repaired by this module.

## Literal UTF-8 path semantics

Path is a literal UTF-8 Git-relative name, never a URI, glob or OS-path conversion
request. It must be nonempty, must not begin with `/`, and cannot contain a
backslash, U+0000–U+001F or U+007F–U+009F. Splitting only on literal `/` must produce
no empty, `.` or `..` segments. All other characters are preserved exactly.
Lone surrogates and non-UTF-8 Git names are unsupported.

Unlike Text, Path may be entirely spaces. Leading/trailing spaces within a name,
Unicode, punctuation, percent signs and wildcard-looking characters are literal:

```text
SampleWatch Watch App/Sources/SampleWatchApp.swift
示例模块/消费者 测试.swift
assets/100% complete.txt
src/%61.py
```

There is no trimming, case-folding, whitespace collapse, Unicode normalization,
URL decoding, alias expansion, separator rewrite, prefix matching or wildcard
evaluation. `src/%61.py` is not `src/a.py`; `%2F` is not a separator; `%2e%2e` is
not `..`. Composed `café.swift` and decomposed `cafe\u0301.swift` are distinct.
The schemas permit these same literal spellings; neither uses an ASCII segment
allowlist nor rejects percent characters categorically.

Scope uses exact string membership. A scope named `src/*` covers only that literal
name, not its neighbors. A path `src/a.py` covers neither `src/ab.py` nor
`src/a.py/child`. Directory, repository-wide and revision-range semantics are
unsupported. Symlink containment, aliases and canonical Git entry identity belong
to the trusted caller; core cannot recognize accidentally URI-encoded names or
infer filesystem identity. One successful evaluation covers only its one exact
subject path and revision.

## Comparison and exception eligibility

Policy repository ID and revision must match the baseline exactly. Exceptions
cannot authorize a changed policy pin. SHA syntax does not prove existence;
lexicographic SHA order, ancestry, floating refs and version ranges confer no
eligibility.

| Requirement kind | Equal or stricter candidate |
| --- | --- |
| `required` | Same requirement retained |
| `minimum_basis_points` | Same kind, candidate value at least the baseline value |
| `required_set` | Same kind, candidate values a superset of baseline values |

New supported rule IDs are allowed. Unknown kinds, kind substitution and malformed
requirements cannot be waived. Every weakened or removed baseline rule needs
exactly one candidate exception. Each claim must:

1. Match the complete separately supplied Approval object with the same unique
   approval ID. Only dictionary key order is irrelevant; evidence, reason,
   conditions, scope spellings, before and after all remain content-bound.
2. Match the baseline policy pin and subject repository ID, exact path membership
   and exact subject-revision membership.
3. Bind `before` to the actual baseline requirement and `after` to the actual
   candidate requirement; null means removal. A claim for a nonexistent baseline
   rule, unchanged rule or stronger rule is unused and fails.
4. Supply expiry, review event, or both. Expiry requires `now < expires_at`;
   equality is expired. Review requires explicitly `not_occurred`. Both conditions
   apply when both are present.
5. Observe every revocation event explicitly as `not_occurred`.
6. Observe alternative verification explicitly as `occurred`.

Missing/unknown observations fail closed. Condition text is bound content,
not an expression the evaluator executes. Event IDs select caller-observed states;
an unsatisfiable combination of conditions never manufactures eligibility.

Duplicate approval IDs within either list and multiple candidate claims for the
same rule are structural errors. Claims cannot be combined to broaden authority.
Unreferenced external records must have valid v1 structure and unique IDs, but
their current scope, expiry and event eligibility are irrelevant.

## Deterministic failure order and kinds

Evaluation order is structural validation, candidate policy pin, claims sorted
by approval ID, then baseline requirements sorted by rule ID. Structural checks
walk native data first, then baseline, candidate, external approvals and
observation. Within a claim the order is complete-record matching, policy/scope
and actual rule content/use, expiry, review, revocations, then alternative.
Kind substitutions are rejected in the requirement comparison even if a claim
otherwise passes. A prior failure always wins; findings are not an accumulation
of every defect.

| Kind | Meaning |
| --- | --- |
| `policy_input_invalid` | Native type, closed shape, lexical, ordering, duplicate, cycle or resource violation |
| `policy_schema_unsupported` | Native schema integer other than 1 |
| `policy_kind_unsupported` | Unsupported requirement kind |
| `policy_kind_changed` | Candidate substitutes a different supported kind |
| `policy_pin_mismatch` | Candidate or waiver policy pin differs from baseline |
| `policy_scope_mismatch` | Waiver does not cover exact subject repository/path/revision |
| `policy_approval_mismatch` | Missing/different external record or before/after content mismatch |
| `policy_requirement_missing` | Baseline rule removed without an eligible exception |
| `policy_requirement_weakened` | Baseline rule weakened without an eligible exception |
| `policy_exception_unused` | Claim does not address an actual baseline weakening/removal |
| `policy_exception_expired` | Observation time is at or beyond expiry |
| `policy_review_due` | Review event occurred |
| `policy_exception_revoked` | A revocation event occurred |
| `policy_condition_unknown` | Required event observation missing or unknown |
| `policy_alternative_unmet` | Alternative verification explicitly not occurred |

Routine malformed native input returns a failure rather than propagating its
validation exception. Python call errors such as missing keyword arguments are
outside the four-argument data contract, as are interpreter/resource failure and
concurrent mutation by a caller.

## Caller trust assumptions and limits

The caller independently selects an authentic immutable baseline and materializes
all applicable rules and nearest-owner facts, authenticates Owner approvals,
verifies candidate extraction, and supplies fresh, trustworthy time and event
observations. Repository IDs and SHAs are merely syntax-checked here. Evidence
references and condition text are not fetched or interpreted.

These are assumptions, not proof. Separate files do not establish trust. An actor
able to replace both candidate and purported external approval records can defeat
those assumptions; this pure module cannot detect that. It chooses no policy
values, product defaults, cryptographic issuer, authentication App, writer policy,
credential source or deployment mechanism. It grants no privileges, approves no
waiver, publishes no check and enforces no delivery action. It makes no R0/C1,
real-consumer, shipping or complete-6DQ claim.

## Authored coverage and bounded verification

`tests/policy/test_validation.py` contains 38 stdlib unittest method declarations,
with synthetic records and subcases. Tests call only `evaluate_policy`; none
exercise private implementation helpers. The test harness reads only the reviewed
evaluator source and the three schema files (including existing finding-v1).
Its explicit source read/compile loader avoids cached bytecode and imports no
resolver or context fixture. AST inspection is limited to that same source.
The tests do not read Git metadata.

| Frozen expectation | Authored coverage |
| --- | --- |
| E01–E03 | Exact baseline; each comparator; added rules; missing and weakened rules |
| E04–E06 | Exact weakening/removal approvals; both policy pin fields; exact subject scope; no prefix/glob/range semantics |
| E07a–d | Space/Unicode/percent literals; invalid segments/controls/surrogates; no decoding, normalization, case or whitespace aliases |
| E08 | Full-record field mutations; actual before/after binding; dictionary order independence |
| E09–E10 | Expiry second edges; calendar/lexical dates; review/revocation/alternative states; missing/unknown states; every revocation |
| E11–E12 | Closed structures; all cross-kind substitutions; schema/type/grammar checks; sorted unique lists; cycles; 32-level and 100,000-node edges; shared subtrees; inert rejection of custom values |
| E13–E15 | Duplicate/unused claims; unrelated external records; sorted deterministic results; no mutation/partial results; failure precedence; safe five-field findings |
| E16 | External before/after hash and mode inspection, not candidate-controlled runtime testing |

At the original authoring handoff, verification was limited to syntax-only
AST/JSON parsing and source/whitespace inspection. The author had not imported the
evaluator or performed test collection, execution, builds or lint; that handoff
made no tests-pass claim.

On 2026-09-23, separate Standards, unmapped/cross-scope and independent SPEC
reviews completed with zero findings. Review covered the actual core, schemas,
docs and loader, and rechecked the five candidate hashes and discovery scope.
The subsequent bounded policy-only verification ran this exact command:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C /usr/bin/python3 -I -S -B -m unittest discover -s tests/policy -p test_validation.py -v
```

The run exited 0: 38 tests ran in 0.394 seconds, all OK. The evaluator, two policy
schemas and test file retained their reviewed hashes. This records completed
bounded review and synthetic-test verification, not authorization for further
execution or evidence of authentication, R0/C1, CI, real-caller acceptance, full
6DQ, PR publication or merge. Final delivery remains held.

The earlier policy-only snapshot left existing context compatibility tests
untouched and did not include the fixture-hook repair; their historical results
were not transferred to that policy-only verification. The expanded candidate
includes the fixture-hook repair. The 38-test result above remains evidence for
the bounded policy-only run, not a fresh combined-suite result or verification
of the expanded candidate as a whole.

This remains an unpublished candidate with the bounded verification recorded
above; the recorded review and test result do not imply publication or merge.
