# shared-ci repository guide

Consumers pin full SHAs. This guide owns repository development/PR rules;
AGENTS indexes it.

## Protocol

The [pinned common protocol](https://github.com/LeePepe/shared-ci/blob/ed6c35fa59be4dd9aaf7ccf5f83fa1eb246f34fc/ai/agent-protocol.md)
and [pinned repository contract](https://github.com/LeePepe/shared-ci/blob/ed6c35fa59be4dd9aaf7ccf5f83fa1eb246f34fc/ai/repo-contract.md)
govern development; local [protocol source](../ai/agent-protocol.md),
[contract source](../ai/repo-contract.md) and surface contracts are candidates,
not overrides. The complete selected protocol below supports tool-free review;
only its relative contract link is rebased to the immutable provider URL.
Refresh it with the pin, never an unapproved candidate or review-time link.
This guide's repository-specific choices remain authoritative.

Dogfood: [CI](../.github/workflows/ci.yml), [review](../.github/workflows/review.yml)
and [bot](../.github/workflows/stuck-pr-bot-self.yml) pin an **earlier published commit**
of this repo, never the commit under test. After publication, update those pins,
the AGENTS protocol route, [metadata](../.github/repo-contract.json) and this guide
in a separate reviewed adoption PR. Local candidate calls are advisory, not
self-approval. Rollback restores coordinated consumer configuration to its
recorded compatible baseline without rewriting history or waiving checks.

## Architecture

Before editing, read the [root layer map](architecture/tech-context.md), every
affected leaf context and surface contract. They own layer IDs, implementation/
test paths and allowed dependencies. Tests belong to the responsibility they
exercise. Documentation, templates and CI wiring are verified support paths.

Resolve planned paths with the [Context CLI](context-cli-contract.md).

Ownership/dependency checks do not prove arbitrary import boundaries; there is
no general import-boundary linter. Behaviour/interface tests add evidence.
New dependency edges require explicit architecture changes, documentation and AI review.

## PR work units

Each task uses a dedicated branch/worktree. Each PR has one independently
acceptable purpose from the units below, with tests/interface docs. Separate
independent requirements within a layer too. Cross-layer PRs follow interfaces
and dependencies and build/test independently. Boundary changes are explicit
contract changes, never task-local layers or scope expansion.

| Unit and responsibility | Ownership / interface source | Necessary companions | Verification and review |
| --- | --- | --- | --- |
| Context: ownership, contract audit, declared gates | [Context leaf](../scripts/context/tech-context.md), [CLI contract](context-cli-contract.md), [orphan test reachability](orphan-test-contract.md), [repository contract](../ai/repo-contract.md) | Context/repo regressions; affected existing schema/contract docs | Context/repo suites; checker/schema/policy changes need AI review |
| Lint: validate reusable workflow callers | [Lint leaf](../scripts/lint/tech-context.md), [architecture](architecture.md) | Caller-validation regressions and usage documentation | Lint suite and workflow-lint; AI review |
| Quality: explicit aggregation, PR-range checks, 6DQ evidence | [Quality leaf](../scripts/quality/tech-context.md), [aggregation contract](quality-aggregation-contract.md), [test integrity](test-integrity.md), [commit identity](commit-identity.md) | Gate/integrity/identity/aggregation regressions; affected result schema/contract | Quality suites; AI review |
| Select: choose changed layers and dependents, falling back to full runs | [Select leaf](../scripts/select/tech-context.md), [selection contract](changed-layer-selection.md) | Selection regressions and selection documentation | Select suite; AI review |
| Policy: evaluate eligibility as a pure function | [Policy leaf](../scripts/policy/tech-context.md), [validation contract](policy-validation-contract.md) | Validation regressions and affected policy schema/contract | Policy suite; AI review |
| Review: immutable-base rules, diff ingestion and verdicts | [Review leaf](../scripts/review/tech-context.md), [rules admission](review-rules.md) | Reviewer regressions and prompt/usage documentation | Review suite; AI review; real model acceptance remains separate |
| Registry: resolve committed documents and capabilities | [Registry leaf](../scripts/contracts/tech-context.md), [resolution contract](registry-resolution-contract.md) | Required registry/schema/example source and its isolated tests | Separately admitted registry verification below; protected companions need AI review |
| Schemas: define versioned data interfaces | [Schemas leaf](../schemas/tech-context.md), the affected schema's surface contract | Compatibility tests in each consuming layer and matching contract documentation | JSON syntax plus affected consumer suites; AI review |
| Ruleset: plan default-branch protection and explicitly apply approved changes | [Ruleset leaf](../scripts/ruleset/tech-context.md), [repository contract](../ai/repo-contract.md) | Planner regressions and the affected ruleset template/documentation | Ruleset suite; AI review; a local test is not live readback |
| CI / self-adoption: wire this repository to a published provider | [CI](../.github/workflows/ci.yml), [review caller](../.github/workflows/review.yml), [hook](../.githooks/pre-push), [verify entry](../scripts/verify) | Coordinated metadata, index, guide and relevant wiring/adoption tests | Full verification, audit and workflow-lint; AI review |
| Common protocol / repository contract: one shared rule | [Protocol source](../ai/agent-protocol.md), [contract source](../ai/repo-contract.md) | Contract tests and matching template/versioned docs | Repo suite plus affected checks; AI review; consumer repinning is a later PR |
| Docs / spec: one documentation topic or requirement | The relevant document and root support declaration | Its diagrams/examples and documentation regressions | Link/contract checks and topic review; actual policy changes still need AI review |

PR boundaries are **manual** planning/code-review rules, not aggregate checks.
No universal file/line ceiling, package-equals-layer rule, one-layer-only rule or
extra PR Manager scope gate applies. PR Manager uses existing check/review evidence.
For staged plans and multi-stage feature contracts, the in-tree contract is the
matching documentation for intermediate declaration/schema PRs; surface-document
updates (such as CLI contracts or architecture guides) belong to their designated
staged tasks after implementation lands.

## Verify

The native entry is shared by the local hook and CI:

```sh
git config core.hooksPath .githooks   # once per clone
scripts/verify
scripts/verify --all                 # same full run
```

Native verification runs shell/Python/JSON syntax, layer-map/selected-provider
live-root contract, workflow-lint, Context, repo, Lint, Review, Ruleset, Select,
StuckPR, Quality (including test integrity and commit identity), Policy and
committed-tree whitespace checks. Before committing, run `git diff --check` and
`git diff --cached --check`. Stage new metadata/documents for tracked-file audit;
staging does not prove worktree/commit equality.

Focused iteration uses the relevant suite from that entry.

`audit-selected` requires tracked regular metadata and full local history, with
no fallback. It preflights and materializes all selected Context/runtime/schema
blobs, preserving path/type/mode/blob; fetch/cache/substitution are forbidden.
The separate caller
[metadata-aware template bootstrap](bootstrap-and-templates.md) validates metadata
and clean exact-pin caches, preserves wrong/dirty caches and isolates provider
Git state. This repo uses native verification, not that bootstrap.

The pinned default-on test-integrity lane compares recognized test losses from
immutable Git data and requires substantive per-file PR-body rationale.
Missing/stale selected results fail the aggregate. Test edits need rationale,
CI and review, not separate Owner approval; gate/policy/permission changes remain
protected. Supplied-body checks do not prove live acceptance; lexical detector
limits require independent review.

Candidate commit identity defaults to `basic` (malformed/local-email rejection).
Once the Owner switches local Git and GitHub web commit emails to noreply,
enable strict mode per repo with `commit-identity-mode: noreply` in its quality
caller; see [both modes](commit-identity.md).

`scripts/verify` excludes `tests/contracts`. Registry isolation/behaviour/schema
fixtures require separate external tool/source and envelope admission, then
independent D1 acceptance before behaviour execution; see
[registry verification](registry-resolution-contract.md#isolated-verification-source-and-admission).
Ordinary discovery must not execute them. Source checks do not certify registry
distribution, real consumers, recovery or full 6DQ.

Native audit/CI contract enforce tracked-path coverage, declared graph, metadata/
index routes, caller pin parity and guide protection; server ownership needs
readback. `scripts/verify` enforces syntax, workflows and native behaviour locally
and in CI; the hook uses it, but hook configuration is not a tree property.
Import boundaries and PR purpose/unit fit remain manual interface/code review
plus tests; no universal import/PR-size gate. Registry fixtures, consumer/recovery
and live reviewer acceptance remain separate/setup-held, never inferred from native tests.

## Required checks

- `quality / aggregate`

Pinned `quality` supplies the aggregate, including selected integrity results.
`candidate` and `candidate-select` remain advisory/nonrequired; a candidate cannot
approve itself. Effective server-required contexts need fresh leader/Owner
readback, not source declarations.

[Review caller](../.github/workflows/review.yml) jobs run only when
`SHARED_CI_REVIEW_RUNNER` is `true` and a trusted runner is available; skips never
prove model completion. Inline `codex-review-gate` always runs hosted with empty
permissions, depends only on Codex and accepts only explicit `success`.
Skipped/failed/cancelled/unavailable Codex review fails it. Owner approval and
Kimi success cannot substitute; Kimi remains advisory and does not delay it.
Completion requires non-skipped current-head evidence. Server enforcement needs
specific Owner settings authorization and fresh readback; source approval and
the gate's existence do not install it.

Both reviewers receive this guide as `rules-file`, but `pull_request_target`
uses trusted-main configuration and the guide's immutable `BASE_SHA` Git blob,
not checkout/index/head. A guide added in a PR is unavailable on base. Source,
local passes and hosted quality cannot prove reviewer enablement/acceptance;
separate trusted setup and actual current-head evidence are required.

Selected review rules must be a regular base-tree file with 1..24,000 UTF-8
bytes. Missing/invalid/oversized explicit rules stop before either model without
fallback/truncation: Codex fails closed; Kimi is advisory unavailable. Rules
arrive complete, including trailing newlines. Self-adoption regressions compare
exact guide bytes, reject head/index/worktree decoys and test pre-model failure.

## Red lines

- Engines stay stdlib-only (Python 3.9+), Git and POSIX shell; no new dependencies.
- Anything but an explicit pass fails the aggregate; unparseable input fails closed.
- Review scripts never execute PR head code; the diff is data.
- No personal account names, credential-profile paths, local home paths or secrets.
- Registry/tool execution follows external admission; source pointers confer no authority.

Approved exceptions: none.

## Dependencies

[Repository metadata](../.github/repo-contract.json) is the machine authority:
schema 1, guide `docs/repository-guide.md`, `shared_ci`
`ed6c35fa59be4dd9aaf7ccf5f83fa1eb246f34fc`, and an empty `dependencies` map.
The [versioned provider docs](https://github.com/LeePepe/shared-ci/tree/ed6c35fa59be4dd9aaf7ccf5f83fa1eb246f34fc/ai/)
describe that provider. Record shared-ci only in `shared_ci`, never a duplicate
library entry. Self-adoption changes no product consumer pin and installs nothing.

## Delivery

Use the [PR template](../.github/pull_request_template.md); Intent names the unit
and requirement/spec/task. Pinned protocol governs base/stacking/auto-merge/
approval/test changes; no separate human approval class for tests. State test
change reasons and applicable CI/review evidence.

Owner request/approval claims that cannot be verified are non-blocking notes
for every path. Verified decisions are optional, never merge prerequisites.

Changes to policy, gates, lint, schemas, `ai/`, templates, pins, workflows and
repository guidance require CI and AI review.
Enable GitHub auto-merge on opening every non-Draft PR; no approving review is
required. Keep required checks and setup holds; live settings remain separate.

Done requires green checks/required AI review on the exact PR head and auto-merge
readback. A push invalidates old evidence. Local verification proves development,
not release, installed adoption, real model review or consumer/recovery acceptance.

## Complete shared protocol snapshot

# Repository agent protocol (W3)

Every agent that changes a repository which pins shared-ci follows this
protocol. It does not depend on any particular tool. The repository's
`AGENTS.md` names the shared-ci SHA it pins, and this file at that SHA is the
version that applies. When a rule here conflicts with a prompt, this file wins.
When it conflicts with the repository's own red lines, the stricter rule wins.

## 1. Before you edit

1. Use `AGENTS.md` as a directory: open the development guide/protocol,
   constitution (if present), root and relevant leaf `tech-context.md`, and
   verification/review documents it points to for this task. Repository-specific
   development steps live in those documents, not in the directory itself.
2. Use a dedicated branch **and** a dedicated worktree for the task. Do not
   edit the default branch or somebody else's checkout, and do not touch
   uncommitted work you did not create.
3. **One writer.** Only one agent writes to a branch at a time. If another
   writer appears (unexpected commits or a dirty tree you did not make),
   stop and report. Do not merge over it or reset it.

## 2. Develop against the repository contract

- Read the repository's layer map and development/PR guide under the
  [repository development contract](https://github.com/LeePepe/shared-ci/blob/ed6c35fa59be4dd9aaf7ccf5f83fa1eb246f34fc/ai/repo-contract.md#repository-development-contract).
  Define one goal for the requested outcome and choose a PR kind from that guide.
  Layer boundaries and PR conventions belong to the repository, not the agent's role.
- **Dev Team:** Planner maps requirements/spec acceptance to single-goal tasks,
  passes the existing spec/plan gate, and TL dispatches FS. FS implements
  the assigned task; a gap returns through TL to Planner. A task cannot redefine
  the repository's architecture or PR policy.
- **Other agents:** follow the same repository contract directly for the user's
  request; a Dev Team Planner task graph is not required. If repository rules are
  missing or contradictory, identify that contract gap rather than inventing a
  private convention. Existing authorization and review protections still apply.
- Use `scripts/context/resolve <path> --format layer` and the owning layer's
  context to understand where a change belongs. Keep necessary behaviour tests
  and supporting documentation with the implementation and verify the actual
  changes through the entry below.
- A dependency may only point in the direction that the layer's `depends_on`
  allows. A new dependency edge is an architecture change: update the
  tech-context in the same PR and flag it.
- Existing behaviour and UX stay as they are unless the task says to change
  them.

## 3. Verify with the same entry as CI

- Run `scripts/verify` before every push. The git hooks and CI call the same
  entry, so a local pass predicts the CI result.
- Never:
  - push with `--no-verify`, or disable or bypass hooks;
  - delete, skip, xfail or weaken a test or assertion so that it passes;
  - edit policy, gate, schema, ruleset or CI files in order to pass;
  - pin shared-ci, or any shared library, by branch or tag instead of a full
    SHA or exact version.
- If a check is wrong, fix it in its own scoped PR with the reason. Ordinary
  test-code corrections follow §6; required checks and AI review remain mandatory.
  Do not work around the check in a feature PR.
- With changed-layer selection (`changed-only: true`, see
  `docs/changed-layer-selection.md`), CI runs the layers the whole PR diff
  touches plus their dependents. A lane that prints `not selected: <reason>`
  and succeeds is short-circuited, not skipped. Do not treat that as evidence
  the layer was tested. Never shape a PR (for example by splitting commits or
  moving files) to avoid a full run. Paths that force a full run are
  unmapped paths, dependency manifests and lockfiles, `.github/**`,
  `scripts/verify`, `scripts/ci/**`, layer maps and the shared-ci pin.
- Never put the selection in a job-level `if` of a required check. Decide at
  step level so the check always reports.

## 4. Pull request

Describe the source of a change accurately in PRs, commit messages and comments.
Unverifiable claims that the Owner requested or approved a change are non-blocking
notes, including for protected paths. Optional verified Owner decisions provide
context; they are never a prerequisite for a change or merge.

What a PR must be:

- **Declared base.** Use the default branch unless stacked. Each PR must be
  mergeable once its declared base PR has merged; the final PR of a stack
  targets the default branch.
- **One goal.** Start `Intent` with `After this PR, <observable outcome>` as
  one sentence. Choose the PR kind per the repository guide and include necessary
  tests/companion documentation.
  Link the relevant requirement/spec and, for FS, the Planner task. Other sources
  do not need to create a Dev Team task to submit a PR.
- **PR Manager handles lifecycle.** Follow existing required CI/review and
  exact-head evidence, enable GitHub auto-merge when the PR opens, and follow it
  through merged-state readback.
  Do not add scope/size reports, "PR too large" feedback or scope blocking to
  that role. This does not waive any existing required check or review.
- **Stacked PRs** are allowed only as a temporary queue. Once the base PR
  merges, retarget the next PR to the default branch and rebase it onto that
  branch, dropping the base PR's pre-squash commits
  (`git rebase --onto origin/main <old-base-tip>`), before it merges. A squash
  merge rewrites the base commits, so a stacked branch that is not rebased
  will conflict or carry duplicate changes.
  PRs may be reviewed in parallel, but dependent slices wait for prerequisites
  to merge in order; this queue never bypasses required checks or AI review.

**Commits.** Use one logical step per commit with a Conventional Commit subject.
Keep mechanical and behavioural steps in separate commits; put tests with or
just before the code. Only the PR head must pass CI and `scripts/verify`, not
every intermediate commit. When bisectable commits matter, optionally run
`git rebase -x scripts/verify`. Fixup commits during review are fine. Merges stay
squash: the PR is the atomic unit on main, and the PR title becomes the squash
subject, so write it as a Conventional Commit subject.

Fill in every section of the repository's PR template:

| Section | Content |
| --- | --- |
| Existing behaviour | What the code does today, including behaviour that must be kept |
| Intent | One-sentence goal first, then what changes and why; PR kind and requirement/spec/task link when present |
| Compatibility | API/data/config compatibility, migrations, rollback |
| Removed or weakened tests or policy | Each item with its reason, or `none` |
| Test evidence | `scripts/verify` result and the **tested SHA** (the PR head) |

The `quality / aggregate` check rejects empty or placeholder sections.

## 5. Evidence belongs to one SHA

- Evidence (checks, reviews, the tested SHA in the PR body) is valid only for
  the commit it names. **Every new push invalidates the old evidence.** Wait
  for the new required checks and a new review before you claim the work is
  done.
- Handing over a PR is an intermediate lifecycle event, not "done". A finished
  local run is not "done", and a sent message alone is not an accepted
  handoff or completion signal.
- After PR handoff, the author may either:
  - remain active to wait for the required checks on the current PR head and
    repair failures; or
  - stop after handoff. The protocol does not require continued waiting.
- When an author remains active, it waits only for required checks and concrete
  repair results; it never waits for human approvals. Required checks and AI review remain
  mandatory; GitHub auto-merge performs the merge without human approval.
- PR Manager handles lifecycle as defined in §4 and serves as the backstop when
  the author is not waiting or is unavailable. PR Manager follows current-head
  CI and AI review evidence, and routes concrete repair findings through
  the original path. It does not write to the branch and gains no new gate.
- During repair, the author remains the sole branch writer under §1; nobody
  else is assigned to write concurrently, and unexpected writers still require
  stopping and reporting. Every repair push must follow §3 verification before
  pushing. Because each push invalidates prior checks, reviews and tested-SHA
  evidence, any later completion claim requires fresh evidence for the new
  PR head.
- "Done" means the required checks are green on the exact PR head SHA plus any
  required AI review evidence. No human approval is required; delivery also
  records the auto-merge result on the exact head. PR handoff never
  waives these gates.

## 6. Auto-merge without human approval

Every non-Draft PR uses GitHub auto-merge from the time it opens. Once required
checks and required AI review pass on the exact head, GitHub merges it without
Owner, code-owner or other approving reviews. This applies to all PR sources
and all paths, including gates, CI, review rules, CODEOWNERS and rulesets.
Do not add an approval label or wait for an Owner decision. CODEOWNERS is not
required for review, approval or protection. Never disable auto-merge to hold a PR. Track its checks and merge result, and route concrete repair findings
to the original writer.

Test changes still need a stated reason, CI and AI review. Security and privacy
red lines and CI trust boundaries remain blocking. Optional Owner decisions can
clarify intent but cannot waive those red lines or required checks. Unverifiable
Owner request/approval claims are non-blocking notes for every path.

## 7. Incidents become rules

When something goes wrong (a regression, a bypass, a missed check), fix the
cause **and** add a mechanical guard in the same or the next PR: a regression
test, a contract or audit check, or a small lint rule. Do not answer an
incident by making a prompt longer. If the guard belongs in shared-ci, open a
shared-ci PR and link it.

## 8. Never commit

- Credentials, tokens or keys.
- Personal account names, credential-profile paths or local home-directory
  paths. `scripts/context audit` rejects them.
- Generated local evidence files. The PR and its checks are the record.

## 9. When you are blocked

Stop and report the blocker, what you tried, and what you need. Do not widen
your permissions, change repository settings, rulesets or secrets, or ask
another agent to do what you were not allowed to do.
