# Stuck-PR bot

The reusable workflow reports PR signals in the calling repository. It supports
`workflow_call` and `workflow_dispatch`; the reusable provider deliberately has
no schedule. Consumers own a unique, staggered schedule in their caller (for
example `7,37 * * * *`) and pin the provider by its full SHA.

Inputs are finite positive numbers unless noted: `failure-hours` (2),
`open-hours` (24), `stale-days` (14), `draft-days` (7),
`auto-merge-grace-minutes` (30), and `thread-hours` (24). String inputs are
`mention-allowlist` (empty), `summary-assignee` (empty), `exclude-prs` (empty),
and `auto-merge-exempt-prs` (empty). PR lists are comma-separated positive
integers. An excluded PR is removed before detail queries, comments, summary,
and persisted state. An exempt PR is exempt only from missing-auto-merge and
behind-branch reasons.

The bot classifies required check failures, merge conflicts, requested changes,
behind branches without auto-merge, and missing auto-merge after its grace
period as actionable. Drafts always remain summary-only; stale PRs, old Drafts,
pure waiting older than `open-hours`, old unresolved non-outdated threads,
manual review requests, and the `owner-review` signal are summary-only. Age
adds context and never independently causes a PR comment. Unknown merge state
is not treated as a conflict.

Only the PR author is eligible for a mention, and only when their login is in
`mention-allowlist`; all untrusted text is quoted and neutralized. GTT markers
are reduced to `present` or `absent` and identifiers are never copied into
public reports. The bot does not change labels, repair, rerun, approve, alter
auto-merge, or merge.

The summary issue is bot-owned and titled `[stuck-PR bot] open stuck PRs`.
Every successful full scan writes `last_run_at` in UTC and a versioned
`stuck-pr-bot:state:v2` JSON comment containing current entries and history.
Actionable entries receive one v1 head-marked PR comment; repeat failures update
the summary only. Summary-only entries keep the issue open without PR comments.
An empty result closes an existing bot-owned summary. API or reconciliation
failure fails the run and never publishes a partial result.

The workflow checks out only the selected provider revision and never checks
out or executes PR code. It uses only the calling repository token with
`pull-requests: write`, `issues: write`, `checks: read`, and `contents: read`.
Offline behavior and workflow-contract tests run through `scripts/verify`.
