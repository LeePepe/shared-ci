# AGENTS.md — <Repository>

## Read first

1. `.specify/memory/constitution.md` — non-negotiable principles (if present)
2. `docs/architecture/tech-context.md` — layer table: layer → paths → depends_on
3. Relevant leaf `tech-context.md` — layer responsibilities, interfaces and verification
4. `docs/development.md` — repository development steps, PR work units and verification/review sources

## Protocol

Follow `LeePepe/shared-ci@<40-char-sha>/ai/agent-protocol.md`
(https://github.com/LeePepe/shared-ci/blob/<40-char-sha>/ai/agent-protocol.md).

## Verify

[Development verification](docs/development.md#verification-and-review-sources)
and [verify entry](scripts/verify).

## Required checks

[CI caller](.github/workflows/ci.yml), repository protection settings and
[review ownership](.github/CODEOWNERS).

## Red lines

[Root and leaf architecture contracts](docs/architecture/tech-context.md),
the constitution when present, and the pinned protocol above.

## Dependencies

- `shared-ci` `<40-char-sha>` — https://github.com/LeePepe/shared-ci/blob/<40-char-sha>/ai/

## Delivery

[PR work units](docs/development.md#pr-work-units),
[PR template](.github/pull_request_template.md) and the pinned protocol above.
