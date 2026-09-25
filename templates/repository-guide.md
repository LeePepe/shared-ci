# Repository guide

Read the constitution when present, then the root architecture context and each
affected layer's leaf context. Keep repository-specific facts in those sources.

## Protocol

Read `ai/agent-protocol.md` from the exact provider revision in
`.github/repo-contract.json` (`shared_ci`). The workflow pins must match it.
AGENTS is the document router, not a policy or bootstrap configuration file.

## Verify

```sh
git config core.hooksPath .githooks
scripts/verify
scripts/verify --all
```

The pre-push hook and CI use this entry. Record repository-specific prerequisites
here and layer build/test commands in their leaf contexts.

## Required checks

Record the live required-check names here after ruleset readback. The shared
contract targets `quality / aggregate` and `codex-review-target / codex-review`;
retain caller-required checks and leave Kimi advisory. Configuration is not proof
that enforcement or a review runner is working.

## Red lines

Record repository constraints and approved exceptions here. Test edits/deletions
need an explanation and normal AI review, not an Owner approval merely because
they change tests. Protected CI/gate/policy changes retain their review gates.
Applicable Plan-Review requirements remain in force.

## Dependencies

Use `.github/repo-contract.json` for exact pins and versioned `ai/` links.
Keep integration behavior in each dependency's versioned contract.

## Delivery

Use a dedicated task branch/worktree and the PR template. Bind verification and
review to the current head. Important paths remain CODEOWNERS-gated; enable
auto-merge without disabling required checks or review.
