# Repository guide

<!-- Copy to docs/repository-guide.md. Adapt repository-specific checks and
constraints. Keep this protected file self-contained for the tool-free reviewer;
links alone do not load policy. Its complete text must fit the selected review
provider's rules-file limit (24000 bytes at the documented baseline). -->

## Protocol

The provider is pinned by `.github/repo-contract.json` (`shared_ci`), matching
all workflow pins and the versioned AGENTS protocol route. The full shared
protocol is included below, not fetched by the reviewer. On a pin upgrade,
compare and update that snapshot from the selected provider before review.

## Verify

```sh
git config core.hooksPath .githooks
scripts/verify
scripts/verify --all
```

The hook and CI use the same executable entry. Python 3.9+, Git and Bash are
required. Layer commands and toolchain prerequisites are owned by the leaf
contexts. Use a clean provider checkout at the exact pin; bootstrap never
replaces an existing cache. Read docs/development.md for repository setup.

## Required checks

The shared contract targets `quality / aggregate` and
`codex-review-target / codex-review`; Kimi is advisory. Retain existing caller
checks. Record actual names and enforced/manual/planned/N/A status after live
ruleset and runner readback; template configuration does not prove enforcement.
Missing required protection or unavailable review is a hold, not permission
to merge. Settings changes require exact Owner approval and readback.

## Red lines

Preserve behavior unless the approved requirement says otherwise. Layers are
stable responsibilities/interfaces, not mechanically packages. Respect their
owned tests and allowed dependencies. Support paths need reasons and checks;
executable tools must not disappear under broad script exclusions.

Ordinary test edits/deletions need rationale, CI and ordinary review, not a
separate Owner ledger. Actual policy/gate/permission changes retain Owner review.
Never execute PR head code in a review job. Record repository-specific red lines
and approved exceptions here as complete reviewer-visible text, not only links.

## Dependencies

Metadata records exact versions and versioned AI documentation. Inspect real
manifests/lockfiles for parity; the shared-ci pin has only one metadata authority.
A published source commit is not a release, product adoption or live protection.

## Delivery

The repository's docs/development.md owns PR work units and companion changes.
Keep the following review-relevant extract synchronized when adapting that guide;
the tool-free reviewer receives this file, not linked documents.


| Unit | Path source | Permitted companion changes | Verification / review |
| --- | --- | --- | --- |
| Core | Core leaf `owns` | Required behaviour tests and API documentation | Core gates; repository architecture/code review |
| App | App leaf `owns` | Required behaviour tests and feature documentation | App gates and affected dependents; code review |
| CI | Repository workflow/hook/verify entry points | Tests and docs of that wiring change | Workflow lint and full verification; protected-path review |
| Docs / spec | One documentation topic or requirement/spec | Its diagrams and examples | Documentation checks/review; no unrelated implementation |
| Review / policy | Repository's actual policy and reviewer-configuration paths | Policy regression tests and usage docs | Policy checks and existing protected-path review |

Each PR serves one purpose within a unit. Refer to layer ownership instead of
copying its glob lists here. Specify any additional companion paths precisely;
sharing a unit is not permission to bundle independent requirements. For a
cross-layer feature, document the interface and dependency-ordered PRs first.


PRM follows existing CI/review outcomes, without a separate size/scope gate.
Use the PR template, dedicated task branch/worktree and current-head evidence.
Required checks and Owner approval for protected changes remain mandatory.

## Complete shared protocol snapshot

<!-- Snapshot of the selected baseline protocol; refresh deliberately on upgrade. -->

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
  [repository development contract](https://github.com/LeePepe/shared-ci/blob/<40-char-sha>/ai/repo-contract.md#repository-development-contract).
  Choose its existing PR unit for the requested outcome. Layer boundaries and
  PR conventions belong to the repository, not to the agent's role.
- **Dev Team:** Planner maps requirements/spec acceptance to tasks within those
  units, passes the existing spec/plan gate, and TL dispatches FS. FS implements
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

- **Base is the default branch.** A PR must be mergeable on its own. Do not
  make it depend on another open PR being merged first.
- **Repository-defined unit.** Follow the repository guide's PR conventions:
  one purpose, an existing unit and its necessary tests/companion documentation.
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
  Dependent slices wait for prerequisites to merge in order; this queue never
  bypasses approvals or CI.

Fill in every section of the repository's PR template:

| Section | Content |
| --- | --- |
| Existing behaviour | What the code does today, including behaviour that must be kept |
| Intent | What changes and why; repository PR unit and requirement/spec/task link when present |
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
