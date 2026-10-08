# Construct SDK and internal TestFlight releases

Use this guide when creating or updating repository Actions release wiring.
Read it and the chosen template from the same delivered full provider SHA.
The workflow skill routes integrations here; this is the shared construction
contract, not a publishing service or an enabled workflow. `quality.yml` checks
quality; it neither builds a distribution for publication nor uploads one.

## Integrate in order

1. Read the repository's current release instructions, distribution contract,
   protected checks and approved channels. Record its actual build commands,
   release baseline, platform, runner and existing credentials interface.
   Missing permission or configuration is a prerequisite, not a default to guess.
2. Select the [SDK template](../templates/release-sdk.yml) or
   [TestFlight template](../templates/release-testflight.yml). They are deliberately
   outside `.github/workflows`. Record the exact delivered provider SHA in the
   consumer's versioned guide and preserve that binding on later updates.
3. Replace the workflow-name placeholder with the repository's post-merge check
   workflow. Implement the two deliberately failing `prepare` and `publish`
   steps using reviewed repo-owned commands, under the interfaces below. The
   read-only `prepare` adapter runs both before queue admission and after queue
   wait: wire the same repo-owned implementation into both places. Keep
   data in quoted environment variables; do not interpolate event text into
   shell source or evaluate a command supplied by a PR or artifact.
4. Keep SDK/TF commands, platforms and channels repository-specific. Start from
   read-only workflow permissions; grant only the independently authorized
   publication step/job permissions and credentials. Pin added actions, retain
   self-hosted fork protections and existing checks. A template's presence does
   not authorize credentials, runner changes, settings or enablement.
5. Test the actual adapted workflow and commands with safe fixtures before its
   normal source review/CI. Enable only through the applicable approval path.
   Record separately source delivery, fixed-version availability, skill wiring,
   repository wiring, enablement and an authorized successful real release.

Ordinary execution belongs to repository GitHub Actions after appropriate
merged content and checks, not an agent receiving every release as a task.
There is no new manual per-release product acceptance step. Required checks,
accurate-head review and existing activation holds still apply.

## Candidate and cumulative content

The templates admit only a successful same-repository default-branch push
`workflow_run`, before checkout. They checkout its exact `head_sha`, never the
pull-request head, and use no persisted checkout credential. This originating
run is a wakeup signal, **not proof that every necessary check has passed**.

The repo-owned `prepare` step must retrieve trustworthy check evidence for
`CANDIDATE`, including all necessary workflow/check identities and their latest
applicable attempts. Reject missing, pending, failed, cancelled, skipped,
ambiguous or wrong-SHA evidence; an unrelated green check name is insufficient.
Do not trust a PR-supplied artifact or an author's claimed status. Select the
wakeup workflow so required checks normally finish before preparation; otherwise
report the unresolved result without adding a retry mechanism.

Produce these step outputs only from those actual checks and the repository's
release inventory (these are local Actions wiring, not a new persistent schema):

| `prepare` output | Required meaning |
| --- | --- |
| `checked-sha` | Exact candidate whose complete necessary checks were verified |
| `required-checks` | `success` only after that verification |
| `baseline` | Full SHA of the last successfully verified release for this unit/channel |
| `publishable` | `true` or `false` from all unreleased changes between baseline and candidate |

For initial publication, explicitly establish the repository's baseline and
version procedure; an absent baseline fails rather than silently becoming HEAD
or HEAD's parent. If the last result was unknown, reconcile the actual existing
distribution before selecting a baseline; this is not permission to resend it.
Use the complete cumulative diff, including generated inputs, package contents
and shipped guides. A final notes-only commit must not hide an earlier unreleased
library change. Non-shipped documentation/tests alone do not cause a release;
there is no blanket documentation exclusion. Classifier policy and executable
tests belong to the repository's actual published content, not this template.

The unsynchronized `admit` job runs `candidate`, `prepare` and `eligible` before
any publication concurrency. `eligible` validates exact checkout, current
fetched default-branch tip, successful candidate-bound checks and an ancestor
baseline. Only successful admission with `release=true` allows the dependent
`release` job into its concurrency group. Rejected events and no-content results
never consume a publication queue slot. False means no publication, not a
successful-release receipt. The template does not discover checks or classify
content by itself.

Publication uses **job-level `queue: max` and `cancel-in-progress: false`**.
The [GitHub concurrency contract](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
documents that the default single pending slot replaces older pending work even
when running work is not cancelled. Admission alone cannot fix this: an older B
can finish admission first but reach the queue after newer C. The max queue keeps
both; a stale B cannot remove pending C. Ordering is by when jobs start waiting,
not by commit time or workflow dispatch time; correctness does not assume either
order. Keep the group channel/unit-specific when a repository has several.

After acquiring that slot, `release` checks out the admitted exact candidate and
runs `prepare` and `eligible` **again**. Refresh trusted remote state and read
checks, last successful release baseline and cumulative content anew; do not
copy those observations from `admit` outputs. This rejects a stale B and prevents
republication after an earlier queued run already published the same content.
Immediately before an external write, the repo-owned publisher rechecks
candidate/checks, baseline and version/build uniqueness to cover subsequent
changes. In-flight uploads remain non-cancelling.

`queue: max` retains at most **100 pending jobs**. New jobs beyond that capacity
are cancelled by GitHub, not successful releases; record that unresolved native
run result under the failure contract below. This is bounded platform queuing,
not an unbounded durable delivery guarantee or a new retry mechanism. Verify
the target GitHub installation supports this property before enablement; never
silently fall back to the replacing single slot. No hosted scheduling or queue
capacity validation is claimed by local source tests.

## SDK adapter

The SDK `publish` step builds the repository's actual release unit and uses its
existing distribution channel. Preserve immutable versions, compatibility and
the corresponding versioned `ai/` documentation. A private package distributed
as a verified tag-built tarball does not become an npm registry publication;
exact-tag Swift consumption stays exact-tag Swift consumption. Multiple units
need their own applicable evidence rather than one unit standing in for all.

Verify the remotely retrievable version, candidate binding, required files and
artifact digests, plus the existing external artifact/consumer acceptance
contract. Only then emit `published-sha=CANDIDATE` and
`verified-artifacts=success`. Build/test success or creating a local archive is
not release verification. An existing version at another revision or an unknown
publication result fails; never overwrite/move a version or silently republish.
Consumer upgrade PRs are outside this release workflow, while separately required
architecture-upgrade consumption and rollback evidence remain required.

## Internal TestFlight adapter

The TF `publish` step owns signing/build/upload and reads Apple state using the
repository's existing authorized interface. Set `expected-app`,
`expected-platform` and `expected-build` from the exact candidate's actual
built/uploaded identity, not from the latest Apple build. A build identifier
must distinguish the applicable version/build combination when the product does
not guarantee globally unique build numbers. Preserve the authorized platform
and internal groups; no expansion to another platform, external groups or Store.

Query that exact build after processing and verify availability to **every**
agreed internal group, with a nonempty expected group set. Emit `actual-app`,
`actual-platform`, `actual-build`, `processing=complete`,
`internal-groups=available` and `published-sha` only from that bound evidence.
Neither upload success, best-effort distribution, a missing-group skip, nor an
old successful build is sufficient. Unknown/pending status is an unconfirmed
release. Waiting for processing is a bounded status check, not re-upload/retry.
The template's result step compares identities and required terminal states;
it does not implement Apple queries or prove availability from caller booleans.

## Collectible errors and acceptance

Let a failed command exit nonzero and keep its useful, sanitized native Actions
error/log. Do not catch it as success, continue-on-error, or overwrite the exit
status while writing a summary. Preserve repository/run/attempt/candidate/job/
step association through normal Actions records, including the precise version
or build and safe underlying cause in the adapter's output. Do not print secrets,
signing data, private configuration, arbitrary environment dumps or raw responses
that may contain them. Fixed template admission errors never echo input values.

Before activation, demonstrate that the intended collector can legally read
the relevant failed-run record and its useful cause within the agreed retention
window. Reuse native run/job/log APIs and, where needed, bounded sanitized
Actions artifacts; do not upload the workspace indiscriminately. A current
operator's successful GET does not establish a future collector's permission.
Use existing failures or safe fixtures, not deliberately failing real releases.
No new error schema/store, automatic retry, repair dispatch, notification,
rollback/resend, AIDash collector or UI is supplied by this source slice.

Local template tests execute the actual shell snippets with synthetic inputs,
Git histories and a deliberately removed-check negative control. A small queue
model applies the documented single/max semantics to actual template settings:
running A, pending C, rejected B and an earlier-admitted B that queues late.
Its single-slot control loses C; the configured max queue retains C, whose real
guard passes, while the stale B's postqueue guard rejects it. This is a model of
platform scheduling, not a hosted Actions execution. Tests parse and lint
generated workflows, but do not emulate Actions event evaluation, trusted
check retrieval, content classifiers, Apple state or distribution availability.
Those require each adapter's integration tests and authorized real-run evidence.
Error recording, green snippet tests and uploaded bytes are not release success.
