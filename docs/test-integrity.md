# Test integrity — development candidate

The [detector](../scripts/quality/test_integrity.py) and the proposed default-on
lane in [quality.yml](../.github/workflows/quality.yml) require Owner review as
a gate change before merging. This is not a released capability or evidence of
live enforcement/adoption. Existing consumers keep their pinned behavior until
a separately reviewed full-SHA update. Ordinary test edits/deletions require a
reason and ordinary quality/AI review, **not** a separate Owner ledger or approval.
Actual policy/gate/permission changes retain their existing protections.

## Comparison

Read-only Git blobs from `merge-base(base, head)..head` are compared; neither
test sources nor caller-configured diff/textconv programs are executed. Both
inputs must be full lowercase 40-character commit SHAs with history available.
Only changed recognized test paths participate. Test directories (`Tests`,
`tests`, `__tests__`, `spec`, `specs` and singular variants) and common Python,
Swift, Go, JVM and JS/TS test filenames are recognized. A `test_*.py` tool under
`scripts/` is excluded unless in a recognized test directory. Directory matches
also include fixtures; deleting such a fixture requires explanation.

| Loss | Meaning |
| --- | --- |
| `assertion_removed` | A normalized lexical assertion occurrence in changed base test files has no identical occurrence in changed head test files. |
| `test_removed` | A recognized test name has fewer occurrences across changed head test files. |
| `skip_added` | A recognized lexical skip/disable statement has more occurrences in a head file than in the same base file. |
| `test_file_deleted` | A recognized test path was deleted, including the old path of a rename. |

Names/assertions are multisets, not total counts: unrelated additions cannot
offset losses, while identical moves among changed test files can preserve them.
Identical duplicates can substitute for one another; this is not per-test semantic
identity. A pure rename still requires a reason for the deleted path; moving code
to a non-test path does not preserve its recognized tests/assertions.

Comments and ordinary quoted/raw/multiline literals are masked before detection;
literal assertion values remain part of identity. Commenting out a suite removes
its evidence. Uncommenting an existing skip is detected even without an added
marker line. Moving a skip to another file reports a new skip in the destination.
Multiple same-line assertions and balanced multiline delimiters are recognized.
Jest skip chains include `.skip.each` (array/tagged tables), concurrent variants,
`.skip.failing`, and `xit`/`xtest`/`xdescribe` aliases; examples inside comments
or literals remain non-executable data.
The NUL-delimited Git inventory preserves literal Unicode/whitespace/quoted paths;
malformed records or non-UTF-8 Git data fail closed rather than alias filenames.

## Per-file rationale

Use exactly one `## Removed or weakened tests or policy` section (`###` also
accepted). Each affected path needs a separate line with a non-placeholder reason:

```text
- `tests/test_parser.py`: obsolete case replaced by malformed-input coverage.
- "Tests/tab\tname.swift": renamed to match the suite responsibility.
```

Heading recognition uses bounded prefix matching and linear suffix trimming,
including long whitespace runs before invalid trailing text. No PR-body size cap
or truncation is imposed; malformed headings still cannot declare a rationale.

Plain paths, backtick-wrapped paths, or JSON-quoted paths are accepted, followed
immediately by `:` and a reason. JSON quoting safely represents paths containing
newlines, tabs, quotes or backticks. Paths are exact and case-sensitive;
`tests/test_a.py.bak` cannot explain `tests/test_a.py`. Comments, fenced examples,
missing/duplicate/prefix-only headings, bare filenames and placeholder reasons
are not declarations. Inline code/emphasis/strikethrough around a whole
placeholder (for example, `` `none` ``) does not make it a reason; substantive
reasons may still contain or use code formatting. `none` is appropriate only
when no losses exist. Reasons are checked for presence, not truth: ordinary AI review must assess whether the
explanation is accurate and whether behavior/coverage remains acceptable.

## CLI and output

Run the reviewed provider engine from the caller repository root:

```sh
python3 -I -B "$SHARED_CI_CHECKOUT/scripts/quality/test_integrity.py" \
  --base "$PR_BASE_SHA" --head "$PR_HEAD_SHA" --body-file "$PR_BODY_FILE"
```

`--body-file` checks supplied UTF-8 text. With neither body option, local reporting
returns losses with `body_checked: false`, `body_status: unavailable-local`;
a local `pass` does **not** mean rationale was checked. Do not use that mode as
hosted acceptance evidence. `--live-body` instead requires `REPO`, `PR_NUMBER`
and `GH_TOKEN`, fetches the actual current body from GitHub's REST API, and
requires both live head and base SHAs to match the compared commits. Missing,
malformed or stale API data fails closed. A null API body is checked as empty.
The mutually exclusive body options never silently fall back to local reporting.

JSON stdout contains `verdict` (`pass`/`fail`), `losses` (`kind`, `file`, `detail`),
`undeclared` paths, `problems`, `body_checked`, and `body_status` (`supplied`,
`live`, `unavailable-local`, or `unavailable-error`). Exit 0 means the requested
checks passed; 1 means invalid/unavailable input or undeclared losses; 2 means
CLI usage error. A process failure or missing JSON is not a pass. Diagnostics
escape untrusted filenames rather than emitting raw workflow commands.

## Workflow/aggregate contract

`test-integrity` defaults to `true` in the candidate reusable workflow. The lane
runs on a hosted runner from the pinned provider, separately from layer selection,
using complete caller history. It fetches the live body on pull-request events,
even if `check-pr-body: false` disables aggregate's general template checks.
On non-PR events it explicitly reports not applicable; success there is not a
new diff/rationale evaluation. Its SHA output still identifies the checkout.

Aggregate always depends on the integrity job. Selected integrity must succeed,
report the expected head SHA, and report `ran: true` when selection is present;
empty selected layers cannot short-circuit it. Missing/malformed/skipped/failed
results fail closed. Explicitly disabling the input still requires a valid
unselected lane result; the option is not authorization to bypass repository
policy. This change does not alter existing consumer pins, required checks or
reviewer trust boundaries. The lane scans data; it does not run the tests.

## Limits and recovery

This is a lexical heuristic, not a grammar, coverage metric, assertion-strength
proof or test-reachability analysis. Common XCTest/Swift Testing, unittest/pytest,
Go and Jest/Vitest shapes are recognized; unknown frameworks/helper indirection,
interpolation, regex literals, unusual quoting, conditional compilation and
complex layouts require independent review. Renaming/reformatting recognized
assertions can conservatively report losses. Retaining a token does not prove it
executes; replacing one assertion with an identical copy elsewhere can match.

For losses, restore accidental changes or explain each affected file for ordinary
review. For unreadable history/body/API data, repair input and rerun for current
commits. Never use a missing report, old SHA evidence or test count as acceptance.
[Fixtures](../tests/quality/test_test_integrity.py) and
[aggregate tests](../tests/quality/test_gate.py) exercise synthetic Git callers,
lexical/parser boundaries and failure routes, not hosted rollout or 6DQ evidence.
