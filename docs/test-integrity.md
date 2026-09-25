# Test integrity (v0.2.1 candidate)

This describes the current [detector](../scripts/quality/test_integrity.py) and
its lane in [quality.yml](../.github/workflows/quality.yml), not an approved
release. The [candidate entry](../ai/README.md) records the unresolved Owner
policy A/B decision. Existing consumers retain their old full-SHA behavior
until a separately reviewed pin change. No real-consumer adoption is claimed.

## Comparison and declarations

The detector reads committed Git data from `merge-base(base, head)..head`, not
the working diff or just the last push. It does not execute test sources.
The [repository contract](../ai/repo-contract.md#test-integrity) and
[agent protocol](../ai/agent-protocol.md#3-verify-with-the-same-entry-as-ci)
define the declaration obligation; the [ledger template](../templates/test-weakening.md)
provides its format.

Loss records have `kind`, `file` (repository-relative path) and `detail`:

| Kind | Detector meaning |
| --- | --- |
| `assertion_removed` | A normalized assertion from a changed base test file has no matching occurrence among changed head test files. Literal values are retained; changing an assertion can remove its old form. |
| `test_removed` | A recognized test name has fewer occurrences across the changed head files. |
| `skip_added` | An added diff line contains a recognized executable skip/disable marker. |
| `test_file_deleted` | A recognized test source path was deleted; its recognized tests/assertions can also be losses. |

Names and assertions are multisets: unrelated additions do not offset a loss;
moving an identical occurrence between changed test files can preserve it.
Skip detection is added-line based, so moving existing skip code can still
produce `skip_added`. The scanner keeps whole-blob comment/literal context:
commenting out a suite removes its tests/assertions, but documenting a skip in
a comment or literal is not executable skip code. Git-quoted Unicode, spaces,
tabs, quotes and backslashes do not hide additions: per-file diffs use literal
paths from the NUL-delimited inventory, not decoded display headers.

When losses exist, every affected file needs a newly added ledger entry with
a reason and approver spelling. Pre-existing entries do not authorize new
losses. A supplied PR body must name those files in `Removed or weakened tests
or policy`; a missing section or `none` fails even when the ledger is present.

The first existing CODEOWNERS file wins: `.github/CODEOWNERS`, `CODEOWNERS`,
then `docs/CODEOWNERS`. An empty first file prevents fallback. The last matching
rule must name an owner for `.github/test-weakening.md`; a later ownerless rule
removes coverage. Supported glob handling includes a complete `**/` component
matching zero or more directories. Escapes, negation and bracket syntax are
unsupported by this detector and fail closed when coverage is evaluated.
This is a coverage check, not verification of owner identity/access or an
approval. The protected branch's code-owner review remains the approval gate.

## CLI

Use Python 3.9+ and Git from the caller repository root, with base/head commits
and their merge-base history available. Use the detector from the reviewed
provider checkout, not a similarly named caller script. Supply the variables
below with that checkout, full caller commit SHAs and a captured PR body file;
this is an illustrative invocation, not a consumer execution record:

```sh
python3 "$SHARED_CI_CHECKOUT/scripts/quality/test_integrity.py" \
  --base "$PR_BASE_SHA" --head "$PR_HEAD_SHA" --body-file "$PR_BODY_FILE"
```

`--base` and `--head` are required; the CLI resolves them to commits before
evaluation. `--body-file` supplies the body cross-check. Alternatively,
`--event-body` reads `pull_request.body` from `GITHUB_EVENT_PATH` when present;
the file option takes precedence. With neither a body file nor an available
event PR body, the standalone CLI checks losses/ledger/coverage but cannot
claim the PR-body obligation was checked. The workflow supplies a live body.

Normal stdout is JSON with `verdict` (`pass` or `fail`), `losses`, `undeclared`
(file paths) and `problems` (messages). Losses and errors are also written to
stderr. Exit 0 means pass, 1 means an unmet declaration requirement or evaluation
failure, and 2 means argument usage error. Invalid revisions, unreadable test
blobs and unlocatable/malformed hunks fail closed. Body-file/event read or
decode errors can terminate nonzero before JSON; absent output is not a pass.

## Workflow integration

Call `quality.yml` at the same full provider SHA as the other shared-ci
workflows and docs; the [integration checklist](integration-and-migration.md#selection-and-integrity-workflows)
covers caller setup. The relevant inputs are:

| Input | Default | Effect |
| --- | --- | --- |
| `test-integrity` | `true` | Selects the hosted integrity lane and makes aggregate require its success on the caller head. `false` is an interface option, not policy-exception authority. |
| `check-pr-body` | `true` | Controls aggregate's general template/body validation. Setting it false does not disable the integrity lane's loss/body cross-check. |
| `changed-only` | `false` | Controls command-lane selection, not integrity; see [selection compatibility](changed-layer-selection.md#compatibility). |

The lane checks out caller history, then its provider engine at
`job.workflow_sha`. On `pull_request` and `pull_request_target` it retrieves
the live PR body and runs the detector with the event's base/head. On other
events it reports that the PR check is not applicable and succeeds; that is
not a new diff-integrity evaluation. Its `tested-sha` identifies the checkout.
The reusable workflow exposes `tested-sha` only after aggregate passes, plus
`selection`; see the workflow source for the complete input/output inventory.

Integrity is independent of selected layers: a docs-only selection cannot
short-circuit it. A read/API/process failure cannot count as a successful lane.
The check scans Git blobs as data, but ordinary command lanes execute caller
commands; this does not authorize executing untrusted PR code in a privileged
review workflow. Keep the existing workflow-lint/fork guards and caller trust
boundary. This lane does not run or replace the test suite.

## Failure routes and limits

- `undeclared` or a body mismatch: inspect each actual loss; restore accidental
  changes or obtain Owner approval and follow the declaration contract.
- CODEOWNERS coverage/syntax error: inspect the first existing file and its
  last matching rule; do not treat approver text as authorization.
- `cannot read the diff` / nonzero without JSON: verify caller root, commits,
  history and body input. Repair the input and rerun; do not infer no losses.
- Aggregate failure: inspect the integrity job result and head SHA as well as
  the [aggregate selection contract](changed-layer-selection.md#3-aggregate).
  New commits require fresh checks and review; older green evidence is stale.

The engine recognizes common XCTest, Swift Testing, unittest/pytest, Go and
Jest/Vitest shapes. This is lexical matching, not a language grammar or proof
of strength/execution. Interpolation, regex literals, conditional compilation,
helper indirection, unknown frameworks, reachability and complex assertion
layouts still need independent review. Multiline calls are joined by parenthesis
depth with a 200-line bound. Repository-specific execution and policy remain
caller/Owner responsibilities.

[Integrity fixtures](../tests/quality/test_test_integrity.py) cover the
positive/negative detector boundary, including comment deactivation,
literal preservation, CODEOWNERS precedence and quoted filenames. They are
synthetic Git callers, not real-consumer rollout evidence. Release evidence
and [registry discovery](integration-and-migration.md#selection-and-integrity-discovery-gap)
remain outstanding.
