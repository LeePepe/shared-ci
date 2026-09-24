# AGENTS.md — shared-ci

shared-ci provides the repository agent protocol, the repository contract and
its checker, the layer-map resolver, the fail-closed quality gate, the AI review
workflows and workflow-lint. Other repositories pin it by full commit SHA.

## Read first

1. `docs/architecture/tech-context.md` — layer table (engines under `scripts/`)
2. The leaf `tech-context.md` of every layer you touch
3. The contract doc for the surface you change (`ai/`, `docs/*-contract.md`)

## Protocol

Follow `LeePepe/shared-ci@9ff304e317a5ff924a4c488515ead5a607d28236/ai/agent-protocol.md`
(https://github.com/LeePepe/shared-ci/blob/9ff304e317a5ff924a4c488515ead5a607d28236/ai/agent-protocol.md).
Dogfood rule: `.github/workflows/ci.yml` pins an **earlier** commit of this
repository, never the commit under test. Bump the pin and this pointer together
in a separate PR, after the pinned commit exists on the remote.

## Verify

```sh
git config core.hooksPath .githooks   # once per clone
scripts/verify                        # what pre-push and CI run
```

## Required checks

- `quality / aggregate`

AI review for this repository runs from `.github/workflows/review.yml`
once it is on `main` and a trusted runner is registered.

## Red lines

- Engines stay stdlib-only (Python 3.9+), Git and POSIX shell.
- Anything but an explicit pass fails the aggregate; unparseable input fails closed.
- Review scripts never execute PR head code.
- No personal account names, credential-profile paths or local home paths.

Approved exceptions: none.

## Dependencies

- `shared-ci` `9ff304e317a5ff924a4c488515ead5a607d28236` — https://github.com/LeePepe/shared-ci/blob/9ff304e317a5ff924a4c488515ead5a607d28236/ai/

## Delivery

- One task → one branch + worktree → one PR using the PR template.
- Changes to gates, lint, schemas, `ai/` or templates are important PRs (Owner review).
- Done = required checks green on the PR head SHA; a new push invalidates old evidence.
