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

## 2. Development modes

- **Dev Team FS:** execute the ready task produced by Planner and dispatched
  by TL after the spec/plan gate. Use its requirement/spec revision, acceptance,
  layer, paths and exclusions; one implementation task has its own branch/PR.
  If another layer, spec or requirement is needed, return the gap through TL
  to Planner before continuing. Task decomposition is a planning-stage duty,
  not a PR Manager scope/size check.
- **Other agents:** follow the user's request and the development documents
  indexed by `AGENTS.md`. No Planner task graph, formal scope declaration or
  PR-size/scope gate is required by this protocol. Existing authorization,
  architecture, verification and review rules still apply.
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
- **Dev Team task link.** An FS PR identifies the Planner task it implements;
  its boundary was set before implementation under §2. Other sources do not
  need to create a Planner task or a scope declaration to submit a PR.
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
| Intent | What changes and why; task/issue link (Dev Team: the Planner task) |
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
