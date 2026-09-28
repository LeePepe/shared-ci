# Development guide

<!-- Place at docs/development.md or adapt an existing guide. Adapt PR kinds
with this repository's real commands and review pointers. -->

## Architecture

[The layer map](architecture/tech-context.md) owns layer IDs and dependencies.
Each referenced leaf owns its implementation/test paths, responsibility,
interfaces and verification commands. Read those sources for the change at hand.
The pinned shared protocol/contract reached through AGENTS defines the common
development rules; this guide records the repository-specific choices.

## PR kinds

One goal per PR: start `Intent` with `After this PR, <observable outcome>`.
"And" between unrelated outcomes means two PRs. Layers are review signals, not
PR scope; ownership stays in tech-context. Every PR head passes `scripts/verify`.
There is no universal line/file ceiling. Follow-ups become new PRs/tasks.

| Kind | What belongs together | Keep separate from | Verification / review |
| --- | --- | --- | --- |
| Mechanical | Rename/move/format/generated/codemod for one goal | Behavioural changes | Existing behaviour tests; code review |
| Dependency / pin | Manifest/lockfile/shared-ci pin and necessary compatibility evidence | Non-trivial adaptation | Full verification; Owner review |
| Governance | AGENTS, policy, ruleset, CI wiring, CODEOWNERS paths for one rule, with tests/docs | Feature code | Policy checks, workflow lint as applicable, full verification; Owner review |
| Behaviour / feature slice | One observable outcome with required tests and implementation docs | Mechanical changes, dependency/pin bumps, governance, unrelated features | Affected layer/dependent gates; code review |
| Interface-first | Cross-layer: lower-layer interface + tests + a real or test usage first | Upward adoption that can follow separately | Interface/compatibility tests; architecture/code review |
| Docs / spec | One documentation topic or requirement, its diagrams and examples | Unrelated implementation | Documentation checks/review; policy changes retain Owner review |

Test-only additions for existing behaviour may precede the change they protect.
For cross-layer work, introduce the tested lower-layer interface with a usage,
then adopt upward; small single-goal cross-layer PRs are fine. Touching several
layers prompts "still one goal? interface-first order?". Use a flag or an
unused-but-tested path when adoption needs several steps. Stack dependent PRs
under the pinned protocol: review in parallel, merge in order, then retarget and
rebase after each squash merge. Combine or reorder slices that cannot build alone.

## Verification and review sources

Use the repository's executable verify entry from both local hooks and CI:

```sh
git config core.hooksPath .githooks
scripts/verify
scripts/verify --all
```

Point to the repository's verify entry, CI configuration and review policy /
CODEOWNERS. Record the command/evidence and `enforced`, `manual`, `planned` or
`N/A` status for actual checks; do not present this example table as enforcement.
PR authors use these conventions regardless of workflow. PRM follows existing
CI/review outcomes without adding a separate size or scope review.
