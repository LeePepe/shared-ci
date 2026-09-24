# AGENTS.md — <Repository>

<One sentence: what this repository is.> Every agent that edits it follows the
protocol below. Tool-specific files (CLAUDE.md etc.) only point here.

## Read first

1. `.specify/memory/constitution.md` — non-negotiable principles (if present)
2. `docs/architecture/tech-context.md` — layer table: layer → paths → depends_on
3. The leaf `tech-context.md` of every layer you touch (`scripts/context/contexts <path>`)

## Protocol

Follow `LeePepe/shared-ci@<40-char-sha>/ai/agent-protocol.md`
(https://github.com/LeePepe/shared-ci/blob/<40-char-sha>/ai/agent-protocol.md).
It must be the same SHA as the `uses:` pins in `.github/workflows/`.

## Verify

```sh
git config core.hooksPath .githooks   # once per clone
scripts/verify            # changed layers vs origin/main (what pre-push runs)
scripts/verify --all      # every layer (what CI runs)
```

Never `--no-verify`, never weaken or skip tests, never edit policy/gates to pass.

## Required checks

Merging to `main` requires (must match the ruleset):

- `quality / aggregate`
- `codex-review-target / codex-review`

`kimi-review` is advisory and never required.

## Red lines

- <repository-specific red line>
- No personal account names, credential-profile paths or local home paths in the repo.

Approved exceptions: none.

## Dependencies

- `shared-ci` `<40-char-sha>` — https://github.com/LeePepe/shared-ci/blob/<40-char-sha>/ai/

## Delivery

- One task → one branch + worktree → one PR using `.github/pull_request_template.md`.
- Done = required checks green on the PR head SHA; a new push invalidates old evidence.
- CODEOWNERS paths (`.github/**`, policy/schemas/gates, AGENTS.md, constitution,
  dependency pins) need Owner approval; until enforced, add the `owner-review` label.
