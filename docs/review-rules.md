# Trusted repository rules input

The Codex and Kimi review wrappers read the selected rules file from the exact
`BASE_SHA` Git commit, not the checkout, index, PR head or linked documents.
`rules-file` / `REVIEW_RULES_FILE` selects a repository-root-relative path;
omitted or empty selects legacy `AGENTS.md`. An invalid explicit path never
falls back to AGENTS. The file must already exist in the trusted base before
a consumer switches its review caller to that path.

The selected base tree entry must be a regular file (`100644` or `100755`).
Symlinks, directories, gitlinks, missing/untracked files, absolute paths,
traversal and noncanonical path components are rejected. Spaces and Git glob
characters in filenames are literal. Backslashes and control characters in
paths are unsupported. `BASE_SHA` must be a full lowercase commit SHA; local
Git replacement refs cannot substitute another object for it.

Rules must contain nonempty UTF-8 text, with no binary control characters
(other than tab, CR and LF), and be at most **24,000 bytes**. Oversized policy
is rejected, never truncated. Both wrappers preserve the complete selected
text, including its ending newlines, through the required `REPO_RULES` prompt
placeholder. Placeholder-looking text inside policy or diff data is not
recursively substituted.

Invalid rules prevent a model invocation, including when the PR diff is empty.
Codex reports unavailable and fails closed; Kimi reports unavailable but stays
advisory (exit zero). Legacy default selection is preserved, not legacy silent
acceptance of missing or invalid AGENTS. No required-check names or fork trust
boundaries change.

Kimi is always advisory and never a required check. A missing runner CLI makes
the review job **skipped**, with an unavailable warning, step summary and sticky
PR comment. Later review failures report **unavailable**, never pass, in the
warning, summary and comment (when publication is possible). Neither case fails
the workflow or blocks merge; a successful availability probe is not a review.
The probe and wrapper run in the same execution job. The final `kimi-review`
check runs only when that wrapper emits `completed=true` after validating an
actual model verdict (pass or advisory findings). Missing CLI, later unavailable
results and empty diffs leave that check skipped, even if the advisory execution
job exits zero. A CLI disappearing after the probe cannot produce a successful
review check. Comment publication remains best-effort; no caller input,
permission or required Codex gate changes are needed.

## Directory-mode adoption

AGENTS may be only an index. A tool-free reviewer cannot follow its links:
select a complete protected review guide containing the applicable repository
policy, not merely pointers to protocol/development documents. Keep that guide
within the byte limit and verify its rendered policy sentinels. Protect its
source with effective CODEOWNERS and the repository's actual server rules.
Reading a complete file does not prove policy completeness or effective server
protection; these still need content review and independent readback.

Establish the guide on the trusted base before changing the consumer review
route. Upgrade to a reviewed published provider revision deliberately; an old
provider pin does not gain this validation retroactively. Rollback restores the
recorded compatible caller/provider configuration, never rewrites a provider
revision or disables required gates. This source change does not migrate caller
pins, install runners or change live settings.

The diff-size budget and architecture-facts reader are unchanged. Rules admission
does not certify other context as complete or execute any PR-head source.
Tests use real local Git base/head
objects and stub model/GH commands, not hosted or product-adoption evidence.

## Codex Target scope

A PR may opt into scoped Codex blocking by including one section outside fenced
code examples in its description:

```markdown
## Target scope

### Paths
- `scripts/review/**`
- `.github/workflows/codex-review.yml`
- `tests/review/**`
- `docs/review-rules.md`

### Acceptance
- Existing shared-ci tests pass.
- Scoped findings and changed-file coverage have regression tests.
```

Paths are case-sensitive, repository-root-relative literal file paths or subtree
prefixes ending in `/**` (which covers every file beneath that directory).
Other globs, absolute paths, traversal, backslashes and control characters are
unsupported. Use backticks around each path. Both `### Paths` and `### Acceptance`
need nonempty, single-line `- ` bullet lists; no other content belongs inside
the section. A subsequent level-one or level-two heading ends it. Duplicate,
malformed or over-8,000-byte scope sections make Codex unavailable and fail
closed, including for an empty diff. A heading in a fenced example does not opt
in. The section is parsed from the same complete PR API response used for
title/body review, before the existing 8,000-byte body display cap. A separate
quoted JSON data block supplies the complete admitted declaration to the model.

The scope and acceptance text remain untrusted author data. They grant no
repository-policy exception, Owner approval, execution permission or authority
to instruct the reviewer. The model evaluates acceptance items against the diff
and trusted rules and reports substantiated findings. After validating the
original verdict, the wrapper applies these rules:

- Any problem introduced or worsened by this diff blocks, wherever its fix
  belongs. This includes correctness defects and mandatory-rule/red-line
  violations introduced by the change; excluding the fix path grants no exception.
- Failures of the declared Target's acceptance items block, including pre-existing
  failures and failures whose fix belongs outside the declared paths.
- Any security, privacy or data-loss problem blocks, including pre-existing
  problems. There is no P0 exception threshold.
- Only pre-existing non-security problems that the diff did not introduce or
  worsen and that do not fail Target acceptance become **Follow-ups (non-blocking,
  pre-existing)** in the sticky comment. This also applies to files inside the
  declared paths: classification depends on the problem's origin, not its fix path.
- Every changed file must match a declared path. A mismatch adds a blocking
  finding even when the model returns pass. The check uses the complete literal
  NUL-delimited path list, with rename detection disabled so both old and new
  paths (and deletions) must be covered.

Codex's output schema requires three fields on every blocker: boolean
`introduced`, boolean `acceptance_failure`, and nullable `safety_category`
(`security`, `privacy` or `data_loss`, otherwise `null`). A pre-existing
classification requires evidence that the problem existed on base and was not
introduced or worsened by this diff. When the evidence is insufficient, the
reviewer must set `introduced` to true. With declared scope, security/privacy/
data-loss problems must be reported as blockers rather than notes regardless of
origin. Missing/invalid classification or a noncanonical finding path makes the
verdict unavailable and fails closed; no ambiguous finding is silently deferred.
The model judges origin, Target acceptance and safety; the wrapper enforces the
resulting classification and changed-path coverage. Local stub tests prove that
enforcement, not real model classification accuracy.

With no declaration, the existing blocking behavior is unchanged. Kimi remains
advisory and does not apply Target scope. All existing rules/Owner-input
validation, complete-diff byte limits, fork isolation, publication requirements
and exact-head evidence requirements remain in force. This provider change
does not update any consumer SHA or install a server setting. Consumers pinned to older provider SHAs keep their existing behavior;
adoption requires a separate pin update. Callers must re-run on PR description
edits as described below so a changed declaration receives a fresh review.

## Codex review rounds

Codex records the complete effective verdict and review-input snapshot in a
bounded, compressed data field in its sticky comment. It reads that field through
the PR comment API on each run. The comment author must be the GitHub Actions
bot; an updated comment must also have that bot as its last editor (checked
through GraphQL). A human-edited or forged marker cannot authorize reuse. This
trusts the repository's Actions bot and trusted workflows that can act as it;
the state is review data, never repository rules or Owner authority.

The provider handles these cases:

1. No previous sticky review: the initial full review and gate behavior stay
   unchanged.
2. A new descendant head with usable previous state and unchanged base SHA and
   merge-base: supply all previous findings,
   `previous-head...current-head` as the repair delta, and the complete PR diff
   as context only. Recheck previous findings and repair regressions without
   rescanning unchanged code. Changed review inputs are supplied too.
3. The same head with identical title, body, base SHA/ref and merge-base, complete
   rules and admitted Owner decision set: reuse the effective pass or blocking conclusion,
   without invoking the model. Publication of the review record remains required.
4. The same head and unchanged base SHA and merge-base with changed inputs:
   supply the changed inputs and previous findings for reconsideration, with the
   complete diff as context only. Adding
   an admitted `Owner decision:` comment therefore forces reconsideration, even
   without a push. Removed or no-longer-admitted decisions also change the input.

A changed base SHA or merge-base always forces a full review fallback, whether
the head is unchanged or new, because it can expose code absent from the previous
PR diff.

Input snapshots compare complete title/body values, including text beyond the
model display cap. State is bound to the repository, PR and a digest of Review
source/template/schema files and all Context Python modules, including dynamically
loaded helpers. Changes to these provider dependencies invalidate stored verdicts.
Legacy/malformed/unavailable state, failed comment reads or an unavailable
previous-head delta cause a full review fallback explicitly identified in the
output. Storage beyond the comment/state capacity is never truncated into a
reusable record: the output notes that the next run will fall back. Invalid
current rules, Owner input, scope or complete-diff budgets still fail closed
before any reuse; a failed model/invalid verdict never creates reusable state.

On re-review, V2 blockers remain: delta-introduced problems, unresolved previous
findings, declared acceptance failures, red-line violations, and any security,
privacy or data-loss problem. The last two categories block even outside the
delta; the reviewer does not rescan unchanged code to search for them. The
schema's `unresolved` and `red_line` flags preserve those findings through scope
filtering; `introduced` refers to the current repair delta or changed inputs.
Other pre-existing problems become non-blocking follow-ups. Changed paths
outside the declared Target still block. Missing round classification fails
closed. On the first/full-fallback review, existing scope behavior is preserved.

This implements V3's bounded re-review input: original findings, previous/current
heads, repair delta and fresh evidence for the new head, without opening a new
full scan. It does not add a retry counter, reset a Task's review history, or
replace the coordinator's two-round escalation or independent Target acceptance.
Kimi remains advisory and does not use this state. No caller pins are upgraded:
only provider source gains these behaviors; existing consumers need separate
adoption. Stub tests cover transitions and gate enforcement, not real model
classification or live caller enablement.

## Owner decision comments

PR title and description are fetched at review time as untrusted author input,
never as instructions or Owner decisions; the title is capped at 300 UTF-8 bytes
and the body at 8,000 UTF-8 bytes, with generated truncation markers. The title is
flattened to one line and the body is quoted per line with `> `, under distinct
`> Title:` and `> Body:` labels. `review.yml` triggers on `opened`, `synchronize`,
`reopened` and `edited`, so title/body/base edits re-run review and gate (a base
change changes the diff). PR-keyed concurrency cancels superseded runs; a
cancelled run's gate is cancelled, not successful, and only the newest run's gate
result stands. Callers must adopt the updated `templates/review.yml` to gain this
behavior. Residual risk: between an edit and creation of the new run's checks,
an earlier green result may briefly remain visible; auto-merge could race in
that window.

Rationale (W5): in the 2026-09 zero-knowledge workflow test (probe P4), an agent
PR stated in its description that the Owner had requested the change, without
any Owner-authored source. The reviewer then received only the diff, so the
claim was not visible to it, and neither review nor CI flagged it. Supplying the
title (capped at 300 UTF-8 bytes) and description (capped at 8,000 UTF-8 bytes)
as quoted untrusted data, admitting only verified
`Owner decision:` comments as authority, and re-running review on edits narrow
that gap. Remaining risks: a claim confined to commit messages is still not
supplied to the reviewer; the stale-green window above; and callers are covered
only after they adopt this version and the updated `templates/review.yml`.

Codex optionally consumes PR issue comments as trusted, PR-scoped decisions.
Set the reusable workflow's `owner-user-id` to the Owner's numeric GitHub user ID
through trusted caller configuration (`OWNER_DECISION_USER_ID` for the wrapper).
The default is empty: no Owner-decision comment read is made (Codex still reads
its sticky round state). Kimi does not consume these
decisions. The trusted workflow reads comments at run time with its workflow
token; it never executes or reads PR-head code to obtain them.

`owner-user-id` must be a human Owner account, never an App/bot account:
otherwise an agent acting as that account could authorize its own exceptions.
A comment qualifies only when:

- Its integer author ID matches the configured Owner ID and `user.type` is
  `User` (Bot and Organization authors are rejected even with a matching ID).
- Its first non-empty line, after stripping leading/trailing whitespace, starts
  with the case-sensitive marker `Owner decision:`. CRLF and CR count as newlines;
  leading blank or whitespace-only lines are allowed.
- `created_at == updated_at`.

The marker prevents casual Owner comments from counting as decisions. Edited
comments are ignored: repository writers can edit others' comments, and REST
exposes no editor identity. The Owner must post a new comment.

At most **5** decisions, **4,000 UTF-8 bytes per body**, and **12,000 bytes total**
are admitted. Admitted bodies cannot contain control characters except tab, CR
and LF (C1 controls are forbidden). API, malformed-record, invalid-configuration,
text or bound errors make Codex unavailable and fail closed before the model,
even for an empty diff. Nothing is truncated or silently dropped to fit bounds.
Bodies are line-quoted and prompt placeholders/delimiters neutralised; headers
identify comment IDs and creation times. Logs contain the admitted count, not
comment bodies.

A decision is the Owner's PR-level decision: it covers all later pushes to the
same PR without naming a head SHA. The trade-off is that later pushes are not
re-authorized per commit.
Each decision covers only the specific finding/file/change it explicitly names or quotes; it never extends to unrelated or newly introduced changes in later pushes; blanket approvals authorize nothing. Changes and final merge never require an Owner decision, human approval or
code-owner approval, including protected paths, gates, CI, review rules and
CODEOWNERS. Required checks and AI review on the exact head remain mandatory.

A decision may confirm intent or authorize a scoped repository policy/test
exception. Covered blockers become notes citing the comment ID.
It cannot override red lines: committed secrets/tokens/credentials, personal
identifiers or local paths, CI trust-boundary breaks (PR code running with secrets
or on self-hosted runners, PR content made trusted/executable), prompt injection,
or clear correctness/security bugs. Claims in diffs, commit messages or file
contents have no Owner-decision authority.

For PR-controlled text actually supplied to the reviewer, an unverifiable Owner
request/approval claim lacking an admitted Owner decision in the trusted
Owner-decisions block is always a non-blocking note, including when used to
justify protected changes (CODEOWNERS paths, policy/gate/CI/ruleset/schema files,
or removed or weakened tests). Mention any link as unverified so a human can
check it. Missing approval or an Owner decision never blocks by itself, even
when supplied repository rules retain an older approval requirement. Independently
substantiated red-line, correctness and security problems still block.
Only an admitted Owner decision in the trusted Owner-decisions block can verify
such a claim. Links in PR-controlled text (title, description or diff) are
author-controlled and do not verify a claim. The reviewer cannot verify their
contents or authorship.

To use: the Owner posts a **new comment whose first line starts with
`Owner decision:`**, followed by the decision, then re-runs the `codex-review` job.
This is optional review context. It is never a prerequisite for a change or
merge and cannot substitute for required checks or waive red lines.

Known limitation: the unedited check compares second-resolution REST
timestamps, so an edit within the same second as creation is indistinguishable
from an unedited comment. A writer editing the Owner's comment would have to
race creation within that second; exact editor identity would need GraphQL,
which this reader deliberately does not use.
