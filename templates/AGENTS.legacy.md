# AGENTS.md — <Repository>

## Read first

1. `.specify/memory/constitution.md` — non-negotiable principles (if present)
2. `docs/architecture/tech-context.md` — layer table: layer → paths → depends_on
3. Relevant leaf `tech-context.md` — layer responsibilities, interfaces and verification
4. `docs/development.md` — repository development steps, goal-based PR kinds and verification/review sources

## Protocol

Follow `LeePepe/shared-ci@<40-char-sha>/ai/agent-protocol.md`
(https://github.com/LeePepe/shared-ci/blob/<40-char-sha>/ai/agent-protocol.md).

## Verify

[Development verification](docs/development.md#verification-and-review-sources),
[Quality contract (6DQ matrix)](docs/development.md#quality-contract-6dq-matrix)
and [verify entry](scripts/verify).

## Required checks

[CI caller](.github/workflows/ci.yml), repository protection settings and
[review policy](docs/development.md#verification-and-review-sources).

## Red lines

[Root and leaf architecture contracts](docs/architecture/tech-context.md),
the constitution when present, and the pinned protocol above. Keep detailed
incident narratives in `Retrospective.md` and distill at most ~10 concise
one-line recurring project rules into the guide's `Red lines`.

## Dependencies

- `shared-ci` `<40-char-sha>` — https://github.com/LeePepe/shared-ci/blob/<40-char-sha>/ai/

## Delivery

[PR kinds](docs/development.md#pr-kinds),
[PR template](.github/pull_request_template.md) and the pinned protocol above.
