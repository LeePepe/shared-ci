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
public reports. The bot emits an actionable supervision signal; it does not
itself change labels, repair, rerun checks, approve, alter auto-merge, or merge.
For an actionable PR, the Goal TL, PRM, or coordinator routes repair to the
original writer or a legitimate proxy and follows through to the merge
read-back.

The summary issue is bot-owned and titled `[stuck-PR bot] open stuck PRs`.
`summary-assignee`, when configured, is the observation recipient; it is not
an Owner-default or a repair gate. The summary remains an observation surface
for supervision consumers.
Every successful full scan writes `last_run_at` in UTC and a versioned
`stuck-pr-bot:state:v2` JSON comment containing current entries and history.
Actionable entries receive one v1 head-marked PR comment; repeat failures update
the summary only. The marker is
`<!-- stuck-pr-bot:v1 head=… -->`; same-head dedupe remains byte-compatible, so
the same head receives no repeat comment. Summary-only entries keep the issue
open without PR comments. An empty result closes an existing bot-owned summary.
API or reconciliation failure fails the run and never publishes a partial result.

## Repair signal

An actionable comment records the exact `head` and the human-readable reasons;
the summary records the PR `number`, exact `head`, `classification`, compact
reason codes, age, auto-merge, mergeability, review decision, Draft status,
unresolved-thread count, GTT presence, stale/exception flags, and repeat-failure
state. These fields are observation evidence, not a repair performed by the
bot.

Supervision mirrors an actionable result into the repair queue at
`_watch/prmon/repair-queue/` using schema `prmon-repair-queue/v1`:

| Queue field | Stuck-PR signal source |
| --- | --- |
| `repo` | Calling repository (`owner/name`) |
| `pr` | Summary `number` / PR number |
| `head_sha` | Comment and summary `head` |
| `status` | Queue lifecycle: `open`, `in_repair`, `done`, or `skipped` |
| `actionable_reason` | First applicable: `required_check_failure`, `auto_merge_not_enabled`, `conflicting`, `changes_requested`, or `behind` |
| `failure_hours` | Check-failure age when present; otherwise omit |
| `checks_failed` | Failed required-check names from the observation |
| `mergeable` | Summary `mergeable` / merge-state observation when present |
| `auto_merge` | Summary `auto_merge` |
| `hold` | Supervision ledger hold, not inferred by this bot |
| `dangerous` | Supervision classification, not inferred by this bot |
| `created_at`, `updated_at` | Queue writer timestamps |
| `source` | `stuck-pr-bot` |
| `goal_hint` | Optional supervising Goal identifier |

The queue's `actionable_reason` enum is authoritative; pure waiting, stale,
Draft, age-only, and other summary-only observations do not create queue files.
GitHub Actions cannot write the Mac mini disk, so the Mac mini heartbeat or the
coordinator mirrors the comment/summary evidence into the queue. Wiring that
mirror into the prmon heartbeat is outside this repository change.

The workflow checks out only the selected provider revision and never checks
out or executes PR code. It uses only the calling repository token with
`pull-requests: write`, `issues: write`, `checks: read`, and `contents: read`.
Offline behavior and workflow-contract tests run through `scripts/verify`.
