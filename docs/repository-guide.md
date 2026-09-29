# shared-ci repository guide

shared-ci provides the repository agent protocol, repository contract and its
checker, layer-map resolver, fail-closed quality gate, AI review workflows and
workflow-lint. Other repositories consume it by full commit SHA. This guide owns
shared-ci's repository-specific development and PR rules; AGENTS is its index.

## Protocol

The [pinned common protocol](https://github.com/LeePepe/shared-ci/blob/6e354f476bc53d68f0f09fc231d5cd938466af9c/ai/agent-protocol.md)
and [pinned repository contract](https://github.com/LeePepe/shared-ci/blob/6e354f476bc53d68f0f09fc231d5cd938466af9c/ai/repo-contract.md)
govern development. The local [protocol source](../ai/agent-protocol.md),
[contract source](../ai/repo-contract.md) and surface contracts linked below are
the candidate being developed, not an override of the pinned common rules.
The complete selected protocol is included below for tool-free review; only its
relative contract link is rebased to the immutable provider URL. Refresh that
snapshot with the pin, not from an unapproved candidate or a linked document at
review time. Repository-specific choices remain authoritative in this guide.

Dogfood rule: the external calls in [CI](../.github/workflows/ci.yml) and
[review](../.github/workflows/review.yml) pin an **earlier published commit** of
this repository, never the commit under test. Update those pins, the AGENTS
protocol route, [metadata](../.github/repo-contract.json) and this guide together
in a separate reviewed adoption PR after the selected provider is published.
The local candidate workflow calls are advisory tests, not approval of their
own gate. Rollback restores the coordinated consumer configuration to its
recorded compatible baseline; it does not rewrite provider history or waive
required checks.

## Architecture

Read the [root layer map](architecture/tech-context.md), the leaf context of
every affected layer, and its surface contract before editing. The root and
leaves own layer IDs, implementation/test paths and allowed dependencies; this
guide references them rather than duplicating their glob lists. Tests belong
to the responsibility they exercise. Support paths cover documentation,
templates and CI wiring and are still verified.

Use the [Context CLI](context-cli-contract.md) to resolve planned paths:

```sh
scripts/context/resolve scripts/context/_contract.py --format layer
scripts/context/contexts tests/repo/test_self_adoption.py
```

Declared ownership/dependency checks do not prove arbitrary language import
boundaries. Behaviour and interface tests below provide additional evidence;
there is no general import-boundary linter in this repository. New dependency
edges require an explicit architecture change under existing Owner review.

## PR work units

One task uses one dedicated branch/worktree and one independently acceptable
PR purpose within a unit below. Necessary tests and interface documentation
travel with the change. Independent requirements remain separate even when
they share a layer. Cross-layer features use interface-based, dependency-ordered
PRs that each build and test independently; changing a boundary is an explicit
contract change, not a new task-local layer or permission to expand scope.

| Unit and responsibility | Ownership / interface source | Necessary companions | Verification and review |
| --- | --- | --- | --- |
| Context: resolve ownership, audit contracts, run declared gates | [Context leaf](../scripts/context/tech-context.md), [CLI contract](context-cli-contract.md), [repository contract](../ai/repo-contract.md) | Required context/repo regressions, affected existing schema and contract documentation | Context and repo suites; checker/schema/policy changes need Owner review |
| Lint: validate reusable workflow callers | [Lint leaf](../scripts/lint/tech-context.md), [architecture](architecture.md) | Caller-validation regressions and usage documentation | Lint suite and workflow-lint; Owner review |
| Quality: aggregate explicit gate results, PR-range checks and 6DQ evidence | [Quality leaf](../scripts/quality/tech-context.md), [aggregation contract](quality-aggregation-contract.md), [test integrity](test-integrity.md), [commit identity](commit-identity.md) | Gate/integrity/identity/aggregation regressions and affected result schema/contract | Quality suites; Owner review |
| Select: choose changed layers and dependents, falling back to full runs | [Select leaf](../scripts/select/tech-context.md), [selection contract](changed-layer-selection.md) | Selection regressions and selection documentation | Select suite; Owner review |
| Policy: evaluate eligibility as a pure function | [Policy leaf](../scripts/policy/tech-context.md), [validation contract](policy-validation-contract.md) | Validation regressions and affected policy schema/contract | Policy suite; Owner review |
| Review: immutable-base rules, diff ingestion and verdicts | [Review leaf](../scripts/review/tech-context.md), [rules admission](review-rules.md) | Reviewer regressions and prompt/usage documentation | Review suite; Owner review; real model acceptance remains separate |
| Registry: resolve committed documents and capabilities | [Registry leaf](../scripts/contracts/tech-context.md), [resolution contract](registry-resolution-contract.md) | Required registry/schema/example source and its isolated tests | Separately admitted registry verification below; protected companions need Owner review |
| Schemas: define versioned data interfaces | [Schemas leaf](../schemas/tech-context.md), the affected schema's surface contract | Compatibility tests in each consuming layer and matching contract documentation | JSON syntax plus affected consumer suites; Owner review |
| Ruleset: plan default-branch protection and explicitly apply approved changes | [Ruleset leaf](../scripts/ruleset/tech-context.md), [repository contract](../ai/repo-contract.md) | Planner regressions and the affected ruleset template/documentation | Ruleset suite; Owner review; a local test is not live readback |
| CI / self-adoption: wire this repository to a published provider | [CI](../.github/workflows/ci.yml), [review caller](../.github/workflows/review.yml), [hook](../.githooks/pre-push), [verify entry](../scripts/verify) | Coordinated metadata, index, guide, CODEOWNERS and relevant wiring/adoption tests | Full verification, audit and workflow-lint; Owner review |
| Common protocol / repository contract: change one shared development rule | [Protocol source](../ai/agent-protocol.md), [contract source](../ai/repo-contract.md) | Necessary contract tests and matching template/versioned documentation | Repo suite plus affected checks; Owner review; consumer repinning is a later PR |
| Docs / spec: one documentation topic or requirement | The relevant document and root support declaration | Its diagrams/examples and documentation regressions | Link/contract checks and topic review; actual policy changes still need Owner review |

These PR boundaries are **manual** planning/code-review rules. The aggregate
does not infer purpose or validate this table. There is no universal file/line
ceiling, package-equals-layer rule, one-layer-only requirement or additional PR
Manager scope gate. PR Manager consumes existing check/review evidence and
manages lifecycle.

## Verify

The native entry is shared by the local hook and CI:

```sh
git config core.hooksPath .githooks   # once per clone
scripts/verify
scripts/verify --all                 # same full run
```

This repository runs its full suites; it does not use the template bootstrap
or narrow local verification by layer. The entry checks shell/Python/JSON syntax,
the actual layer map and repository contract, workflow-lint, Context, repo,
Lint, Review, Ruleset, Select, Quality (including test integrity and commit identity) and Policy tests, then committed-tree
whitespace. For edits not yet committed, also run `git diff --check` and
`git diff --cached --check`. New metadata/documents must be staged for the
tracked-file audit. Staging is not proof that worktree content equals a commit.

For a focused iteration, use the corresponding suite from the entry, for example:

```sh
python3 -I -B -m unittest discover -s tests/repo -p test_self_adoption.py -v
python3 -I -B scripts/context/_context.py audit
python3 -I -B scripts/lint/workflows.py --root .
```

The selected-provider tests require the recorded historical Git objects locally.
CI's caller checkout fetches full history; the tests do not fetch missing objects
or substitute candidate provider code. This is not a shallow/partial-checkout
compatibility claim. The [metadata-aware template bootstrap](bootstrap-and-templates.md)
is a separate caller surface: it validates metadata and clean exact-pin caches,
preserves existing wrong/dirty caches and isolates provider Git state. This
repository retains its native full verify entry, not that template bootstrap.

The pinned quality workflow's default-on test-integrity lane compares recognized
test losses from immutable Git data and requires substantive per-file rationale
in the PR body. Missing or stale selected results fail the aggregate. This is
distinct from ordinary test approval: test edits need rationale, CI and review,
not a separate Owner test class. Actual gate/policy/permission changes remain
protected. Local supplied-body checks do not prove live PR-body acceptance;
the lexical detector's limits require independent review.

`tests/contracts` is **not** run by `scripts/verify`. Registry isolation,
behaviour and schema-engine fixtures require separate external tool/source and
envelope admission, then independent D1 acceptance before behaviour execution,
as specified in [registry verification](registry-resolution-contract.md#isolated-verification-source-and-admission).
Do not turn ordinary unittest discovery into registry execution. Source checks
do not certify registry distribution, real consumers, recovery or full 6DQ.

| Rule | Status and evidence boundary |
| --- | --- |
| Tracked-path coverage, declared graph, metadata/index routes, caller pin parity and guide protection | **Enforced** by native audit and the CI contract lane; effective server ownership still needs readback |
| Syntax, workflow validity and behaviour in the native suites | **Enforced** by `scripts/verify` locally and in CI; the hook calls this entry, but local hook configuration is not a tree property |
| Actual import boundaries and PR purpose/unit fit | **Manual** interface/code review plus relevant tests; no universal import or PR-size gate |
| Registry fixtures, consumer/recovery and live reviewer acceptance | **Separate / setup-held** evidence, never inferred from the native suite |

## Required checks

- `quality / aggregate`

The pinned `quality` job supplies this aggregate, including selected integrity
results. Local `candidate` and `candidate-select` jobs stay advisory and
nonrequired; a candidate cannot approve itself. Effective server-required
contexts must come from fresh leader/Owner readback, not this source declaration.

[Review caller](../.github/workflows/review.yml) jobs run only when
`SHARED_CI_REVIEW_RUNNER` is `true` and a trusted runner is available. When that
setup is absent, skipped jobs do not establish model completion. The approved
inline `codex-review-gate` always runs on a hosted runner with empty permissions,
depends only on Codex and accepts only an explicit `success` result. Skipped,
failed, cancelled or unavailable Codex review fails that gate. Owner approval
and Kimi success cannot substitute; Kimi stays advisory and does not delay it.
Actual non-skipped current-head evidence is still required to prove completion.
Requiring this check on the server needs specific Owner settings authorization
and fresh readback; source approval and the gate's existence do not install it.

Both reviewers receive this guide as `rules-file`, but `pull_request_target`
uses trusted-main workflow configuration and the guide's immutable `BASE_SHA`
Git blob, not the mutable checkout, index or head. A guide newly added in a PR
is not already available on base. The source PR, a local
pass or a hosted quality run cannot prove reviewer enablement or acceptance;
those require separate trusted setup and actual current-head evidence.

The selected provider admits only a regular base-tree file containing nonempty
UTF-8 text within 24,000 bytes. Missing, invalid or oversized explicit rules
never fall back or truncate: they stop before either model, with Codex failing
closed and Kimi advisory unavailable. Admitted rules arrive complete, including
all trailing newlines. The self-adoption regressions compare exact guide bytes,
ignore head/index/worktree decoys and verify unavailable-before-model negatives.

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
`6e354f476bc53d68f0f09fc231d5cd938466af9c`, and an empty `dependencies` map.
The [versioned provider documentation](https://github.com/LeePepe/shared-ci/tree/6e354f476bc53d68f0f09fc231d5cd938466af9c/ai/)
describes that selected provider. Shared-ci is recorded only in `shared_ci`,
not duplicated as a library entry. This self-adoption changes no product
consumer pin and installs nothing.

## Delivery

Use the [PR template](../.github/pull_request_template.md) and name the repository
unit and relevant requirement/spec/task in Intent. Keep base/default-branch,
stacking, auto-merge, approval and ordinary-test-change policy in the pinned
protocol; this guide introduces no separate human approval class for test edits.
State reasons for test changes and provide applicable CI/review evidence.

Changes to gates, lint, schemas, `ai/`, templates, pins, workflows, this guide
and other [CODEOWNERS](../.github/CODEOWNERS) paths are important PRs requiring
real Owner review. Source ownership declarations do not prove server protection;
preserve the existing approval gates and setup holds.

Done means required checks are green on the exact PR head SHA, with existing
required approvals/review evidence satisfied. A new push invalidates old
evidence. Local source verification is only development evidence, not release,
installed adoption, real model review or consumer/recovery acceptance.

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
  [repository development contract](https://github.com/LeePepe/shared-ci/blob/6e354f476bc53d68f0f09fc231d5cd938466af9c/ai/repo-contract.md#repository-development-contract).
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
  test-code corrections follow §6; policy/gate changes still need Owner review.
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
  approval evidence, route concrete repair findings, and merge when eligible.
  Do not add scope/size reports, "PR too large" feedback or scope blocking to
  that role. This does not waive any existing required check or review.
- **Stacked PRs** are allowed only as a temporary queue. Once the base PR
  merges, retarget the next PR to the default branch and rebase it onto that
  branch, dropping the base PR's pre-squash commits
  (`git rebase --onto origin/main <old-base-tip>`), before it merges. A squash
  merge rewrites the base commits, so a stacked branch that is not rebased
  will conflict or carry duplicate changes.
  PRs may be reviewed in parallel, but dependent slices wait for prerequisites
  to merge in order; this queue never bypasses approvals or CI.

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
| Removed or weakened tests or policy | Each item with its reason; approval where §6 requires it, or `none` |
| Test evidence | `scripts/verify` result and the **tested SHA** (the PR head) |

The `quality / aggregate` check rejects empty or placeholder sections.

## 5. Evidence belongs to one SHA

- Evidence (checks, reviews, the tested SHA in the PR body) is valid only for
  the commit it names. **Every new push invalidates the old evidence.** Wait
  for the new required checks and a new review before you claim the work is
  done.
- "Done" means the required checks are green on the PR head SHA. A finished
  local run is not "done", and a sent message is not an accepted handoff.

## 6. Important PRs need the Owner

Changes under `CODEOWNERS` paths need Owner approval (for example
`.github/**`, policy, schemas, gates, `AGENTS.md`, the constitution,
dependency pins, credentials, privacy and data migrations). Ordinary test-code
edits or deletions require a stated reason, CI and AI review, not separate
Owner approval merely because tests changed. Changes to actual gate/policy
semantics or permissions remain important even when placed in a test or Markdown
file. Existing behaviour changes without an approved spec also need the Owner.
Use trusted policy and effective CODEOWNERS protections, not an author's label,
to route review. Until CODEOWNERS review is enforced, add `owner-review` for
important PRs and wait; do not bypass existing protections.

Enable auto-merge on every PR; CODEOWNERS required review gates important paths; never disable auto-merge to hold a PR.

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
