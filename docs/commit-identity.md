# Commit identity

The reusable [quality workflow](../.github/workflows/quality.yml) defaults
`commit-identity` to `true`. Its step in the existing `select` job checks every
commit in `base..head`, including merge commits, for both author and committer
email. It reads raw Git metadata, not names or mailmap aliases.

The [check](../scripts/quality/commit_identity.py) belongs to the
[Quality layer](../scripts/quality/tech-context.md), alongside the PR-range
[test-integrity check](test-integrity.md); it is not reusable-workflow lint.

## Modes and allowlist

`commit-identity-mode` is a string input with default `basic`, matching the CLI's
`--mode basic|noreply` (default `basic`). Any other value exits 2, failing closed;
the workflow validates the mode even before its event/disabled skip checks.

In **basic** mode, both author and committer are rejected only for:

- No `@`, or an empty local part or domain when split at the last `@`.
- A domain with no `.`.
- A domain equal to or ending in `localhost`, `.local` or `.localdomain`.
  Domain checks are case-insensitive and strip one trailing `.` first, so
  `@localhost` and `@LOCALHOST.` are rejected too.

Everything else passes: public mail domains, example domains, GitHub user/bot
noreply addresses and `noreply@github.com` in either role. This is a basic sanity
check, not full email syntax, deliverability, ownership or privacy validation.

**noreply** mode preserves the strict policy. Accepted addresses
(case-insensitive):

- `<user>@users.noreply.github.com` or `<id>+<user>@users.noreply.github.com`,
  including bot addresses (`<id>+<name>[bot]@...`). The local part must follow
  GitHub login rules (letters, digits and single inner hyphens, at most 39
  characters, optional `[bot]` suffix) with an optional positive numeric `<id>+`
  prefix; anything else (empty, `_`, `.`, brackets, doubled or edge hyphens) is
  rejected, and basic-mode malformations never pass.
- `noreply@github.com` for **committers only**: GitHub's web-flow committer is
  used for web merges and Update branch. Authors still need their own noreply
  address, unless explicitly allowlisted.
- Explicitly allowlisted addresses.

In **both modes**, `commit-identity-allow` (string, default empty) adds
case-insensitive `fnmatch` globs that override rejection for either role.
Separate patterns with commas or newlines; surrounding whitespace and empty
entries are ignored. Every nonempty pattern must contain `@`. Bare `*`, `*@*`
and patterns containing only `*`/`?` wildcards on both sides of `@` are invalid.
Invalid patterns exit 2 with a diagnostic naming the JSON-escaped pattern, even
for an empty commit range. Keep exceptions narrow and reviewed, for example
`*@example.invalid` in a synthetic caller.

After configuration validation, the check prints the effective mode and the
effective allow patterns (lowercased, as a JSON list) on stdout before reading
the commit range. An empty allowlist is printed as `[]`.

The check runs independently of `changed-only`, selected layers and other lane
inputs, using complete caller history and the pinned provider script. A failing
step fails `select`, which already fails `quality / aggregate`; no check names,
lane-selection rules or aggregate semantics are added. Non-`pull_request` events
and `commit-identity: false` explicitly report skipped and succeed when the mode
is valid. Disabling the
input or adding an exception is not authorization to bypass repository policy.
Existing consumers keep their pinned behavior until a reviewed provider update.

## Enabling strict mode per repository

First the Owner switches local Git's `user.email` and GitHub's web commit email
setting to the GitHub noreply address from email settings, such as
`<id>+<user>@users.noreply.github.com`. Check both author and committer identities
on existing PR commits and repair offenders before enabling strict enforcement.
Then add this to that repository's pinned quality caller's `with` block:

```yaml
commit-identity: true
commit-identity-mode: noreply
```

Omitting `commit-identity-mode` selects `basic`; adopting this provider without
the explicit `noreply` setting no longer requires noreply-only identities.
This is a per-repository choice, not a change to the shared default or to
required check names. Provider pin changes and policy exceptions still need
their existing review.

## Local check and repair

From the caller repository, run the selected provider script:

```sh
python3 -I -B "$SHARED_CI_CHECKOUT/scripts/quality/commit_identity.py" \
  --base "$PR_BASE_SHA" --head "$PR_HEAD_SHA" --mode basic --root .
```

Use `--mode noreply` for a strict caller. `--allow` is repeatable and accepts the
same comma/newline-separated globs and validation rules.
Exit 0 means clean (including zero commits); 1 reports offending short SHAs,
roles and reasons (for example `local hostname domain`, `missing domain` or
`not a GitHub noreply address`), without logging raw email addresses; 2 means
invalid configuration, arguments or unavailable Git input. Base and
head must both resolve to commits; an empty or unknown revision never passes.

To repair a branch in basic mode, set `git config user.email` to a valid address
with a non-local, dotted domain; a GitHub noreply address also works. In noreply
mode, use the noreply address from GitHub email settings and update the GitHub
web commit email setting too. Rewrite **every offending branch commit**, correcting
both identities: interactive rebase with `edit`, then
`git commit --amend --no-edit --reset-author` and `git rebase --continue` is
appropriate for your own commits. Preserve attribution when repairing commits
by others; provide their correct author identity explicitly instead of resetting
it to yours. Amending only the latest commit does not fix earlier offenders.
Re-run the check over the full range; coordinate any history rewrite before
updating a published branch.
