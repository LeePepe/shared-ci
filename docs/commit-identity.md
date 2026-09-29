# Commit identity

The reusable [quality workflow](../.github/workflows/quality.yml) defaults
`commit-identity` to `true`. Its step in the existing `select` job checks every
commit in `base..head`, including merge commits, for both author and committer
email. It reads raw Git metadata, not names or mailmap aliases.

The [check](../scripts/quality/commit_identity.py) belongs to the
[Quality layer](../scripts/quality/tech-context.md), alongside the PR-range
[test-integrity check](test-integrity.md); it is not reusable-workflow lint.

Accepted addresses (case-insensitive):

- `*@users.noreply.github.com`, including numeric-ID and bot addresses.
- `noreply@github.com` for **committers only**: GitHub's web-flow committer is
  used for web merges and Update branch. Authors still need their own noreply
  address, unless explicitly allowlisted.
- Additional `fnmatch` globs from `commit-identity-allow` (string, default empty).
  Separate patterns with commas or newlines; surrounding whitespace is ignored.
  Keep exceptions narrow and reviewed, for example `*@example.invalid` in a
  synthetic caller. An allowlist applies to both roles.

The check runs independently of `changed-only`, selected layers and other lane
inputs, using complete caller history and the pinned provider script. A failing
step fails `select`, which already fails `quality / aggregate`; no check names,
lane-selection rules or aggregate semantics are added. Non-`pull_request` events
and `commit-identity: false` explicitly report skipped and succeed. Disabling the
input or adding an exception is not authorization to bypass repository policy.
Existing consumers keep their pinned behavior until a reviewed provider update.

## Local check and repair

From the caller repository, run the selected provider script:

```sh
python3 -I -B "$SHARED_CI_CHECKOUT/scripts/quality/commit_identity.py" \
  --base "$PR_BASE_SHA" --head "$PR_HEAD_SHA" --root .
```

`--allow` is repeatable and accepts the same comma/newline-separated globs.
Exit 0 means clean (including zero commits); 1 reports offending short SHAs,
roles and emails; 2 means invalid arguments or unavailable Git input. Base and
head must both resolve to commits; an empty or unknown revision never passes.

To repair a branch, set `git config user.email` to the noreply address from your
GitHub email settings. Rewrite **every offending branch commit**, correcting
both identities: interactive rebase with `edit`, then
`git commit --amend --no-edit --reset-author` and `git rebase --continue` is
appropriate for your own commits. Preserve attribution when repairing commits
by others; provide their correct author identity explicitly instead of resetting
it to yours. Amending only the latest commit does not fix earlier offenders.
Re-run the check over the full range; coordinate any history rewrite before
updating a published branch.
