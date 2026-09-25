# shared-ci

For versioned adoption, compatibility and rollback, start at the
[AI documentation bundle](ai/USAGE.md). Existing entry paths below remain valid.

The shared CI for LeePepe repositories. Every consumer pins it by a **full
40-character commit SHA**. Branch and tag refs are rejected. At any pinned SHA,
the docs, schemas, templates and engines all come from that same commit.

## What it provides

| Surface | Path | Purpose |
| --- | --- | --- |
| Agent protocol (W3) | [`ai/agent-protocol.md`](ai/agent-protocol.md) | How any agent works inside a consumer repository: its own worktree, one writer, owned paths only, same `scripts/verify` as CI, PR evidence tied to a SHA, incidents become rules |
| Repository contract v1 | [`ai/repo-contract.md`](ai/repo-contract.md), [`schemas/repo-contract-v1.json`](schemas/repo-contract-v1.json) | The 8 minimum items per repository, and which ones are checked by machine |
| Layer-map resolver + audit | [`scripts/context/`](scripts/context/) ([contract](docs/context-cli-contract.md)) | `audit`, `resolve`, `layers`, `field`, `contexts`, `run`. Reads the repo-kit `tech-context.md` layer map, and still reads legacy `CONTEXT.md` trees. For repo-kit callers, `audit` also checks the repository contract |
| Quality gate | [`.github/workflows/quality.yml`](.github/workflows/quality.yml) | Reusable. Runs per-repo command lanes (verify/lint/build/test) plus the contract audit and workflow-lint, then a **fail-closed `aggregate`** job: selected lanes must be `success` on the PR head SHA, unselected lanes must be `success`/`skipped`, and the PR body must fill every template section |
| Changed-layer selection (v0.2.0) | [`scripts/select/`](scripts/select/), [`select.yml`](.github/workflows/select.yml) ([contract](docs/changed-layer-selection.md)) | Opt-in `changed-only: true`. Maps the PR diff (merge-base to head) to layers plus their dependents with the pinned resolver. It falls back to a full run for unmapped paths, manifests and lockfiles, `.github/**`, `scripts/verify`, `scripts/ci/**`, layer maps, pin changes, non-PR events and any error. Unselected lanes short-circuit with `not selected: <reason>` and succeed, so required checks always report. `select.yml` gives the same outputs to callers' own matrix lanes |
| AI review | [`codex-review.yml`](.github/workflows/codex-review.yml), [`kimi-review.yml`](.github/workflows/kimi-review.yml) | Reusable, run by `pull_request_target` on a self-hosted runner that has a local CLI. Fork PRs never reach that runner, and PR code is never checked out or executed (the diff is data). codex is a gate: it comments and fails on critical/high findings. kimi is advisory and never fails. Both prompts include layer ownership and the allowed dependency direction from the resolver |
| workflow-lint | [`.github/workflows/workflow-lint.yml`](.github/workflows/workflow-lint.yml), [`scripts/lint/workflows.py`](scripts/lint/workflows.py) | Rejects shared-ci refs that are not full SHAs, self-hosted jobs without the fork guard, and PR-head checkout under `pull_request_target` |
| Ruleset as code | [`templates/ruleset.json`](templates/ruleset.json), [`scripts/ruleset/`](scripts/ruleset/) | The default-branch ruleset is part of the contract. `plan.py` prints old → new against the live rules and keeps existing required checks unless they are explicitly mapped. `apply.sh` applies only with `--apply`, and only after Owner approval, then reads the result back |
| Templates | [`templates/`](templates/) | `AGENTS.md`, `CLAUDE.md`, root and leaf `tech-context.md`, `pull_request_template.md`, `CODEOWNERS`, `ci.yml`, `review.yml`, `ruleset.json`, `scripts/verify`, `githooks/pre-push` |
| Policy, 6DQ, registry | [`scripts/policy/`](scripts/policy/), [`scripts/quality/aggregate.py`](scripts/quality/aggregate.py), [`scripts/contracts/`](scripts/contracts/) | Existing pure functions and the committed-registry resolver (see [architecture](docs/architecture.md)) |

## How a consumer pins it

1. Pick one shared-ci commit SHA (from the latest release, or `main`).
2. Use that SHA everywhere:
   - `.github/workflows/ci.yml`:
     `uses: LeePepe/shared-ci/.github/workflows/quality.yml@<SHA>` (job id
     `quality`, so the required check is `quality / aggregate`);
   - `.github/workflows/review.yml`: `codex-review.yml@<SHA>` and
     `kimi-review.yml@<SHA>`;
   - `AGENTS.md`: `LeePepe/shared-ci@<SHA>/ai/agent-protocol.md`, plus the
     `Dependencies` line.
3. Run the contract audit from the consumer root:
   `python3 <shared-ci checkout>/scripts/context/_context.py audit`.
4. Ruleset: run `scripts/ruleset/apply.sh OWNER/REPO [--map OLD=NEW]` to see the
   old → new diff. The new ruleset requires `quality / aggregate` and
   `codex-review-target / codex-review`, and kimi stays optional. After the
   Owner approves, run it again with `--apply`. The script reads the ruleset
   back to confirm.

The reusable workflows check out their own engines at `job.workflow_sha`, so
the code that runs is always the code at the pinned SHA. To upgrade, change
every pin and the AGENTS pointer in one PR. The audit rejects pins that are
mixed or do not match.

## This repository

shared-ci runs on its own gate. [`.github/workflows/ci.yml`](.github/workflows/ci.yml)
calls `quality.yml` pinned to an **earlier** commit of this repository, never
the commit under test, and its `verify` lane runs [`scripts/verify`](scripts/verify).
That script runs every self-test (aggregate, workflow-lint, contract, resolver
and review fixtures), the self-applied audit and the lint. Local entry:
`scripts/verify`, which the pre-push hook also calls.

| Task | Entry |
| --- | --- |
| Understand modules and boundaries | [Architecture](docs/architecture.md) |
| Locate a contract by task | [AI usage](docs/ai-usage.md) |
| Connect or migrate a caller | [Integration and migration](docs/integration-and-migration.md) |
| Run only changed layers in CI | [Changed-layer selection](docs/changed-layer-selection.md) |
| Recover source, configuration or evidence | [Disaster recovery](docs/disaster-recovery.md) |

Requirements: Python 3.9+ (stdlib only), Git and a POSIX shell.
