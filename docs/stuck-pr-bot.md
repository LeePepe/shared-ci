# Stuck-PR bot

The [reusable workflow](../.github/workflows/stuck-pr-bot.yml) reports non-Draft
open PRs in the **calling repository**. It runs hourly at minute 17 and supports
manual dispatch. Consumers copy the [caller template](../templates/stuck-pr-bot.yml),
replace its placeholder with the delivered full provider SHA and coordinate that
pin with their other shared-ci references. Keep the hourly schedule and manual
trigger in the caller; reusable workflows do not install caller schedules.

| Input | Default | Meaning |
| --- | --- | --- |
| `failure-hours` | `2` | Minimum hours since the earliest current failed required check completed on the exact head |
| `open-hours` | `24` | Report a PR open longer than this many hours, independently of check state |

Both inputs must be finite positive numbers; fractional hours are supported.
Invalid inputs fail before API access or writes. Scheduled provider runs use the
same defaults. No secret inputs or inherited secrets are needed. Only the
calling repository's `GITHUB_TOKEN` is used, with exactly `pull-requests: write`,
`issues: write`, `checks: read` and `contents: read`. The token reads PRs and
checks and writes only issue/PR comments and the bot's summary issue. The bot
never modifies code, PR metadata or labels, repairs, reruns checks, approves,
changes auto-merge or merges. Required checks remain unchanged.

The runner checks out only the reusable workflow's own provider at
`job.workflow_sha`, with persisted credentials disabled. It never checks out or
executes PR code. Repository concurrency serializes overlapping report runs.

## Detection and evidence

The GraphQL query reads the PR's exact head commit and all status-rollup pages.
GitHub's `isRequired(pullRequestNumber: ...)` identifies required checks without
an admin ruleset/protection read. For check runs, the latest attempt per name and
app wins; legacy status contexts use their latest creation time. Failed,
timed-out, cancelled, action-required, startup-failed or stale required checks
count as failure. Optional failures, pending checks, success, skipped and neutral
checks do not trigger the failure condition. Age can independently trigger a
report even if checks are healthy or absent.

The failure clock starts at the earliest completion time among the current
failed required checks on the exact head. Check runs use `completedAt`; legacy
commit statuses use the failed status event's `createdAt`. A report is due when
that timestamp is at least `failure-hours` old. Comments and other PR activity
never reset the clock. The report includes this timestamp and elapsed hours;
it does not claim an exact push time or use PR activity/commit author dates.
Missing completion evidence for a current failed required check fails the run.

A new head is evaluated using its own checks and completion times. A rerun's
latest attempt replaces the previous attempt; recovered checks no longer count.
Already reported heads receive no duplicate comment. The 24-hour age condition
remains independent of check completion and all other activity.

Before publishing, the bot refreshes head, draft/open state and checks. A changed
head, newly Draft/closed/merged PR or recovered PR gets no stale report. A head
change during pagination fails the run. API errors fail rather than count as
healthy observations; the read phase finishes before any writes. The next
scheduled run can observe a stable state. Check names are escaped as data and
mentions are neutralized.

## Reports and recovery

Each PR report includes the head, failed required checks, elapsed hours and
“Bot 不会修”. A hidden head marker in a `github-actions[bot]` comment makes it
idempotent: the same head is commented on once, even across reruns or recovery
and recurrence. Another author cannot suppress a report by copying its marker.
Comment and issue lists are fully paginated.
Exceptionally large failed-check lists are bounded to fit GitHub's comment body
limit, with an explicit remaining count and direction to the PR's checks tab.

The bot creates or updates its own issue titled
`[stuck-PR bot] open stuck PRs`, listing every PR detected as stuck during the
run as a compact PR-number list; check and wait details remain in PR comments.
It updates only issues with its own author and summary marker, reuses a
closed summary on recurrence, and closes it when no stuck PR remains. A healthy
repository with no existing summary gets no write. API failures are surfaced as
a failed Actions run; an interrupted publication is reconciled by the next run.

Local behavior/API-fixture tests run through `scripts/verify`. They cover report
decisions (including recent comments after old failures), completion thresholds,
pagination, deduplication, latest check attempts, new heads, race avoidance,
summary creation/update/closure/reopening and write boundaries. They do not
establish real caller enablement or the separate live stuck-PR acceptance.
